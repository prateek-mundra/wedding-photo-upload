"""
Google Drive integration for the Wedding Photo Upload System.

Auth strategy: OAuth 2.0 client credentials.
  1. Create a Google Cloud project -> enable "Google Drive API".
  2. Create an OAuth client ID (Desktop app or Web app, depending on your setup).
  3. Save the downloaded client JSON as credentials.json in the repo root or set
     GOOGLE_OAUTH_CREDENTIALS_FILE in .env.
  4. On first run, the app opens a browser prompt for authorization and stores
     the resulting token in token.json.
  5. Put your shared Drive folder's ID in .env as DRIVE_ROOT_FOLDER_ID
     (the ID is the long string in the folder's URL after /folders/).
"""

import io
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import google_auth_httplib2  # noqa: F401
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from config import get_settings

OAUTH_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


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


def get_oauth_credentials() -> Credentials:
    settings = get_settings()
    credentials_path = resolve_config_path(settings.google_oauth_credentials_file, "credentials.json")
    token_path = resolve_config_path(settings.google_oauth_token_file, "token.json")

    if not credentials_path.exists():
        raise RuntimeError(
            f"Missing OAuth client credentials. Place the downloaded OAuth client JSON file at "
            f"{credentials_path} or set GOOGLE_OAUTH_CREDENTIALS_FILE to the correct path."
        )

    if token_path.exists():
        try:
            credentials = Credentials.from_authorized_user_file(str(token_path), OAUTH_SCOPES)
        except ValueError:
            credentials = None

        if credentials and credentials.valid:
            return credentials

        if credentials and credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
                token_path.write_text(credentials.to_json(), encoding="utf-8")
                return credentials
            except Exception:
                credentials = None

    client_config = json.loads(credentials_path.read_text(encoding="utf-8"))
    try:
        flow = InstalledAppFlow.from_client_config(client_config, OAUTH_SCOPES)
    except ValueError as exc:
        raise RuntimeError("OAuth client configuration is invalid. Check credentials.json.") from exc

    credentials = flow.run_local_server(port=0)
    token_path.write_text(credentials.to_json(), encoding="utf-8")
    return credentials


@lru_cache
def get_drive_service():
    credentials = get_oauth_credentials()
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


@lru_cache(maxsize=64)
def get_or_create_event_folder(event_name: str) -> str:
    """Return the folder ID for a given event (e.g. 'haldi', 'reception'),
    creating it under ROOT_FOLDER_ID the first time it's requested."""
    service = get_drive_service()
    root_folder_id = get_settings().drive_root_folder_id
    safe_name = event_name.strip().lower() or "general"

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


def upload_file_bytes(
    file_bytes: bytes,
    filename: str,
    mimetype: str,
    event_name: str = "general",
) -> dict:
    """Uploads raw bytes to the Drive folder for `event_name`.
    Returns {id, name, webViewLink}.
    """
    service = get_drive_service()
    folder_id = get_or_create_event_folder(event_name)

    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mimetype, resumable=True)
    metadata = {"name": filename, "parents": [folder_id]}

    uploaded = (
        service.files()
        .create(body=metadata, media_body=media, fields="id, name, webViewLink, size")
        .execute()
    )
    return uploaded


def list_event_files(event_name: str = "general") -> list:
    service = get_drive_service()
    folder_id = get_or_create_event_folder(event_name)
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
