import json
import logging
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import httpx

from app.config.settings import settings
from app.core.errors import UnauthorizedError, ForbiddenError, safe_error_detail, UpstreamServiceError, \
    ExternalServiceUnavailableError, InvalidUpstreamResponseError

logger = logging.getLogger(__name__)

_FILE_PATH = re.compile(r"/file/d/([A-Za-z0-9_-]+)")
_DOCS_PATH = re.compile(r"/(presentation|document|spreadsheets)/d/([A-Za-z0-9_-]+)")

_EXPORT_TARGETS = {
    "presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "presentation.pptx",
    ),
    "document": ("application/pdf", "document.pdf"),
    "spreadsheets": ("application/pdf", "spreadsheet.pdf"),
}


@dataclass(frozen=True)
class DriveFileRef:
    """A Google Drive file referenced by a user-facing URL."""

    file_id: str
    export_mime_type: str | None = None
    file_name: str = "drive-file"


def parse_drive_url(url: str) -> DriveFileRef | None:
    """Extract a Drive file id from the link shapes Google shows to users.

    Covers drive.google.com/file/d/<id>/view, open?id=..., uc?id=...,
    drive.usercontent.google.com/download?id=..., and the Google Docs editors
    (presentation/document/spreadsheets), which have to be exported instead of
    downloaded with alt=media.
    """
    if not isinstance(url, str) or not url.strip():
        return None
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()

    if host == "docs.google.com":
        match = _DOCS_PATH.search(parsed.path)
        if match:
            kind, file_id = match.groups()
            mime_type, file_name = _EXPORT_TARGETS[kind]
            return DriveFileRef(file_id, mime_type, file_name)
        return None

    if host not in {"drive.google.com", "drive.usercontent.google.com"}:
        return None

    match = _FILE_PATH.search(parsed.path)
    if match:
        return DriveFileRef(match.group(1))

    file_id = parse_qs(parsed.query).get("id", [None])[0]
    if file_id:
        return DriveFileRef(file_id)
    return None


def _check_error(response: httpx.Response):
    logger.info(
        "Drive HTTP response: method=%s url=%s status=%s",
        response.request.method if response.request else "unknown",
        response.request.url if response.request else "unknown",
        response.status_code,
    )
    if 200 <= response.status_code < 300:
        return

    if response.status_code == 401:
        raise UnauthorizedError()

    if response.status_code == 403:
        raise ForbiddenError(
            service="Drive",
            detail=safe_error_detail(response),
        )

    if response.is_error:
        try:
            error_body = response.json()
        except Exception:
            error_body = {"text": response.text}

        logger.error("Drive API Error [%s]: %s", response.status_code, error_body)

        raise UpstreamServiceError(
            response.status_code,
            service="Drive",
            body=error_body,
        )


class DriveClient:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def create_spreadsheet_in_folder(self, telegram_id: int, folder_id: str, file_name: str):
        url = f"{settings.CPP_SERVER_URL}/api/drive/files"

        params = {
            "telegram_id": telegram_id,
        }

        body = {
            "name": file_name,
            "mimeType": "application/vnd.google-apps.spreadsheet",
            "parents": [folder_id],
        }

        try:
            response = await self._http.post(url=url, params=params, json=body)
            _check_error(response)
            return response.json()
        except httpx.RequestError as error:
            raise ExternalServiceUnavailableError("Drive") from error


    async def upload_to_drive(
            self,
            telegram_id: int,
            file_name: str,
            content: bytes,
            mime_type: str,
            parent_folder_id: str | None = None,
    ) -> dict:

        url = f"{settings.CPP_SERVER_URL}/api/drive/upload"

        params = {"telegram_id": telegram_id}

        boundary = "foo_bar_baz_boundary"

        metadata = {
            "name": file_name,
            "mimeType": mime_type,
        }
        if parent_folder_id:
            metadata["parents"] = [parent_folder_id]

        metadata_json = json.dumps(metadata)

        body_bytes = (
                         f"--{boundary}\r\n"
                         f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
                         f"{metadata_json}\r\n"
                         f"--{boundary}\r\n"
                         f"Content-Type: {mime_type}\r\n\r\n"
                     ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")

        headers = {
            "Content-Type": f"multipart/related; boundary={boundary}"
        }

        try:
            response = await self._http.post(
                url,
                params=params,
                content=body_bytes,
                headers=headers
            )
            _check_error(response)
            result = response.json()
            if not isinstance(result, dict) or not isinstance(result.get("id"), str):
                raise InvalidUpstreamResponseError("Drive")
            return result
        except httpx.RequestError as error:
            raise ExternalServiceUnavailableError("Drive") from error

    async def download_file(
            self,
            telegram_id: int,
            file_id: str,
            *,
            export_mime_type: str | None = None,
    ) -> bytes:
        """Download file content through the authenticated server proxy.

        Google Docs editors (Slides/Docs/Sheets) cannot be fetched with
        alt=media; they must be exported to an Office/PDF format first.
        """
        if export_mime_type:
            url = f"{settings.CPP_SERVER_URL}/api/drive/files/{file_id}/export"
            params = {
                "telegram_id": telegram_id,
                "mimeType": export_mime_type,
            }
        else:
            url = f"{settings.CPP_SERVER_URL}/api/drive/files/{file_id}"
            params = {
                "telegram_id": telegram_id,
                "alt": "media",
            }

        try:
            response = await self._http.get(url, params=params)
            _check_error(response)
            return response.content
        except httpx.RequestError as error:
            raise ExternalServiceUnavailableError("Drive") from error
