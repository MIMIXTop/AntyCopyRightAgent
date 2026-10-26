import httpx
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from app.api.classroom.models import Course, CourseWork, StudentSubmission, Student, ResultRequest, Announcement, \
    CourseTopic, CourseMaterial
from app.api.drive.client import DriveClient
from app.core.errors import (
    ExternalServiceUnavailableError,
    InvalidUpstreamResponseError,
    UpstreamServiceError, ForbiddenError, UnauthorizedError,
    safe_error_detail, ValidationError
)
from app.config.settings import settings

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


class ClassroomClient:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http
        logger.info("ClassroomClient initialized")

    async def upload_to_drive(
        self,
        telegram_id: int,
        file_name: str,
        content: bytes,
        mime_type: str,
        parent_folder_id: str | None = None,
    ) -> dict:
        """Compatibility wrapper; Drive transport lives in DriveClient."""
        return await DriveClient(self.http).upload_to_drive(
            telegram_id=telegram_id,
            file_name=file_name,
            content=content,
            mime_type=mime_type,
            parent_folder_id=parent_folder_id,
        )

    async def get_concrete_course(self, telegram_id: int, course_id: int) -> Course:
        logger.info("ClassroomClient.get_concrete_course called: telegram_id=%s course_id=%s", telegram_id, course_id)
        url = f"{settings.CPP_SERVER_URL}/api/classroom/courses/{course_id}"
        params = {"telegram_id": telegram_id}

        try:
            res = await self.http.get(url, params=params)
        except httpx.TimeoutException as error:
            raise ExternalServiceUnavailableError from error

        _check_error(res)
        return Course.model_validate(res.json())

    async def get_course(self, telegram_id: int) -> list[Course]:
        logger.info("ClassroomClient.get_course called: telegram_id=%s", telegram_id)
        url = f"{settings.CPP_SERVER_URL}/api/classroom/courses"
        params = {"telegram_id": telegram_id}

        try:
            res = await self.http.get(url, params=params)

        except httpx.TimeoutException as error:
            raise ExternalServiceUnavailableError from error

        _check_error(res)
        return self._parse_list(res, Course, "courses", "courses", empty_body_is_empty=True)

    async def get_course_works(
            self,
            telegram_id: int,
            course_id: int
    ) -> list[CourseWork]:
        logger.info("ClassroomClient.get_course_works called: telegram_id=%s course_id=%s", telegram_id, course_id)
        url = f"{settings.CPP_SERVER_URL}/api/classroom/courses/{course_id}/courseWork"
        params = {"telegram_id": telegram_id}

        try:
            res = await self.http.get(url, params=params)
        except httpx.TimeoutException as error:
            raise ExternalServiceUnavailableError from error

        _check_error(res)
        return self._parse_list(
            res,
            CourseWork,
            "course works",
            "courseWork",
            empty_body_is_empty=True,
        )

    async def get_submissions(
            self,
            telegram_id: int,
            course_id: int,
            course_work_id: int
    ) -> list[StudentSubmission]:
        logger.info(
            "ClassroomClient.get_submissions called: telegram_id=%s course_id=%s course_work_id=%s",
            telegram_id,
            course_id,
            course_work_id,
        )
        url = f"{settings.CPP_SERVER_URL}/api/classroom/courses/{course_id}/courseWork/{course_work_id}/studentSubmissions"
        params = {"telegram_id": telegram_id}

        try:
            res = await self.http.get(url, params=params)
        except httpx.TimeoutException as error:
            raise ExternalServiceUnavailableError from error

        _check_error(res)
        return self._parse_list(
            res,
            StudentSubmission,
            "submissions",
            "studentSubmissions",
            empty_body_is_empty=True,
        )

    async def get_student_in_course(
            self,
            telegram_id: int,
            course_id: int
    ) -> list[Student]:
        logger.info("ClassroomClient.get_student_in_course called: telegram_id=%s course_id=%s", telegram_id, course_id)
        url = f"{settings.CPP_SERVER_URL}/api/classroom/courses/{course_id}/students"
        params = {"telegram_id": telegram_id}

        try:
            res = await self.http.get(url, params=params)
        except httpx.TimeoutException as error:
            raise ExternalServiceUnavailableError from error

        _check_error(res)
        return self._parse_list(res, Student, "students", "students", empty_body_is_empty=True)

    async def create_course(
            self,
            telegram_id: int,
            course_name: str,
            course_description: str = "",
            course_section: str | None = None
    ) -> ResultRequest:
        logger.info(
            "ClassroomClient.create_course called: telegram_id=%s course_name=%r course_description=%r course_section=%r",
            telegram_id,
            course_name,
            course_description,
            course_section,
        )
        url = f"{settings.CPP_SERVER_URL}/api/classroom/courses"
        params = {"telegram_id": telegram_id}

        body = {
            "name": course_name,
            "ownerId": "me",
        }

        if course_section is not None:
            body["section"] = course_section

        if course_description != "":
            body["description"] = course_description

        try:
            res = await self.http.post(url, params=params, json=body)
            logger.info("Classroom create course POST sent: params=%s body=%s", params, body)
            _check_error(res)

            course_data = res.json()
            course_id = course_data.get("id")

            if course_id:
                patch_url = f"{settings.CPP_SERVER_URL}/api/classroom/courses/{course_id}"
                patch_params = {
                    "telegram_id": telegram_id,
                    "updateMask": "courseState"
                }
                patch_body = {
                    "courseState": "ACTIVE"
                }
                try:

                    patch_res = await self.http.patch(patch_url, params=patch_params, json=patch_body)
                    _check_error(patch_res)

                    course_data["courseState"] = "ACTIVE"
                    logger.info("Курс успешно активирован автоматически (Workspace Teacher).")
                except Exception as e:
                    if "CourseStateDenied" in str(e):
                        logger.warning("Личный аккаунт: авто-активация недоступна. Курс создан как PROVISIONED.")
                        course_data["courseState"] = "PROVISIONED"
                    else:
                        raise e

            return ResultRequest(
                status=res.status_code,
                body=course_data
            )
        except httpx.RequestError as error:
            logger.error("Failed to connect to C++ server while creating course: %s", error)
            raise ExternalServiceUnavailableError("Classroom") from error


    async def create_assigment(
            self,
            telegram_id: int,
            course_id: str,
            title: str,
            description: str = "",
            max_points: int | None = 100,
            due_date: str | None = None,
            due_time: str | None = None,
            materials: list[dict] | None = None,
            topic_id: str | None = None,
            state: str = "PUBLISHED"
    ) -> ResultRequest:

        url = f"{settings.CPP_SERVER_URL}/api/classroom/courses/{course_id}/courseWork"
        params = {"telegram_id": telegram_id}

        body = {
            "title": title,
            "workType": "ASSIGNMENT",
            "state": state,
        }

        if description:
            body["description"] = description

        if max_points is not None:
            body["maxPoints"] = max_points

        if due_date is not None and due_date.strip():
            try:
                time_str = due_time if (due_time and due_time.strip()) else "23:59"

                dt_str = f"{due_date} {time_str}"
                local_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")

                local_tz = ZoneInfo("Europe/Moscow")
                local_dt = local_dt.replace(tzinfo=local_tz)

                utc_dt = local_dt.astimezone(ZoneInfo("UTC"))

                body["dueDate"] = {"year": utc_dt.year, "month": utc_dt.month, "day": utc_dt.day}
                body["dueTime"] = {"hours": utc_dt.hour, "minutes": utc_dt.minute}

            except ValueError:
                raise ValidationError("Неверный формат даты или времени (ожидается YYYY-MM-DD и HH:MM)")
        if materials:
            body["materials"] = materials
        if topic_id:
            body["topicId"] = topic_id

        try:
            response = await self.http.post(url, params=params, json=body)
            _check_error(response)
            return ResultRequest(
                status=response.status_code,
                body=response.json()
            )
        except httpx.TimeoutException as error:
            raise ExternalServiceUnavailableError from error

    async def create_announcement(
            self,
            telegram_id: int,
            course_id: str,
            text: str, state: str | None = None,
            materials: list[dict] | None = None
    ) -> ResultRequest:
        logger.info(
            "ClassroomClient.create_announcement called: telegram_id=%s course_id=%s state=%s materials_count=%s",
            telegram_id,
            course_id,
            state,
            len(materials or []),
        )
        url = f"{settings.CPP_SERVER_URL}/api/classroom/courses/{course_id}/announcements"
        params = {"telegram_id": telegram_id}

        body = {
            "text": text,
        }

        if state is not None:
            body["state"] = state

        if materials:
            body["materials"] = materials

        try:
            response = await self.http.post(url, params=params, json=body)
            logger.info(
                "Classroom announcement POST sent: course_id=%s materials_count=%s",
                course_id,
                len(materials or []),
            )
            _check_error(response)
            return ResultRequest(
                status=response.status_code,
                body=response.json()
            )
        except httpx.TimeoutException as error:
            raise ExternalServiceUnavailableError from error

    async def patch_course(
            self,
            telegram_id: int,
            course_id: str,
            course_name: str | None = None,
            course_description: str | None = None,
            course_section: str | None = None,
            course_state: str | None = None,
    ) -> Course:
        url = f"{settings.CPP_SERVER_URL}/api/classroom/courses/{course_id}"
        body = {}
        mask_fields = []

        if course_name is not None and course_name.strip():
            mask_fields.append("name")
            body["name"] = course_name

        if course_description is not None:
            mask_fields.append("description")
            body["description"] = course_description

        if course_section is not None:
            mask_fields.append("section")
            body["section"] = course_section

        if course_state is not None:
            mask_fields.append("courseState")
            body["courseState"] = course_state

        if not body:
            raise ValidationError("Не указано ни одного поля для обновления курса")

        params = {
            "telegram_id": telegram_id,
            "updateMask": ",".join(mask_fields)
        }

        try:
            response = await self.http.patch(url, params=params, json=body)
            _check_error(response)
            return Course.model_validate(response.json())
        except httpx.RequestError as error:
            logger.error("Failed to connect to C++ server: %s", error)
            raise ExternalServiceUnavailableError("Classroom") from error

    async def patch_announcement(
            self,
            telegram_id: int,
            course_id: str,
            announcement_id: str,
            text: str | None = None,
            state: str | None = None,
    ) -> Announcement:
        url = f"{settings.CPP_SERVER_URL}/api/classroom/courses/{course_id}/announcements/{announcement_id}"
        body = {}
        mask_fields = []

        if text is not None and text.strip():
            mask_fields.append("text")
            body["text"] = text

        if state is not None and state.strip():
            mask_fields.append("state")
            body["state"] = state

        if not body:
            raise ValidationError("Не указано ни одного поля для обновления анонса")

        params = {
            "telegram_id": telegram_id,
            "updateMask": ",".join(mask_fields)
        }

        try:
            response = await self.http.patch(url, params=params, json=body)
            _check_error(response)
            return Announcement.model_validate(response.json())
        except httpx.RequestError as error:
            logger.error("Failed to connect to C++ server: %s", error)
            raise ExternalServiceUnavailableError("Classroom") from error

    async def get_topics_in_course(self, telegram_id: int, course_id: str):
        url = f"{settings.CPP_SERVER_URL}/api/classroom/courses/{course_id}/topics"
        params = {
            "telegram_id": telegram_id
        }

        try:
            res = await self.http.get(url, params=params)
            _check_error(res)
            return self._parse_list(
                res,
                CourseTopic,
                "topics",
                ("topic", "topics"),
                empty_body_is_empty=True,
            )
        except httpx.RequestError as error:
            logger.error("Failed to connect to C++ server: %s", error)
            raise ExternalServiceUnavailableError("Classroom") from error

    async def create_topic_in_course(self, telegram_id: int, topic_name: str, course_id: str):
        url = f"{settings.CPP_SERVER_URL}/api/classroom/courses/{course_id}/topics"
        params = {
            "telegram_id": telegram_id
        }
        body = {
            "name": topic_name
        }
        try:
            response = await self.http.post(url, params=params, json=body)
            _check_error(response)
            return ResultRequest(
                status=response.status_code,
                body=response.json()
            )
        except httpx.RequestError as error:
            logger.error("Failed to connect to C++ server: %s", error)
            raise ExternalServiceUnavailableError("Classroom") from error

    async def update_topic_in_course(self, telegram_id: int, topic_name: str, topic_id: str, course_id: str):
        url = f"{settings.CPP_SERVER_URL}/api/classroom/courses/{course_id}/topics/{topic_id}"
        params = {
            "telegram_id": telegram_id,
            "updateMask": "name"
        }

        body = {
            "name": topic_name
        }

        try:
            response = await self.http.patch(url, params=params, json=body)
            _check_error(response)
            return ResultRequest(
                status=response.status_code,
                body=response.json()
            )
        except httpx.RequestError as error:
            logger.error("Failed to connect to C++ server: %s", error)
            raise ExternalServiceUnavailableError("Classroom") from error


    async def patch_assignments(
            self,
            telegram_id: int,
            course_id: str,
            course_work_id: str,
            title: str | None = None,
            description: str | None = None,
            max_points: int | None = None,
            due_date: str | None = None,
            due_time: str | None = None,
            state: str | None = None,
            topic_id: str | None = None,
    ) -> CourseWork:
        url = f"{settings.CPP_SERVER_URL}/api/classroom/courses/{course_id}/courseWork/{course_work_id}"
        body = {}
        mask_fields = []

        if title is not None and title.strip():
            mask_fields.append("title")
            body["title"] = title

        if description is not None:
            mask_fields.append("description")
            body["description"] = description

        if max_points is not None:
            mask_fields.append("maxPoints")
            body["maxPoints"] = max_points

        if due_date is not None and due_date.strip():
            try:
                time_str = due_time if (due_time and due_time.strip()) else "23:59"

                dt_str = f"{due_date} {time_str}"
                local_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")

                local_tz = ZoneInfo("Europe/Minsk")
                local_dt = local_dt.replace(tzinfo=local_tz)

                utc_dt = local_dt.astimezone(ZoneInfo("UTC"))

                if 'mask_fields' in locals():
                    mask_fields.append("dueDate")
                    mask_fields.append("dueTime")

                body["dueDate"] = {"year": utc_dt.year, "month": utc_dt.month, "day": utc_dt.day}
                body["dueTime"] = {"hours": utc_dt.hour, "minutes": utc_dt.minute}

            except ValueError:
                raise ValidationError("Неверный формат даты или времени (ожидается YYYY-MM-DD и HH:MM)")
        if state is not None and state.strip():
            mask_fields.append("state")
            body["state"] = state
        if topic_id is not None and topic_id.strip():
            mask_fields.append("topicId")
            body["topicId"] = topic_id

        if not body:
            raise ValidationError("Не указано ни одного поля для обновления задания")

        params = {
            "telegram_id": telegram_id,
            "updateMask": ",".join(mask_fields)
        }

        try:
            response = await self.http.patch(url, params=params, json=body)
            _check_error(response)
            return CourseWork.model_validate(response.json())
        except httpx.RequestError as error:
            logger.error("Failed to connect to C++ server: %s", error)
            raise ExternalServiceUnavailableError("Classroom") from error


    async def get_announcements(self, telegram_id: int, course_id: str) -> list[Announcement]:
        url = f"{settings.CPP_SERVER_URL}/api/classroom/courses/{course_id}/announcements"
        params = {"telegram_id": telegram_id}

        try:
            res = await self.http.get(url, params=params)
        except httpx.RequestError as error:
            logger.error("Failed to connect to C++ server: %s", error)
            raise ExternalServiceUnavailableError("Classroom") from error

        _check_error(res)
        return self._parse_list(
            res,
            Announcement,
            "announcements",
            "announcements",
            empty_body_is_empty=True,
        )


    async def get_course_materials(self, telegram_id: int, course_id):
        url = f"{settings.CPP_SERVER_URL}/api/classroom/courses/{course_id}/courseWorkMaterials"
        params = {"telegram_id": telegram_id}

        try:
            response = await self.http.get(url, params=params)
            _check_error(response)
            return self._parse_list(
                response,
                CourseMaterial,
                "courseMaterial",
                ("courseWorkMaterial", "courseMaterial", "courseWorkMaterials"),
                empty_body_is_empty=True,
            )
        except httpx.RequestError as error:
            logger.error("Failed to connect to C++ server: %s", error)
            raise ExternalServiceUnavailableError("Classroom") from error

    async def create_course_material(self, telegram_id: int, course_id: str, materials: list[dict], title: str, description: str = None, topic_id: str = None):

        url = f"{settings.CPP_SERVER_URL}/api/classroom/courses/{course_id}/courseWorkMaterials"
        params = {"telegram_id": telegram_id}
        body = {
            "materials": materials,
            "title": title,
        }

        if description:
            body["description"] = description
        if topic_id:
            body["topicId"] = topic_id

        try:
            response = await self.http.post(url, params=params, json=body)
            _check_error(response)
        except httpx.RequestError as error:
            logger.error("Failed to connect to C++ server: %s", error)
            raise ExternalServiceUnavailableError("Classroom") from error

    async def update_course_material(
            self,
            telegram_id: int,
            course_id: str,
            material_id: str,
            title: str | None = None,
            materials: list[dict] | None = None,
            description: str | None = None,
            topic_id: str | None = None,
    ):
        url = f"{settings.CPP_SERVER_URL}/api/classroom/courses/{course_id}/courseWorkMaterials/{material_id}"
        body = {}
        mask_fields = []

        if title is not None and title.strip():
            mask_fields.append("title")
            body["title"] = title

        if description is not None and description.strip():
            mask_fields.append("description")
            body["description"] = description

        if topic_id is not None and topic_id.strip():
            mask_fields.append("topicId")
            body["topicId"] = topic_id

        if materials is not None:
            mask_fields.append("materials")
            body["materials"] = materials

        if not body:
            raise ValidationError("Не указано ни одного поля для обновления материала")

        params = {
            "telegram_id": telegram_id,
            "updateMask": ",".join(mask_fields)
        }

        try:
            response = await self.http.patch(url, params=params, json=body)
            _check_error(response)
            return CourseMaterial.model_validate(response.json())
        except httpx.RequestError as error:
            logger.error("Failed to connect to C++ server: %s", error)
            raise ExternalServiceUnavailableError("Classroom") from error


    @staticmethod
    def _parse_list(
            response: httpx.Response,
            model,
            resource: str,
            payload_key: str | tuple[str, ...],
            empty_body_is_empty: bool = False,
    ):
        try:
            body = response.json()
            if not isinstance(body, dict):
                raise TypeError("response body must be a JSON object")
            if empty_body_is_empty and not body:
                return []
            keys = (payload_key,) if isinstance(payload_key, str) else payload_key
            payload = next((body[key] for key in keys if key in body), None)
            if payload is None:
                raise KeyError(keys[0])
            if not isinstance(payload, list):
                raise TypeError(f"{keys[0]} must be a JSON array")
            return [model.model_validate(item) for item in payload]
        except (KeyError, TypeError, ValueError) as error:
            logger.error(
                "Invalid Classroom %s response: status=%s body=%s",
                resource,
                response.status_code,
                response.text[:1000],
            )
            raise InvalidUpstreamResponseError("Classroom") from error
