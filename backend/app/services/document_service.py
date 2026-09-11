"""
Orchestrates the full pipeline for one uploaded document:
  validate -> OCR/text extraction -> AI field extraction ->
  financial validation -> build structured response -> persist.

This is the only place that knows the *order* of the pipeline; each step
itself lives in its own service so responsibilities stay separated
(section 9 of the case study).
"""
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.repositories.document_repository import DocumentRepository
from app.services import extraction_service, financial_validation_service, ocr_service
from app.services.document_validation_service import (
    DocumentValidationError,
    validate_upload,
)

logger = get_logger(__name__)


class DocumentProcessingError(Exception):
    """Wraps any pipeline failure with an API-facing error code."""

    def __init__(self, code: str, message: str, http_status: int = 422):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


def _build_extracted_data(field_result: Dict[str, Any]) -> Dict[str, Any]:
    """Converts the LLM's {"fields": {...}} shape into the response's
    extracted_data shape, with each field carrying value/page_number/evidence."""
    extracted: Dict[str, Any] = {}

    for name, entry in field_result.get("fields", {}).items():
        if not isinstance(entry, dict):
            extracted[name] = {
                "value": entry,
                "page_number": None,
                "evidence": None,
            }
            continue

        extracted[name] = {
            "value": entry.get("value"),
            "page_number": entry.get("page_number"),
            "evidence": (
                {
                    "source_text": entry.get("evidence"),
                    "page_number": entry.get("page_number"),
                }
                if entry.get("evidence")
                else None
            ),
        }

    if field_result.get("line_items"):
        extracted["line_items"] = field_result["line_items"]

    return extracted


def _fields_for_validation(field_result: Dict[str, Any]) -> Dict[str, Any]:
    """financial_validation_service expects {"field": {"value": ...}}."""
    return field_result.get("fields", {})


def process_document(
    db: Session,
    *,
    file_path: Path,
    document_name: str,
    document_type: str,
    content_type: str,
) -> Dict[str, Any]:
    repo = DocumentRepository(db)
    start = time.monotonic()

    # --- 1. Document validation (fail fast, gracefully) ---
    try:
        file_validation = validate_upload(
            file_path,
            content_type,
            document_name,
        )
    except DocumentValidationError as exc:
        result = _build_failed_response(
            document_name,
            document_type,
            code=exc.code,
            message=exc.message,
        )

        repo.save_result(
            document_name=document_name,
            document_type=document_type,
            processing_status="FAILED",
            overall_validation_status=None,
            page_count=None,
            ocr_used=False,
            result=result,
            processing_time_ms=int(
                (time.monotonic() - start) * 1000
            ),
        )

        raise DocumentProcessingError(
            exc.code,
            exc.message,
            http_status=422,
        ) from exc

    # --- 2. OCR / text extraction ---
    try:
        extraction = ocr_service.extract_text(
            file_path,
            file_validation.file_type,
            file_validation.page_count or 1,
        )
    except Exception as exc:
        logger.exception(
            "OCR extraction failed for %s",
            document_name,
        )

        return _persist_failure(
            repo,
            document_name,
            document_type,
            file_validation,
            False,
            "OCR_FAILED",
            f"Text extraction failed: {exc}",
            start,
        )

    if not extraction.full_text.strip():
        return _persist_failure(
            repo,
            document_name,
            document_type,
            file_validation,
            extraction.ocr_used,
            "NO_EXTRACTABLE_TEXT",
            "No readable text could be extracted from the document.",
            start,
        )

    # --- 3. AI-based field & table extraction ---
    try:
        field_result = extraction_service.extract_fields(
            document_type,
            extraction.full_text,
        )
    except Exception as exc:
        logger.exception(
            "AI extraction failed for %s",
            document_name,
        )

        return _persist_failure(
            repo,
            document_name,
            document_type,
            file_validation,
            extraction.ocr_used,
            "EXTRACTION_FAILED",
            f"AI field extraction failed: {exc}",
            start,
        )

    extracted_data = _build_extracted_data(field_result)

    # --- 4. Financial validation ---
    validation = financial_validation_service.run_validation(
        document_type,
        _fields_for_validation(field_result),
        field_result.get("line_items", []),
        field_result.get("periods", []),
    )

    # --- 5. Determine overall processing status ---
    required = extraction_service.REQUIRED_FIELDS.get(document_type, [])

    if document_type == "invoice":
        # Some invoice/receipt fields are legitimately absent,
        # such as customer_name, subtotal, or tax_amount.
        #
        # Receipts may use "date" instead of "invoice_date".
        has_date = (
            extracted_data.get("invoice_date", {}).get("value") is not None
            or extracted_data.get("date", {}).get("value") is not None
        )

        has_currency = (
            extracted_data.get("currency", {}).get("value") is not None
        )

        has_total = (
            extracted_data.get("total_amount", {}).get("value") is not None
        )

        has_minimum_fields = (
            has_date
            and has_currency
            and has_total
        )

        extracted_required_present = sum(
            [has_date, has_currency, has_total]
        )

    else:
        extracted_required_present = sum(
            1
            for f in required
            if extracted_data.get(f, {}).get("value") is not None
        )

        has_minimum_fields = extracted_required_present >= max(
            1,
            len(required) // 2,
        )

    # PASS = required fields were extracted AND validations were able to run.
    # A FAILED financial check is surfaced inside validation.issues rather
    # than flipping the whole document to FAILED -- only a document where we
    # couldn't extract meaningful data at all is marked FAILED.
    processing_status = "PASS" if has_minimum_fields else "FAILED"

    response = {
        "document_name": document_name,
        "document_type": document_type,
        "processing_status": processing_status,
        "file_validation": {
            "file_type": file_validation.file_type,
            "is_supported": file_validation.is_supported,
            "is_readable": file_validation.is_readable,
            "page_count": file_validation.page_count,
            "status": file_validation.status,
        },
        "extracted_data": extracted_data,
        "validation": validation,
        "processing_metadata": {
            "ocr_used": extraction.ocr_used,
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "processing_time_ms": int(
                (time.monotonic() - start) * 1000
            ),
        },
    }

    repo.save_result(
        document_name=document_name,
        document_type=document_type,
        processing_status=processing_status,
        overall_validation_status=validation["overall_status"],
        page_count=file_validation.page_count,
        ocr_used=extraction.ocr_used,
        result=response,
        processing_time_ms=response["processing_metadata"]["processing_time_ms"],
    )

    return response


def _build_failed_response(
    document_name: str,
    document_type: str,
    *,
    code: str,
    message: str,
) -> Dict[str, Any]:
    return {
        "document_name": document_name,
        "document_type": document_type,
        "processing_status": "FAILED",
        "file_validation": {
            "file_type": "unknown",
            "is_supported": False,
            "is_readable": False,
            "page_count": None,
            "status": "FAILED",
            "reason": message,
        },
        "extracted_data": {},
        "validation": {
            "checks": [],
            "overall_status": "NOT_APPLICABLE",
            "issues": [message],
        },
        "processing_metadata": {
            "ocr_used": False,
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "processing_time_ms": 0,
        },
        "error": {
            "code": code,
            "message": message,
        },
    }


def _persist_failure(
    repo,
    document_name,
    document_type,
    file_validation,
    ocr_used,
    code,
    message,
    start,
):
    result = _build_failed_response(
        document_name,
        document_type,
        code=code,
        message=message,
    )

    result["file_validation"] = {
        "file_type": file_validation.file_type,
        "is_supported": file_validation.is_supported,
        "is_readable": file_validation.is_readable,
        "page_count": file_validation.page_count,
        "status": "PASS",
    }

    result["processing_metadata"]["processing_time_ms"] = int(
        (time.monotonic() - start) * 1000
    )

    result["processing_metadata"]["ocr_used"] = ocr_used

    repo.save_result(
        document_name=document_name,
        document_type=document_type,
        processing_status="FAILED",
        overall_validation_status=None,
        page_count=file_validation.page_count,
        ocr_used=ocr_used,
        result=result,
        processing_time_ms=result["processing_metadata"]["processing_time_ms"],
    )

    raise DocumentProcessingError(
        code,
        message,
        http_status=422,
    )