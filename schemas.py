"""Pydantic models for request/response validation and OpenAPI docs."""

from pydantic import BaseModel


class UploadResponse(BaseModel):
    status: str
    file_id: str | None = None
    name: str | None = None
    view_link: str | None = None
    event: str


class GalleryFile(BaseModel):
    id: str
    name: str
    mimeType: str
    webViewLink: str | None = None
    thumbnailLink: str | None = None
    createdTime: str | None = None
    size: str | None = None


class GalleryResponse(BaseModel):
    event: str
    count: int
    files: list[GalleryFile]


class HealthResponse(BaseModel):
    status: str
