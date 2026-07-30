"""
Google Drive integration for the Wedding Photo Upload System.

Auth strategy: OAuth 2.0 client credentials.
  1. Create a Google Cloud project -> enable "Google Drive API".
  2. Create an OAuth client ID (Desktop app or Web app, depending on your setup).
  3. Provide the downloaded client JSON via GOOGLE_OAUTH_CREDENTIALS_JSON
     (preferred for Railway) or via a local file path using GOOGLE_OAUTH_CREDENTIALS_FILE.
  4. Provide an authorized user token payload via GOOGLE_OAUTH_TOKEN_JSON
     (preferred for Railway). For local development you can still use token.json.
  5. Put your shared Drive folder's ID in .env as DRIVE_ROOT_FOLDER_ID
     (the ID is the long string in the folder's URL after /folders/).
"""

import io
import json
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

import google_auth_httplib2  # noqa: F401
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from requests import exceptions as requests_exceptions

from config import get_settings

OAUTH_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2
REQUEST_TIMEOUT_SECONDS = 60


def resolve_config_path(config_value: str, default_name: str) -> Path:
    candidate = Path(config_value or default_name)
    if candidate.is_absolute():
        return candidate

    cwd_candidate = Path.cwd() / candidate
    project_candidate = Path(__file__).resolve().parent / candidate

    for path in (cwd_candidate, project_candidate):
        if path.exists():
            return path.resolve()

    return project_candidate.resolve()


def _load_json_from_env(raw_value: str | None) -> dict[str, Any]:
    if not raw_value:
        raise RuntimeError("Missing required OAuth JSON environment variable.")

    try:
        return json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise RuntimeError("OAuth JSON environment variable is not valid JSON.") from exc


def get_oauth_credentials() -> Credentials:
    settings = get_settings()

    try:
        client_config = _load_json_from_env(settings.google_oauth_credentials_json)
    except RuntimeError as exc:
        raise RuntimeError(
            "Missing OAuth client credentials. Set GOOGLE_OAUTH_CREDENTIALS_JSON to a valid client JSON payload."
        ) from exc

    try:
        token_payload = _load_json_from_env(settings.google_oauth_token_json)
    except RuntimeError as exc:
        raise RuntimeError(
            "Missing OAuth token. Set GOOGLE_OAUTH_TOKEN_JSON to a valid authorized-user token payload."
        ) from exc

    try:
        credentials = Credentials.from_authorized_user_info(token_payload, OAUTH_SCOPES)
    except ValueError as exc:
        raise RuntimeError("OAuth token payload is invalid.") from exc

    if credentials.valid:
        return credentials

    if credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
            return credentials
        except Exception as exc:
            raise RuntimeError("OAuth token refresh failed.") from exc

    raise RuntimeError("OAuth token is not usable. Provide a fresh authorized-user token payload.")


@lru_cache
def get_drive_service():
    credentials = get_oauth_credentials()
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def get_authorized_session() -> AuthorizedSession:
    credentials = get_oauth_credentials()
    return AuthorizedSession(credentials)


@lru_cache(maxsize=64)
def get_or_create_upload_folder() -> str:
    """Return the shared upload folder ID, creating it under DRIVE_ROOT_FOLDER_ID if needed."""
    service = get_drive_service()
    root_folder_id = get_settings().drive_root_folder_id
    safe_name = "uploads"

    parent_filter = f"'{root_folder_id}' in parents" if root_folder_id else "'root' in parents"
    query = (
        f"{parent_filter} "
        f"and mimeType='application/vnd.google-apps.folder' "
        f"and name='{safe_name}' and trashed=false"
    )
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]

    metadata: dict[str, Any] = {
        "name": safe_name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if root_folder_id:
        metadata["parents"] = [root_folder_id]
    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def _retry_drive_call(fn, *args, **kwargs) -> Any:
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except (requests_exceptions.Timeout, requests_exceptions.RequestException, Exception) as exc:
            last_error = exc
            if attempt == MAX_RETRIES - 1:
                raise RuntimeError(f"Google Drive request failed after {MAX_RETRIES} attempts: {exc}") from exc
            time.sleep(RETRY_DELAY_SECONDS)
    if last_error is not None:
        raise RuntimeError(str(last_error))
    raise RuntimeError("Google Drive request failed")


def upload_file_stream(
    file_obj: Any,
    filename: str,
    mimetype: str,
) -> dict:
    """Upload a file-like object to the shared Drive folder with retries and timeout handling."""
    service = get_drive_service()
    folder_id = get_or_create_upload_folder()

    media = MediaIoBaseUpload(file_obj, mimetype=mimetype, resumable=True)
    metadata = {"name": filename, "parents": [folder_id]}

    def create_file() -> dict:
        return (
            service.files()
            .create(
                body=metadata,
                media_body=media,
                fields="id, name, webViewLink, size",
            )
            .execute()
        )

    return _retry_drive_call(create_file)


def list_uploaded_files() -> list:
    service = get_drive_service()
    folder_id = get_or_create_upload_folder()
    query = f"'{folder_id}' in parents and trashed=false"
    results = (
        service.files()
        .list(
            q=query,
            fields="files(id, name, mimeType, webViewLink, thumbnailLink, createdTime, size)",
            orderBy="createdTime desc",
            pageSize=200,
        )
        .execute()
    )
    return results.get("files", [])
