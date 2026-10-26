import json
import logging
import httpx

from app.config.settings import settings
from app.core.errors import UnauthorizedError, ForbiddenError, safe_error_detail, UpstreamServiceError, \
    ExternalServiceUnavailableError, InvalidUpstreamResponseError

logger = logging.getLogger(__name__)

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
