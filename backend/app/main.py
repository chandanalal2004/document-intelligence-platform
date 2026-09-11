"""
FastAPI application entrypoint. Wires up the API router, DB init,
CORS, error handling, and serves the HTML/CSS/JS frontend.
"""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes.documents import router as documents_router
from app.core.config import settings
from app.core.database import init_db
from app.core.logging import get_logger

logger = get_logger(__name__)

app = FastAPI(
    title=settings.APP_NAME,
    description="Intelligent document extraction, validation & API platform.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents_router, prefix="/api/v1")

# --- Frontend (server-rendered HTML/CSS/JS, per case study section 6) ---
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
templates = Jinja2Templates(directory=str(FRONTEND_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR / "static")), name="static")


@app.on_event("startup")
def on_startup():
    init_db()
    logger.info("%s starting up (env=%s)", settings.APP_NAME, settings.ENV)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Never leak stack traces / internals to the client.
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."}},
    )


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/documents/{document_name}", response_class=HTMLResponse, include_in_schema=False)
def document_result_page(request: Request, document_name: str):
    return templates.TemplateResponse(
        "document_result.html", {"request": request, "document_name": document_name}
    )
