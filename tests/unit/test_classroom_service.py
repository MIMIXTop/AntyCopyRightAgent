import pytest
from datetime import datetime, timedelta, timezone

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


def test_pending_announcement_has_list_and_expires():
    service = ClassroomService(client=None)
    pending_id = service.hold_course_announcement(
        telegram_id=42,
        course_id="course-1",
        text="hello",
        state="PUBLISHED",
        materials=None,
    )

    pending = service.get_pending_announcement(pending_id)
    assert pending["materials"] == []
    assert pending["status"] == "pending"
    assert pending["expires_at"] > datetime.now(timezone.utc)


def test_pending_announcement_checks_owner_and_is_idempotent():
    service = ClassroomService(client=None)
    pending_id = service.hold_course_announcement(42, "course-1", "hello", "PUBLISHED", [])

    assert service.claim_pending_announcement(pending_id, 99) is None
    assert service.claim_pending_announcement(pending_id, 42) is not None
    assert service.claim_pending_announcement(pending_id, 42) is None


@pytest.mark.asyncio
async def test_service_rejects_invalid_announcement_values():
    service = ClassroomService(client=None)

    with pytest.raises(ValidationError, match="Course ID"):
        await service.create_announcement(42, "", "hello", "PUBLISHED", [])
    with pytest.raises(ValidationError, match="State"):
        await service.create_announcement(42, "course", "hello", "INVALID", [])
    with pytest.raises(ValidationError, match="Materials"):
        await service.create_announcement(42, "course", "hello", "PUBLISHED", {})