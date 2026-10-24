import httpx

import logging
from app.config.settings import settings
from app.core.errors import UnauthorizedError, ForbiddenError, safe_error_detail, UpstreamServiceError, \
    ExternalServiceUnavailableError

logger = logging.getLogger(__name__)


def _check_error(response: httpx.Response):
    logger.info(
        "Classroom HTTP response: method=%s url=%s status=%s",
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
            service="Classroom",
            detail=safe_error_detail(response),
        )

    if response.is_error:
        try:
            error_body = response.json()
        except Exception:
            error_body = {"text": response.text}

        logger.error(f"Classroom API Error [{response.status_code}]: {error_body}")

        raise UpstreamServiceError(
            response.status_code,
            service="Classroom",
            body=error_body,
        )


class SheetsClient:
    def __init__(self, http: httpx.AsyncClient):
        self._http = http

    async def get_sheet_value(self, telegram_id: int, sheet_id: str, range: str):
        url = f"{settings.CPP_SERVER_URL}/api/sheets/{sheet_id}/values/{range}"
        params = {"telegram_id": telegram_id}

        try:
            response = await self._http.get(url, params=params)
            _check_error(response)
            return response.json()
        except UpstreamServiceError as error:
            raise ExternalServiceUnavailableError from error

    async def post_sheet_value(self, telegram_id: int, sheet_id: str, range_name: str, values: list[list]):
        url = f"{settings.CPP_SERVER_URL}/api/sheets/{sheet_id}/values/{range_name}:append"
        params = {
            "valueInputOption": "USER_ENTERED",
            "insertDataOption": "INSERT_ROWS",
            "telegram_id": telegram_id
        }
        body = {"values": values}

        try:
            response = await self._http.put(url, params=params, json=body)
            _check_error(response)
            return response.json()
        except UpstreamServiceError as error:
            raise ExternalServiceUnavailableError from error

    async def put_sheet_value(self, telegram_id: int, sheet_id: str, range_name: str, values: list[list]):
        url = f"{settings.CPP_SERVER_URL}/api/sheets/{sheet_id}/values/{range_name}"

        params = {
            "valueInputOption": "USER_ENTERED",
            "telegram_id": telegram_id
        }

        body = {"values": values}

        try:
            response = await self._http.put(url, params=params, json=body)
            _check_error(response)
            return response.json()
        except UpstreamServiceError as error:
            raise ExternalServiceUnavailableError from error

    async def delete_sheet_value(self, telegram_id: int, sheet_id: str):
