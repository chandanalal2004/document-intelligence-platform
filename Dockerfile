FROM python:3.12-slim

# System dependencies: Tesseract OCR (pytesseract) + Poppler (pdftotext/pdftoppm).
# These are the same tools you installed manually on Windows; apt handles them
# automatically here and puts both on PATH, so no code changes are needed.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first so Docker can cache this layer
# separately from application code (faster rebuilds).
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy the actual application. Frontend must stay a sibling of backend/,
# matching main.py's Path(__file__).parent.parent.parent / "frontend" lookup.
COPY backend backend
COPY frontend frontend

WORKDIR /app/backend

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Most free hosts (Render, Railway) inject a $PORT env var and expect the
# app to bind to it; ${PORT:-8000} falls back to 8000 for local `docker run`.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]