from app.classroom.client import ClassroomClient
from app.core.errors import ValidationError


class ClassroomService:
    def __init__(self, client:  ClassroomClient):
        self.client = client

    async def get_structure(self, telegram_id: int):
        self._validate_telegram_id(telegram_id)
        courses = await self.client.get_course(telegram_id)
        return courses

    async def get_students(self, telegram_id: int, course_id: int):
        self._validate_telegram_id(telegram_id)
        students = await self.client.get_student_in_course(telegram_id,course_id)
        return students

    async def get_assignments(self, telegram_id: int, course_id: int):
        self._validate_telegram_id(telegram_id)
        assignments = await self.client.get_course_works(telegram_id, course_id)
        return assignments

    async def get_submissions_status(self, telegram_id: int, course_id: int, course_work_id: int):
        self._validate_telegram_id(telegram_id)
        submissions_status = await self.client.get_submissions(telegram_id, course_id, course_work_id)
        return submissions_status

    async def create_course(self, telegram_id: int, course_name: str, course_description: str, course_section: str):
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

    @staticmethod
    def _validate_telegram_id(telegram_id: int) -> None:
        if not isinstance(telegram_id, int) or isinstance(telegram_id, bool) or telegram_id <= 0:
            raise ValidationError("A valid Telegram user ID is required")