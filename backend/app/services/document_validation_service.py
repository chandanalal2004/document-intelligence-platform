"""
Input-control layer: validates the uploaded file BEFORE any OCR/AI work
happens. This is deliberately dumb about document *type* (invoice vs.
balance sheet) -- that is chosen by the user in the frontend. It only
checks that the file is a supported, readable, non-corrupt PDF/JPG/PNG
within the page limit.
"""
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, UnidentifiedImageError

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class DocumentValidationError(Exception):
    """Raised for a file that fails validation. Carries an API error code."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class FileValidationResult:
    file_type: str
    is_supported: bool
    is_readable: bool
    page_count: Optional[int]
    status: str
    reason: Optional[str] = None


def _get_pdf_page_count(path: Path) -> int:
    try:
        out = subprocess.run(
            ["pdfinfo", str(path)], capture_output=True, text=True, timeout=15
        )
        for line in out.stdout.splitlines():
            if line.lower().startswith("pages:"):
                return int(line.split(":", 1)[1].strip())
        raise ValueError("Pages field not found in pdfinfo output")
    except Exception as exc:
        raise DocumentValidationError(
            "CORRUPTED_FILE", f"Could not read PDF page count: {exc}"
        )


def validate_upload(
    file_path: Path, content_type: str, declared_filename: str
) -> FileValidationResult:
    """
    Runs all mandatory pre-extraction checks. Raises DocumentValidationError
    on failure (caller converts this into the FAILED response), otherwise
    returns a FileValidationResult with status PASS.
    """
    ext = Path(declared_filename).suffix.lower()
    is_supported = content_type in settings.ALLOWED_CONTENT_TYPES or ext in (
        ".pdf",
        ".jpg",
        ".jpeg",
        ".png",
    )

    if not file_path.exists() or file_path.stat().st_size == 0:
        raise DocumentValidationError("EMPTY_FILE", "Uploaded file is empty.")

    size_mb = file_path.stat().st_size / (1024 * 1024)
    if size_mb > settings.MAX_FILE_SIZE_MB:
        raise DocumentValidationError(
            "FILE_TOO_LARGE",
            f"File exceeds the maximum allowed size of {settings.MAX_FILE_SIZE_MB}MB.",
        )

    if not is_supported:
        raise DocumentValidationError(
            "UNSUPPORTED_FILE_TYPE", "Only PDF / JPG / PNG documents are supported."
        )

    if ext == ".pdf" or content_type == "application/pdf":
        page_count = _get_pdf_page_count(file_path)
        if page_count < 1:
            raise DocumentValidationError("CORRUPTED_FILE", "PDF has no readable pages.")
        if page_count > settings.MAX_PAGE_COUNT:
            raise DocumentValidationError(
                "PAGE_LIMIT_EXCEEDED",
                f"Document exceeds the {settings.MAX_PAGE_COUNT}-page limit "
                f"({page_count} pages found).",
            )
        logger.info("PDF validated: %s pages=%s", declared_filename, page_count)
        return FileValidationResult(
            file_type="application/pdf",
            is_supported=True,
            is_readable=True,
            page_count=page_count,
            status="PASS",
        )

    # Image (JPG/PNG)
    try:
        with Image.open(file_path) as img:
            img.verify()
        file_type = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
        logger.info("Image validated: %s", declared_filename)
        return FileValidationResult(
            file_type=file_type,
            is_supported=True,
            is_readable=True,
            page_count=1,
            status="PASS",
        )
    except (UnidentifiedImageError, OSError) as exc:
        raise DocumentValidationError("CORRUPTED_FILE", f"Image could not be read: {exc}")
