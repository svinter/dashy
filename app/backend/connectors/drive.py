"""Google Drive API connector — syncs recent files to drive_files table.

Also exposes low-level Drive operation helpers used by the Setup page:
  create_drive_folder(name, parent_id)  → (folder_id, web_url)
  list_drive_files(folder_id)           → [{id, name, mimeType, webViewLink}, ...]
  copy_drive_file(file_id, dest_id)     → {id, name, web_url}
"""

from datetime import datetime, timedelta, timezone

import google_auth_httplib2
import httplib2
from googleapiclient.discovery import build

from config import DRIVE_SYNC_DAYS, DRIVE_SYNC_LIMIT
from connectors.google_auth import get_google_credentials
from database import batch_upsert, get_write_db

API_TIMEOUT = 30  # seconds per HTTP request

_FOLDER_MIME = "application/vnd.google-apps.folder"


def _drive_service():
    """Return an authenticated Drive v3 service."""
    creds = get_google_credentials()
    return build("drive", "v3", credentials=creds)


def create_drive_folder(name: str, parent_id: str) -> tuple[str, str]:
    """Create a Drive folder under parent_id.

    Returns (folder_id, web_url).
    Raises RuntimeError on API failure.
    """
    service = _drive_service()
    result = service.files().create(
        body={
            "name": name,
            "mimeType": _FOLDER_MIME,
            "parents": [parent_id],
        },
        fields="id, webViewLink",
    ).execute()
    folder_id = result["id"]
    web_url = result.get("webViewLink") or f"https://drive.google.com/drive/folders/{folder_id}"
    return folder_id, web_url


def list_drive_files(folder_id: str) -> list[dict]:
    """List non-trashed files directly inside folder_id.

    Returns list of {id, name, mimeType, webViewLink}.
    """
    service = _drive_service()
    results = service.files().list(
        q=f"'{folder_id}' in parents and trashed = false",
        fields="files(id, name, mimeType, webViewLink)",
        pageSize=100,
    ).execute()
    return results.get("files", [])


def copy_drive_file(file_id: str, dest_folder_id: str) -> dict:
    """Copy file_id into dest_folder_id, preserving its original name.

    Returns {id, name, web_url}.
    """
    service = _drive_service()
    result = service.files().copy(
        fileId=file_id,
        body={"parents": [dest_folder_id]},
        fields="id, name, webViewLink",
    ).execute()
    return {
        "id": result["id"],
        "name": result.get("name", ""),
        "web_url": result.get("webViewLink", ""),
    }


def sync_drive_files() -> int:
    """Sync recently modified Drive files to local database."""
    creds = get_google_credentials()
    authed_http = google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=API_TIMEOUT))
    service = build("drive", "v3", http=authed_http)

    cutoff = (datetime.now(timezone.utc) - timedelta(days=DRIVE_SYNC_DAYS)).isoformat()

    # Phase 1: Fetch from API (no DB connection held)
    all_files: list[dict] = []
    page_token = None
    while True:
        results = (
            service.files()
            .list(
                q=f"modifiedTime > '{cutoff}' and trashed = false",
                fields=(
                    "nextPageToken, files(id, name, mimeType, webViewLink, iconLink, "
                    "createdTime, modifiedTime, lastModifyingUser, owners, shared, "
                    "starred, trashed, parents, size, description, thumbnailLink)"
                ),
                orderBy="modifiedTime desc",
                pageSize=100,
                pageToken=page_token,
            )
            .execute()
        )
        all_files.extend(results.get("files", []))
        page_token = results.get("nextPageToken")
        if not page_token or len(all_files) >= DRIVE_SYNC_LIMIT:
            break

    all_files = all_files[:DRIVE_SYNC_LIMIT]

    # Phase 2: Build rows
    rows = []
    for f in all_files:
        last_mod_user = f.get("lastModifyingUser", {})
        owners = f.get("owners", [{}])
        owner = owners[0] if owners else {}
        parents = f.get("parents", [])

        rows.append(
            (
                f["id"],
                f.get("name", ""),
                f.get("mimeType", ""),
                f.get("webViewLink", ""),
                f.get("iconLink", ""),
                f.get("createdTime", ""),
                f.get("modifiedTime", ""),
                last_mod_user.get("emailAddress", ""),
                last_mod_user.get("displayName", ""),
                owner.get("emailAddress", ""),
                owner.get("displayName", ""),
                int(f.get("shared", False)),
                int(f.get("starred", False)),
                int(f.get("trashed", False)),
                parents[0] if parents else None,
                None,  # parent_name — resolved separately if needed
                int(f.get("size", 0) or 0),
                f.get("description", ""),
                "",  # content_preview — populated by docs sync
                f.get("thumbnailLink", ""),
            )
        )

    # Phase 3: Batch upsert
    with get_write_db() as db:
        batch_upsert(
            db,
            """INSERT OR REPLACE INTO drive_files
               (id, name, mime_type, web_view_link, icon_link,
                created_time, modified_time, modified_by_email, modified_by_name,
                owner_email, owner_name, shared, starred, trashed,
                parent_id, parent_name, size_bytes, description,
                content_preview, thumbnail_link)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

    return len(rows)
