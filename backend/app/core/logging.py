"""
Centralized logging configuration. Import `get_logger(__name__)` anywhere
in the app to get a configured logger. Logs go to stdout (picked up by
most PaaS platforms like Render/Railway) and to a rotating local file.
"""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.config import settings

_LOG_DIR = Path(settings.UPLOAD_DIR).parent / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_FILE = _LOG_DIR / "app.log"

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

_configured = False


def _configure_root_logger():
    global _configured
    if _configured:
        return
    root = logging.getLogger()
    root.setLevel(settings.LOG_LEVEL)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(stream_handler)

    file_handler = RotatingFileHandler(_LOG_FILE, maxBytes=5_000_000, backupCount=3)
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(file_handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    _configure_root_logger()
    return logging.getLogger(name)
