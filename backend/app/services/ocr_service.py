"""
Text extraction / OCR service.

Strategy:
  - Native PDFs: extract embedded text per page with `pdftotext` (poppler).
    Fast and highly accurate -- no OCR errors.
  - Scanned PDFs (little/no embedded text): rasterize each page with
    `pdftoppm` and run Tesseract OCR on the resulting images.
  - JPG/PNG: run Tesseract OCR directly.

Returns per-page text plus a flag indicating whether OCR was used, so the
caller can report `ocr_used` in processing_metadata and reason about
extraction reliability.
"""
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List

import pytesseract
from PIL import Image

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PageText:
    page_number: int
    text: str


@dataclass
class ExtractionResult:
    pages: List[PageText]
    ocr_used: bool

    @property
    def full_text(self) -> str:
        return "\n\n".join(f"[PAGE {p.page_number}]\n{p.text}" for p in self.pages)


def _native_pdf_text(pdf_path: Path, page_count: int) -> List[PageText]:
    pages = []
    for i in range(1, page_count + 1):
        out = subprocess.run(
            ["pdftotext", "-f", str(i), "-l", str(i), "-layout", str(pdf_path), "-"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        pages.append(PageText(page_number=i, text=out.stdout.strip()))
    return pages


def _rasterize_pdf_page(pdf_path: Path, page_number: int, out_dir: Path) -> Path:
    prefix = out_dir / f"page_{page_number}"
    subprocess.run(
        [
            "pdftoppm",
            "-f", str(page_number), "-l", str(page_number),
            "-r", "300", "-png",
            str(pdf_path), str(prefix),
        ],
        check=True,
        timeout=60,
    )
    candidates = sorted(out_dir.glob(f"page_{page_number}*.png"))
    if not candidates:
        raise RuntimeError(f"Failed to rasterize page {page_number} of {pdf_path.name}")
    return candidates[0]


def _ocr_image(image_path: Path) -> str:
    """
    Word-level OCR with row reconstruction.

    Plain pytesseract.image_to_string() relies on Tesseract's own layout
    analysis, which frequently segments multi-column financial tables into
    separate blocks (e.g. label column vs. numeric columns), then emits
    those blocks sequentially -- destroying the row alignment between a
    line-item label and its value. Reconstructing rows from word bounding
    boxes (grouped purely by vertical position, independent of Tesseract's
    block/par grouping) avoids that failure mode.
    """
    with Image.open(image_path) as img:
        img = img.convert("L")

        # Upscale the receipt before OCR
        scale = 2
        img = img.resize(
            (img.width * scale, img.height * scale),
            Image.Resampling.LANCZOS,
        )

        data = pytesseract.image_to_data(
            img,
            config="--psm 6",
            output_type=pytesseract.Output.DICT,
        )
    words = [
        {"text": data["text"][i].strip(), "left": data["left"][i], "top": data["top"][i], "height": data["height"][i]}
        for i in range(len(data["text"]))
        if data["text"][i].strip()
    ]
    if not words:
        return ""

    words.sort(key=lambda w: w["top"])
    median_height = sorted(w["height"] for w in words)[len(words) // 2]
    row_tolerance = max(median_height * 0.6, 10)

    rows = []
    current_row = [words[0]]
    current_top = words[0]["top"]

    for w in words[1:]:
        if abs(w["top"] - current_top) <= row_tolerance:
            current_row.append(w)
            current_top = (current_top + w["top"]) / 2
        else:
            rows.append(current_row)
            current_row = [w]
            current_top = w["top"]
    rows.append(current_row)

    lines = []
    for row in rows:
        row.sort(key=lambda w: w["left"])
        lines.append("  ".join(w["text"] for w in row))

    return "\n".join(lines)


def extract_text(file_path: Path, file_type: str, page_count: int) -> ExtractionResult:
    """
    Main entry point. `file_type` is the validated MIME type
    (application/pdf, image/jpeg, image/png).
    """
    if file_type == "application/pdf":
        pages = _native_pdf_text(file_path, page_count)
        total_chars = sum(len(p.text) for p in pages)
        avg_chars_per_page = total_chars / max(page_count, 1)

        if avg_chars_per_page >= settings.NATIVE_TEXT_MIN_CHARS_PER_PAGE:
            logger.info(
                "Native text extraction sufficient for %s (%.0f chars/page)",
                file_path.name, avg_chars_per_page,
            )
            return ExtractionResult(pages=pages, ocr_used=False)

        # Sparse text -> likely a scanned PDF. Fall back to OCR per page.
        logger.info(
            "Native text sparse (%.0f chars/page) for %s -- falling back to OCR",
            avg_chars_per_page, file_path.name,
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ocr_pages = []
            for i in range(1, page_count + 1):
                img_path = _rasterize_pdf_page(file_path, i, tmp_path)
                text = _ocr_image(img_path)
                ocr_pages.append(PageText(page_number=i, text=text.strip()))
            return ExtractionResult(pages=ocr_pages, ocr_used=True)

    else:
    # JPG / PNG
        text = _ocr_image(file_path)
        print("\n===== OCR TEXT =====")
        print(text)
        print("===== END OCR TEXT =====\n")
        return ExtractionResult(pages=[PageText(page_number=1, text=text.strip())], ocr_used=True)