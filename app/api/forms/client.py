import logging

import httpx

from app.api.forms.models import Form, FormResponsesList, build_publish_request
from app.config.settings import settings
from app.core.errors import (
    ExternalServiceUnavailableError,
    ForbiddenError,
    InvalidUpstreamResponseError,
    UnauthorizedError,
    UpstreamServiceError,
    safe_error_detail,
)

logger = logging.getLogger(__name__)

# The proxy in front of Google Forms occasionally takes >15s to create a form
# (cold start, token refresh), so Forms requests get a longer budget than the
# generic HTTP client timeout.
_REQUEST_TIMEOUT = 60.0


def _check_error(response: httpx.Response):
    logger.info(
        "Forms HTTP response: method=%s url=%s status=%s",
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
            service="Forms",
            detail=safe_error_detail(response),
        )

    if response.is_error:
        try:
            error_body = response.json()
        except Exception:
            error_body = {"text": response.text}

        logger.error("Forms API Error [%s]: %s", response.status_code, error_body)

        raise UpstreamServiceError(
            response.status_code,
            service="Forms",
            body=error_body,
        )


def _json_or_empty(response: httpx.Response) -> dict:
    """Parse a JSON object body; batchUpdate/publish may return an empty body."""
    if not response.text.strip():
        return {}
    try:
        body = response.json()
    except ValueError as error:
        raise InvalidUpstreamResponseError("Forms") from error
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise InvalidUpstreamResponseError("Forms")
    return body


class FormsClient:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http
        logger.info("FormsClient initialized")

    @staticmethod
    def _base_url() -> str:
        return f"{settings.CPP_SERVER_URL}/api/forms/v1/forms"

    async def create_form(
            self,
            telegram_id: int,
            title: str,
            document_title: str = "",
    ) -> Form:
        """Create an empty form.

        Google only copies ``title`` and ``documentTitle`` from the request;
        every other field (including the description) is rejected with
        ``INVALID_ARGUMENT``. The description is applied afterwards with an
        ``updateFormInfo`` batchUpdate request.
        """
        logger.info(
            "FormsClient.create_form called: telegram_id=%s title=%r",
            telegram_id,
            title,
        )
        info: dict = {"title": title}
        if document_title:
            info["documentTitle"] = document_title

        try:
            response = await self._http.post(
                self._base_url(),
                params={"telegram_id": telegram_id},
                json={"info": info},
                timeout=_REQUEST_TIMEOUT,
            )
            _check_error(response)
            return self._parse_form(response)
        except httpx.RequestError as error:
            raise ExternalServiceUnavailableError("Forms") from error

    async def get_form(self, telegram_id: int, form_id: str) -> Form:
        logger.info(
            "FormsClient.get_form called: telegram_id=%s form_id=%s",
            telegram_id,
            form_id,
        )
        try:
            response = await self._http.get(
                f"{self._base_url()}/{form_id}",
                params={"telegram_id": telegram_id},
                timeout=_REQUEST_TIMEOUT,
            )
            _check_error(response)
            return self._parse_form(response)
        except httpx.RequestError as error:
            raise ExternalServiceUnavailableError("Forms") from error

    async def batch_update(
            self,
            telegram_id: int,
            form_id: str,
            requests: list[dict],
    ) -> dict:
        logger.info(
            "FormsClient.batch_update called: telegram_id=%s form_id=%s requests=%s",
            telegram_id,
            form_id,
            len(requests),
        )
        try:
            response = await self._http.post(
                f"{self._base_url()}/{form_id}:batchUpdate",
                params={"telegram_id": telegram_id},
                json={"requests": requests},
                timeout=_REQUEST_TIMEOUT,
            )
            _check_error(response)
            return _json_or_empty(response)
        except httpx.RequestError as error:
            raise ExternalServiceUnavailableError("Forms") from error

    async def publish(
            self,
            telegram_id: int,
            form_id: str,
            *,
            is_published: bool = True,
            is_accepting_responses: bool = True,
    ) -> dict:
        logger.info(
            "FormsClient.publish called: telegram_id=%s form_id=%s published=%s accepting=%s",
            telegram_id,
            form_id,
            is_published,
            is_accepting_responses,
        )
        try:
            response = await self._http.post(
                f"{self._base_url()}/{form_id}:setPublishSettings",
                params={"telegram_id": telegram_id},
                json=build_publish_request(
                    is_published=is_published,
                    is_accepting_responses=is_accepting_responses,
                ),
                timeout=_REQUEST_TIMEOUT,
            )
            _check_error(response)
            return _json_or_empty(response)
        except httpx.RequestError as error:
            raise ExternalServiceUnavailableError("Forms") from error

    async def get_responses(self, telegram_id: int, form_id: str) -> FormResponsesList:
        logger.info(
            "FormsClient.get_responses called: telegram_id=%s form_id=%s",
            telegram_id,
            form_id,
        )
        try:
            response = await self._http.get(
                f"{self._base_url()}/{form_id}/responses",
                params={"telegram_id": telegram_id},
                timeout=_REQUEST_TIMEOUT,
            )
            _check_error(response)
            try:
                return FormResponsesList.model_validate(response.json())
            except ValueError as error:
                raise InvalidUpstreamResponseError("Forms") from error
        except httpx.RequestError as error:
            raise ExternalServiceUnavailableError("Forms") from error

    @staticmethod
    def _parse_form(response: httpx.Response) -> Form:
        try:
            return Form.model_validate(response.json())
        except ValueError as error:
            raise InvalidUpstreamResponseError("Forms") from error
