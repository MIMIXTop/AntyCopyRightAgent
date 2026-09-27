import httpx
import logging

from app.classroom.models import Course, CourseWork, StudentSubmission, Student, ResultRequest
from app.core.errors import (
    ExternalServiceUnavailableError,
    InvalidUpstreamResponseError,
    UpstreamServiceError, ForbiddenError, UnauthorizedError,
    safe_error_detail
)
from app.config.settings import settings

logger = logging.getLogger(__name__)


def _check_error(response: httpx.Response):
    if response.status_code == 200:
        return

    if response.status_code == 401:
        raise UnauthorizedError()

    if response.status_code == 403:
        raise ForbiddenError(
            service="Classroom",
            detail=safe_error_detail(response),
        )

    if response.is_error:
        raise UpstreamServiceError(
            response.status_code,
            service="Classroom",
            body=response.json(),
        )


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

        _check_error(res)
        return self._parse_list(res, Course, "courses", "courses")

    async def get_course_works(self, telegram_id: int, course_id: int) -> list[CourseWork]:
        url = f"{settings.CPP_SERVER_URL}/api/classroom/courses/{course_id}/courseWork"
        params = {"telegram_id": telegram_id}

        try:
            res = await self.http.get(url, params=params)
        except httpx.TimeoutException as error:
            raise ExternalServiceUnavailableError from error

        _check_error(res)
        return self._parse_list(res, CourseWork, "course works", "courseWork")

    async def get_submissions(self, telegram_id: int, course_id: int, course_work_id: int) -> list[StudentSubmission]:
        url = f"{settings.CPP_SERVER_URL}/api/classroom/courses/{course_id}/courseWork/{course_work_id}/studentSubmissions"
        params = {"telegram_id": telegram_id}

        try:
            res = await self.http.get(url, params=params)
        except httpx.TimeoutException as error:
            raise ExternalServiceUnavailableError from error

        _check_error(res)
        return self._parse_list(res, StudentSubmission, "submissions", "studentSubmissions")

    async def get_student_in_course(self, telegram_id: int, course_id: int) -> list[Student]:
        url = f"{settings.CPP_SERVER_URL}/api/classroom/courses/{course_id}/students"
        params = {"telegram_id": telegram_id}

        try:
            res = await self.http.get(url, params=params)
        except httpx.TimeoutException as error:
            raise ExternalServiceUnavailableError from error

        _check_error(res)
        return self._parse_list(res, Student, "students", "students")

    async def create_course(self, telegram_id: int, course_name: str, course_description: str = "", course_section: str | None = None) -> ResultRequest:
        url = f"{settings.CPP_SERVER_URL}/api/classroom/courses"
        params = {"telegram_id": telegram_id}

        body = {
            "name": course_name,
            "description": course_description,
            "courseState": "ACTIVE"
        }

        if course_section is not None:
            body["section"] = course_section

        try:
            res = await self.http.post(url, params=params, json=body)
        except httpx.TimeoutException as error:
            raise ExternalServiceUnavailableError from error

        _check_error(res)
        return ResultRequest(
            status=res.status_code,
            body=res.json()
        )

    @staticmethod
    def _parse_list(
        response: httpx.Response,
        model,
        resource: str,
        payload_key: str,
    ):
        try:
            body = response.json()
            if not isinstance(body, dict):
                raise TypeError("response body must be a JSON object")
            payload = body[payload_key]
            if not isinstance(payload, list):
                raise TypeError(f"{payload_key} must be a JSON array")
            return [model.model_validate(item) for item in payload]
        except (KeyError, TypeError, ValueError) as error:
            logger.error(
                "Invalid Classroom %s response: status=%s body=%s",
                resource,
                response.status_code,
                response.text[:1000],
            )
            raise InvalidUpstreamResponseError("Classroom") from error