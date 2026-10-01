import uuid
from datetime import datetime, timedelta, timezone

from app.classroom.client import ClassroomClient
from app.core.errors import ValidationError
from app.core.logging import logger


class ClassroomService:
    def __init__(self, client: ClassroomClient):
        self.client = client
        self._pending_courses = {}
        self._pending_announcements = {}
        self._cache_files = {}
        logger.info("ClassroomService initialized")


    def append_file_in_cache(self, pending_id: str, file_name: str, content: bytes, mime_info: str):
        self._cache_files[pending_id] = {
            "file_name": file_name,
            "content": content,
            "mime_info": mime_info
        }

    def remove_file_in_cache(self, pending_id: str, file_name: str):
        vec = self._cache_files.get(pending_id)
        if isinstance(vec, list):
            self._cache_files[pending_id] = [item for item in vec if item["file_name"] == file_name]
        else:
            self._cache_files.pop(pending_id, None)

    def hold_course_announcement(
        self,
        telegram_id: int,
        course_id: str,
        text: str,
        state: str | None,
        materials: list | None,
        telegram_attachments: list | None = None,
    ):

        pending_id = str(uuid.uuid4())[:8]
        self._pending_announcements[pending_id] = {
            "telegram_id": telegram_id,
            "course_id": course_id,
            "text": text,
            "state": state,
            "materials": materials or [],
            "telegram_attachments": telegram_attachments or [],
            "status": "pending",
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=15),
        }

        return pending_id

    def hold_course_creation(self, telegram_id: int, course_name: str, course_description: str,
                             course_section: str) -> str:
        logger.info(
            "ClassroomService.hold_course_creation called: telegram_id=%s course_name=%r course_description=%r course_section=%r",
            telegram_id,
            course_name,
            course_description,
            course_section,
        )
        pending_id = str(uuid.uuid4())[:8]
        self._pending_courses[pending_id] = {
            "telegram_id": telegram_id,
            "name": course_name,
            "description": course_description,
            "section": course_section
        }
        return pending_id

    def get_pending_course(self, pending_id: str) -> dict | None:
        return self._pending_courses.get(pending_id)

    def get_pending_announcement(self, pending_id: str) -> dict | None:
        data = self._pending_announcements.get(pending_id)
        if data and data["expires_at"] <= datetime.now(timezone.utc):
            self.remove_pending_announcement(pending_id)
            return None
        return data

    def claim_pending_announcement(self, pending_id: str, telegram_id: int) -> dict | None:
        data = self.get_pending_announcement(pending_id)
        if not data or data["telegram_id"] != telegram_id or data["status"] != "pending":
            return None
        data["status"] = "processing"
        return data

    def remove_pending_course(self, pending_id: str):
        self._pending_courses.pop(pending_id, None)

    def remove_pending_announcement(self, pending_id: str):
        self._pending_announcements.pop(pending_id, None)

    async def get_structure(self, telegram_id: int):
        logger.info("ClassroomService.get_structure called: telegram_id=%s", telegram_id)
        self._validate_telegram_id(telegram_id)
        courses = await self.client.get_course(telegram_id)
        return courses

    async def get_concrete_course(self, telegram_id: int, course_id):
        self._validate_telegram_id(telegram_id)
        course = await self.client.get_concrete_course(telegram_id, course_id)
        return course

    async def get_students(self, telegram_id: int, course_id: int):
        logger.info("ClassroomService.get_students called: telegram_id=%s course_id=%s", telegram_id, course_id)
        self._validate_telegram_id(telegram_id)
        students = await self.client.get_student_in_course(telegram_id, course_id)
        return students

    async def get_assignments(self, telegram_id: int, course_id: int):
        logger.info("ClassroomService.get_assignments called: telegram_id=%s course_id=%s", telegram_id, course_id)
        self._validate_telegram_id(telegram_id)
        assignments = await self.client.get_course_works(telegram_id, course_id)
        return assignments

    async def get_submissions_status(self, telegram_id: int, course_id: int, course_work_id: int):
        logger.info(
            "ClassroomService.get_submissions_status called: telegram_id=%s course_id=%s course_work_id=%s",
            telegram_id,
            course_id,
            course_work_id,
        )
        self._validate_telegram_id(telegram_id)
        submissions_status = await self.client.get_submissions(telegram_id, course_id, course_work_id)
        return submissions_status

    async def create_course(self, telegram_id: int, course_name: str, course_description: str, course_section: str):
        logger.info(
            "ClassroomService.create_course called: telegram_id=%s course_name=%r course_description=%r course_section=%r",
            telegram_id,
            course_name,
            course_description,
            course_section,
        )
        self._validate_telegram_id(telegram_id)

        if not isinstance(course_name, str) or not course_name.strip():
            raise ValidationError("Course name is required")
        if len(course_name) > 750:
            raise ValidationError("Course name is too long")
        if not isinstance(course_description, str):
            raise ValidationError("Course description must be a string")
        if len(course_description) > 30_000:
            raise ValidationError("Course description is too long")
        if course_section is not None and not isinstance(course_section, str):
            raise ValidationError("Course section must be a string")

        course = await self.client.create_course(
            telegram_id=telegram_id,
            course_name=course_name,
            course_description=course_description,
            course_section=course_section
        )
        return course

    async def create_announcement(
        self,
        telegram_id: int,
        course_id: str,
        text: str,
        state: str,
        materials: list,
    ):
        self._validate_telegram_id(telegram_id)

        if not isinstance(course_id, str) or not course_id.strip():
            raise ValidationError("Course ID is required")
        if not isinstance(text, str) or not text.strip():
            raise ValidationError("Text is required")
        if len(text) > 30_000:
            raise ValidationError("Text is too long")
        if not isinstance(materials, list):
            raise ValidationError("Materials must be a list")
        if state not in {"PUBLISHED", "DRAFT"}:
            raise ValidationError("State must be PUBLISHED or DRAFT")

        announcement = await self.client.create_announcement(
            telegram_id=telegram_id,
            course_id=course_id,
            text=text,
            state=state,
            materials=materials
        )

        return announcement

    async def upload_to_drive(self, telegram_id: int, file_name: str, content: bytes, mime_type: str, parent_folder_id: str | None = None):
        logger.info("ClassroomService.upload_to_drive called: telegram_id=%s", telegram_id)
        result = await self.client.upload_to_drive(
            telegram_id=telegram_id,
            file_name=file_name,
            content=content,
            mime_type=mime_type,
            parent_folder_id=parent_folder_id
        )
        return result


    @staticmethod
    def _validate_telegram_id(telegram_id: int) -> None:
        if not isinstance(telegram_id, int) or isinstance(telegram_id, bool) or telegram_id <= 0:
            raise ValidationError("A valid Telegram user ID is required")
