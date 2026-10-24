import httpx

from app.core.errors import (
    ExternalServiceUnavailableError,
    InvalidUpstreamResponseError,
    UpstreamServiceError,
)
from app.core.logging import logger
from app.api.analysis.models import FileList
from app.config.settings import settings

class AnalysisClient:

    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http
        logger.info("ClassroomClient initialized")


    async def get_analysis(self, telegram_id: int, files: FileList) -> dict:
        url = f"{settings.CPP_SERVER_URL}/api/analyze"

        params = {
            "telegram_id": telegram_id,
        }

        try:
            response = await self.http.post(
                url,
                json=files.model_dump(mode="json"),
                params=params,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as error:
            raise ExternalServiceUnavailableError("Analysis") from error
        except httpx.HTTPStatusError as error:
            raise UpstreamServiceError(
                status_code=error.response.status_code,
                service="Analysis",
                body=error.response.text[:1000],
            ) from error
        except httpx.RequestError as error:
            raise ExternalServiceUnavailableError("Analysis") from error
        except (TypeError, ValueError) as error:
            logger.error("Invalid analysis response: %s", error)
            raise InvalidUpstreamResponseError("Analysis") from error

        if not isinstance(payload, dict):
            raise InvalidUpstreamResponseError("Analysis")
        return payload
