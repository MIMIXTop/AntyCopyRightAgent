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
        logger.info(
            "Sheets read request: sheet_id=%s range=%r url=%s params=%s",
            sheet_id,
            range,
            url,
            params,
        )

        try:
            response = await self._http.get(url, params=params)
            logger.info(
                "Sheets read response: request_url=%s status=%s body=%s",
                response.request.url,
                response.status_code,
                response.text[:500],
            )
            _check_error(response)
            return response.json()
        except httpx.RequestError as error:
            raise ExternalServiceUnavailableError("Sheets") from error

    async def post_sheet_value(self, telegram_id: int, sheet_id: str, range_name: str, values: list[list]):
        url = f"{settings.CPP_SERVER_URL}/api/sheets/{sheet_id}/values/{range_name}:append"
        params = {
            "valueInputOption": "USER_ENTERED",
            "insertDataOption": "INSERT_ROWS",
            "telegram_id": telegram_id
        }
        body = {"values": values}
        logger.info(
            "Sheets append request: sheet_id=%s range=%r url=%s params=%s rows=%s",
            sheet_id,
            range_name,
            url,
            params,
            len(values),
        )

        try:
            response = await self._http.post(
                httpx.URL(url),
                params=params,
                json=body,
            )
            logger.info(
                "Sheets append response: request_url=%s status=%s body=%s",
                response.request.url,
                response.status_code,
                response.text[:500],
            )
            _check_error(response)
            return response.json()
        except httpx.RequestError as error:
            raise ExternalServiceUnavailableError("Sheets") from error

    async def put_sheet_value(self, telegram_id: int, sheet_id: str, range_name: str, values: list[list]):
        url = f"{settings.CPP_SERVER_URL}/api/sheets/{sheet_id}/values/{range_name}"

        params = {
            "valueInputOption": "USER_ENTERED",
            "telegram_id": telegram_id
        }

        body = {"values": values}
        logger.info(
            "Sheets update request: sheet_id=%s range=%r url=%s params=%s rows=%s",
            sheet_id,
            range_name,
            url,
            params,
            len(values),
        )

        try:
            response = await self._http.put(url, params=params, json=body)
            logger.info(
                "Sheets update response: request_url=%s status=%s body=%s",
                response.request.url,
                response.status_code,
                response.text[:500],
            )
            _check_error(response)
            return response.json()
        except httpx.RequestError as error:
            raise ExternalServiceUnavailableError("Sheets") from error

    async def get_sheet_info(self, telegram_id: int, sheet_id: str):
        url = f"{settings.CPP_SERVER_URL}/api/sheets/{sheet_id}"
        params = {
            "fields": "sheets(properties(sheetId,title,index))",
            "telegram_id": telegram_id
        }

        try:
            response = await self._http.get(url, params=params)
            _check_error(response)
            return response.json()
        except httpx.RequestError as error:
            raise ExternalServiceUnavailableError("Sheets") from error

    async def create_sheet_tab(self, telegram_id: int, sheet_id: str, tab_name: str):
        url = f"{settings.CPP_SERVER_URL}/api/sheets/{sheet_id}:batchUpdate"

        params = {
            "telegram_id": telegram_id
        }

        body = {
            "requests": [
                {
                    "addSheet": {
                        "properties": {
                            "title": tab_name
                        }
                    }
                }
            ]
        }

        try:
            response = await self._http.post(url, params=params, json=body)
            _check_error(response)
            return response.json()
        except httpx.RequestError as error:
            raise ExternalServiceUnavailableError("Sheets") from error
