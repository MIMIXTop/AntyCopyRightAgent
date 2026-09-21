import httpx

from app.classroom.models import Course, CourseWork, StudentSubmission, Student
from app.core.errors import (
    ExternalServiceUnavailableError,
    InvalidUpstreamResponseError,
    UpstreamServiceError,
)
from app.config.settings import settings


class ClassroomClient:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http

    async def get_course(self, telegram_id: int) -> list[Course]:
        url = f"{settings.CPP_SERVER_URL}/api/classroom/courses"
        params = {"telegram_id": telegram_id}

        try:
            res = await self.http.get(url, params=params)
        except httpx.TimeoutException as error:
            raise ExternalServiceUnavailableError from error
        if res.is_error:
            raise UpstreamServiceError(res.status_code)
        return self._parse_list(res, Course)

    async def get_course_works(self, telegram_id: int, course_id: int) -> list[CourseWork]:
        url = f"{settings.CPP_SERVER_URL}/api/classroom/courses/{course_id}/courseWork"
        params = {"telegram_id": telegram_id}

        try:
            res = await self.http.get(url, params=params)
        except httpx.TimeoutException as error:
            raise ExternalServiceUnavailableError from error
        if res.is_error:
            raise UpstreamServiceError(res.status_code)
        return self._parse_list(res, CourseWork)

    async def get_submissions(self, telegram_id: int, course_id: int, course_work_id: int) -> list[StudentSubmission]:
        url = f"{settings.CPP_SERVER_URL}/api/classroom/courses/{course_id}/courseWork/{course_work_id}/studentSubmissions"
        params = {"telegram_id": telegram_id}

        try:
            res = await self.http.get(url, params=params)
        except httpx.TimeoutException as error:
            raise ExternalServiceUnavailableError from error
        if res.is_error:
            raise UpstreamServiceError(res.status_code)
        return self._parse_list(res, StudentSubmission)

    async def get_student_in_course(self, telegram_id: int, course_id: int) -> list[Student]:
        url = f"{settings.CPP_SERVER_URL}/api/classroom/courses/{course_id}/students"
        params = {"telegram_id": telegram_id}

        try:
            res = await self.http.get(url, params=params)
        except httpx.TimeoutException as error:
            raise ExternalServiceUnavailableError from error
        if res.is_error:
            raise UpstreamServiceError(res.status_code)
        return self._parse_list(res, Student)

    @staticmethod
    def _parse_list(response: httpx.Response, model):
        try:
            payload = response.json()
            return [model.model_validate(item) for item in payload]
        except (TypeError, ValueError) as error:
            raise InvalidUpstreamResponseError from error