import httpx

from app.core.errors import ExternalServiceUnavailableError
from app.core.logging import logger
from app.analysis.models import FileList
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

        json_file = files.model_dump_json()

        try:
            res = await self.http.post(url, json=json_file, params=params)
        except httpx.HTTPStatusError as error:
            raise ExternalServiceUnavailableError from error

