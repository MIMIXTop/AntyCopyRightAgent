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
            logger.info(f"HTTP ошибка от C++ сервера: {e.response.text}")
            return {"error": "Ошибка сервера", "details": e.response.text}
        except Exception as e:
            logger.info(f"Не удалось подключиться к C++ серверу: {e}")
            return {"error": "Сервер недоступен"}

async def get_assignments( telegram_id: int, course_id: int):
    url = f"{settings.CPP_SERVER_URL}/api/classroom/courses/{course_id}/courseWork"
    params = {"telegram_id": telegram_id}

    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(url, params=params)

            if res.status_code == 401:
                return {"status": "unauthorized"}

            res.raise_for_status()

            return res.json()
        except httpx.HTTPStatusError as e:
            logger.info(f"HTTP ошибка от C++ сервера: {e.response.text}")
            return {"error": "Ошибка сервера", "details": e.response.text}
        except Exception as e:
            logger.info(f"Не удалось подключиться к C++ серверу: {e}")
            return {"error": "Сервер недоступен"}
    pass