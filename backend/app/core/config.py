"""
Application configuration.
All secrets/config are read from environment variables (never hardcoded).
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

class Settings:
    # --- General ---
    APP_NAME: str = "Document Intelligence Platform"
    ENV: str = os.getenv("ENV", "development")

    # --- LLM provider (used for AI-based field extraction) ---
    # Groq's API is OpenAI Chat-Completions compatible, so we reuse the
    # `openai` SDK pointed at Groq's base URL. Get a key at console.groq.com.
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

    # --- Database ---
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'storage' / 'app.db'}"
    )

    # --- File handling ---
    UPLOAD_DIR: Path = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "storage" / "uploads")))
    MAX_PAGE_COUNT: int = int(os.getenv("MAX_PAGE_COUNT", "3"))
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "15"))
    ALLOWED_CONTENT_TYPES = {
        "application/pdf": ".pdf",
        "image/jpeg": ".jpg",
        "image/png": ".png",
    }

    # --- OCR ---
    # Below this many extracted characters per page, we treat the PDF as a
    # scan and fall back to rasterizing + Tesseract OCR.
    NATIVE_TEXT_MIN_CHARS_PER_PAGE: int = int(os.getenv("NATIVE_TEXT_MIN_CHARS_PER_PAGE", "40"))

    # --- CORS ---
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")

    # --- Logging ---
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
