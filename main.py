"""
Wedding Photo Upload System — FastAPI backend.

Run locally:
    uvicorn main:app --reload --host 0.0.0.0 --port 8000

Endpoints:
    POST /api/upload             guest uploads a photo/video (multipart/form-data)
    GET  /api/gallery/{event}    list files for an event (admin-only, needs X-Admin-Token)
    GET  /api/qr/{event}         returns a QR PNG that deep-links to the upload page
    GET  /health                 healthcheck
"""

import io
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import qrcode
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

import drive_service
from auth import require_admin
from config import get_settings
from schemas import GalleryResponse, HealthResponse, UploadResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("wedding_upload")

ALLOWED_EVENTS = {"general"}
ALLOWED_MIME_PREFIXES = ("image/", "video/")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("Starting up. APP_BASE_URL=%s", settings.app_base_url)
    if not settings.admin_token:
        logger.warning("ADMIN_TOKEN is not set — /api/gallery/* will be locked until you set it in .env")
    yield
    logger.info("Shutting down.")


app = FastAPI(title="Wedding Photo Upload System", lifespan=lifespan)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"
if not FRONTEND_DIR.exists():
    FRONTEND_DIR = BASE_DIR
app.mount("/app", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


def get_validated_event(event: str) -> str:
    """Normalize and validate an event name; raises 404 if unknown."""
    normalized = event.strip().lower()
    if normalized not in ALLOWED_EVENTS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Unknown event '{event}'")
    return normalized


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/api/upload", response_model=UploadResponse)
async def upload_media(
    file: UploadFile = File(...),
    event: str = Form("general"),
    uploaded_by: str = Form(""),
) -> UploadResponse:
    normalized_event = "general"

    if not file.content_type or not file.content_type.startswith(ALLOWED_MIME_PREFIXES):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Only image or video files are allowed.")

    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)
    max_mb = get_settings().max_upload_mb
    if size_mb > max_mb:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=f"File exceeds {max_mb}MB limit.")
    if size_mb == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Empty file.")

    original_name = file.filename or "upload"
    safe_filename = f"{uuid.uuid4().hex[:10]}_{original_name}"

    try:
        uploaded = drive_service.upload_file_bytes(
            file_bytes=contents,
            filename=safe_filename,
            mimetype=file.content_type,
            event_name=normalized_event,
        )
    except RuntimeError as exc:
        logger.error("Drive upload failed: %s", exc)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    logger.info(
        "Uploaded %s (%.1fMB) event=%s uploaded_by=%r",
        safe_filename, size_mb, normalized_event, uploaded_by,
    )

    return UploadResponse(
        status="success",
        file_id=uploaded.get("id"),
        name=uploaded.get("name"),
        view_link=uploaded.get("webViewLink"),
        event=normalized_event,
    )


@app.get("/api/gallery/{event}", response_model=GalleryResponse, dependencies=[Depends(require_admin)])
def gallery(event: str) -> GalleryResponse:
    """Admin-only: list uploaded files for an event. Requires header
    'X-Admin-Token: <ADMIN_TOKEN from .env>'."""
    normalized_event = get_validated_event(event)
    files = drive_service.list_event_files(normalized_event)
    return GalleryResponse(event=normalized_event, count=len(files), files=files)


@app.get("/api/qr")
def qr_code() -> StreamingResponse:
    target_url = f"{get_settings().app_base_url}/app/index.html"
    img = qrcode.make(target_url)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")
