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

from starlette.requests import Request

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


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/api/upload", response_model=UploadResponse)
async def upload_media(
    request: Request,
    file: UploadFile = File(...),
    uploaded_by: str = Form(""),
) -> UploadResponse:
    if not file.content_type or not file.content_type.startswith(ALLOWED_MIME_PREFIXES):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Only image or video files are allowed.")

    original_name = file.filename or "upload"
    safe_filename = f"{uuid.uuid4().hex[:10]}_{original_name}"

    file_obj = await file.read()
    size_bytes = len(file_obj)
    size_mb = size_bytes / (1024 * 1024)
    max_mb = get_settings().max_upload_mb
    if size_mb > max_mb:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=f"File exceeds {max_mb}MB limit.")
    if size_bytes == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Empty file.")

    try:
        uploaded = drive_service.upload_file_stream(
            file_obj=io.BytesIO(file_obj),
            filename=safe_filename,
            mimetype=file.content_type,
        )
    except RuntimeError as exc:
        logger.error("Drive upload failed: %s", exc)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    logger.info(
        "Uploaded %s (%.1fMB) uploaded_by=%r",
        safe_filename, size_mb, uploaded_by,
    )

    return UploadResponse(
        status="success",
        file_id=uploaded.get("id"),
        name=uploaded.get("name"),
        view_link=uploaded.get("webViewLink"),
        event="general",
    )


@app.get("/api/gallery", response_model=GalleryResponse, dependencies=[Depends(require_admin)])
def gallery() -> GalleryResponse:
    """Admin-only: list uploaded files from the shared gallery folder."""
    files = drive_service.list_uploaded_files()
    return GalleryResponse(event="general", count=len(files), files=files)


@app.get("/api/qr")
def qr_code() -> StreamingResponse:
    target_url = f"{get_settings().app_base_url}/app/index.html"
    img = qrcode.make(target_url)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")
