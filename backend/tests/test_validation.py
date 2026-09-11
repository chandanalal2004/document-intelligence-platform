"""
Unit tests for the file-validation layer (page limits, empty files,
unsupported types) -- these run without hitting any external API.
"""
from pathlib import Path

import pytest

from app.services.document_validation_service import DocumentValidationError, validate_upload


def test_rejects_empty_file(tmp_path: Path):
    f = tmp_path / "empty.pdf"
    f.write_bytes(b"")
    with pytest.raises(DocumentValidationError) as exc:
        validate_upload(f, "application/pdf", "empty.pdf")
    assert exc.value.code == "EMPTY_FILE"


def test_rejects_unsupported_extension(tmp_path: Path):
    f = tmp_path / "notes.txt"
    f.write_text("hello")
    with pytest.raises(DocumentValidationError) as exc:
        validate_upload(f, "text/plain", "notes.txt")
    assert exc.value.code == "UNSUPPORTED_FILE_TYPE"


def test_rejects_corrupted_image(tmp_path: Path):
    f = tmp_path / "broken.png"
    f.write_bytes(b"this is not a real png file")
    with pytest.raises(DocumentValidationError) as exc:
        validate_upload(f, "image/png", "broken.png")
    assert exc.value.code == "CORRUPTED_FILE"
