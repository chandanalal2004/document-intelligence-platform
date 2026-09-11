"""
REST API routes (case study section 5).
"""
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.repositories.document_repository import DocumentRepository
from app.schemas.document import DocumentListItem, DocumentType, ErrorResponse
from app.services.document_service import DocumentProcessingError, process_document

logger = get_logger(__name__)
router = APIRouter()


def _error(code: str, message: str, status_code: int):
    return HTTPException(status_code=status_code, detail={"error": {"code": code, "message": message}})


@router.get("/health", tags=["health"])
def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as exc:  # pragma: no cover
        logger.error("Health check DB failure: %s", exc)
        db_status = "error"
    return {"status": "ok", "database": db_status}


@router.post("/documents/process", tags=["documents"])
async def process_document_endpoint(
    file: UploadFile = File(...),
    document_type: DocumentType = Form(...),
    db: Session = Depends(get_db),
):
    if not file.filename:
        raise _error("INVALID_UPLOAD", "No file was uploaded.", 400)

    dest_name = f"{uuid.uuid4().hex}_{file.filename}"
    dest_path = Path(settings.UPLOAD_DIR) / dest_name

    try:
        with dest_path.open("wb") as out:
            shutil.copyfileobj(file.file, out)
    except Exception as exc:
        logger.exception("Failed to persist upload")
        raise _error("UPLOAD_FAILED", f"Could not save uploaded file: {exc}", 500)
    finally:
        file.file.close()

    try:
        result = process_document(
            db,
            file_path=dest_path,
            document_name=file.filename,
            document_type=document_type.value,
            content_type=file.content_type or "",
        )
        return result
    except DocumentProcessingError as exc:
        logger.warning("Processing failed for %s: %s (%s)", file.filename, exc.message, exc.code)
        raise _error(exc.code, exc.message, exc.http_status)
    except Exception as exc:
        logger.exception("Unexpected error processing %s", file.filename)
        raise _error("INTERNAL_ERROR", "An unexpected error occurred while processing the document.", 500)
    finally:
        # Clean up the stored upload; we keep only the structured result.
        dest_path.unlink(missing_ok=True)


@router.get("/documents/{document_name}", tags=["documents"])
def get_document_by_name(document_name: str, db: Session = Depends(get_db)):
    repo = DocumentRepository(db)
    record = repo.get_latest_by_name(document_name)
    if not record:
        raise _error("DOCUMENT_NOT_FOUND", f"No processed result found for '{document_name}'.", 404)
    import json
    return json.loads(record.result_json)


@router.get("/documents", tags=["documents"], response_model=list[DocumentListItem])
def list_documents(db: Session = Depends(get_db)):
    repo = DocumentRepository(db)
    records = repo.list_all()
    return [
        DocumentListItem(
            document_name=r.document_name,
            document_type=r.document_type,
            processing_status=r.processing_status,
            overall_validation_status=r.overall_validation_status,
            processed_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in records
    ]
