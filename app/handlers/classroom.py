import httpx
import logging
from app.settings import settings

logger = logging.getLogger("ClassroomClient")

async def get_courses(telegram_id: int):
    url = f"{settings.CPP_SERVER_URL}/api/classroom/courses"
    params = {"telegram_id": telegram_id}

    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(url, params=params)

            if res.status_code == 401:
                return {"status": "unauthorized"}

            res.raise_for_status()

            return res.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP ошибка от C++ сервера: {e.response.text}")
            return {"error": "Ошибка сервера", "details": e.response.text}
        except Exception as e:
            logger.error(f"Не удалось подключиться к C++ серверу: {e}")
            return {"error": "Сервер недоступен"}
