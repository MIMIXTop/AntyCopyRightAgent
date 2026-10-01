import pytest

from app.classroom.service import ClassroomService
from app.core.errors import ValidationError


class FakeClassroomClient:
    async def create_course(self, telegram_id, course_name, course_description, course_section):
        return "fake_course_object"


@pytest.mark.asyncio
async def test_service_validates_telegram_id():
    fake_client = FakeClassroomClient()
    service = ClassroomService(client=fake_client)

    with pytest.raises(ValidationError) as exc_inf:
        await service.create_course(
            -1,
            "fake_course_description",
            "fake_course_section",
            "fake_section"
        )

    assert "A valid Telegram user ID is required" in str(exc_inf.value)


@pytest.mark.asyncio
async def test_service_validates_name_length():
    fake_client = FakeClassroomClient()
    service = ClassroomService(client=fake_client)

    too_long_name = "A" * 800

    with pytest.raises(ValidationError) as exc_info:
        await service.create_course(
            telegram_id=42,
            course_name=too_long_name,
            course_description="",
            course_section=""
        )

    assert "Course name is too long" in str(exc_info.value)