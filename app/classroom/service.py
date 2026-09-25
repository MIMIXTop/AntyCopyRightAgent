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

    @staticmethod
    def _validate_telegram_id(telegram_id: int) -> None:
        if not isinstance(telegram_id, int) or isinstance(telegram_id, bool) or telegram_id <= 0:
            raise ValidationError("A valid Telegram user ID is required")