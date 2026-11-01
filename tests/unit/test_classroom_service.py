import pytest
from datetime import datetime, timezone

from app.api.classroom.models import CourseMaterial
from app.api.classroom.service import ClassroomService
from app.core.errors import UpstreamServiceError, ValidationError


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


def make_material(material_id: str, title: str = "Лекции") -> CourseMaterial:
    return CourseMaterial(
        courseId="course-1",
        id=material_id,
        title=title,
        description="old description",
        topicId="topic-1",
    )


class RecreateRejectingClient:
    """Simulates Google rejecting a materials update on a PUBLISHED material."""

    def __init__(self, status_code: int = 400):
        self.status_code = status_code
        self.created = None
        self.deleted = None

    async def update_course_material(self, **kwargs):
        raise UpstreamServiceError(self.status_code, service="Classroom", body={})

    async def get_course_materials(self, telegram_id, course_id):
        return [make_material("material-1")]

    async def create_course_material(self, telegram_id, course_id, materials, title, description=None, topic_id=None):
        self.created = {
            "materials": materials,
            "title": title,
            "description": description,
            "topic_id": topic_id,
        }
        return make_material("material-2", title=title)

    async def delete_course_material(self, telegram_id, course_id, material_id):
        self.deleted = material_id


@pytest.mark.asyncio
async def test_update_material_recreates_when_google_rejects_materials_change():
    client = RecreateRejectingClient(status_code=400)
    service = ClassroomService(client=client)

    merged = [{"driveFile": {"driveFile": {"id": "file-1"}, "shareMode": "VIEW"}}]
    result = await service.update_course_material(
        telegram_id=42,
        course_id="course-1",
        material_id="material-1",
        title=None,
        description=None,
        materials=merged,
        topic_id=None,
    )

    # A new material was created with the merged files and reused the old
    # title/description/topic, then the old one was deleted.
    assert client.created["materials"] == merged
    assert client.created["title"] == "Лекции"
    assert client.created["description"] == "old description"
    assert client.created["topic_id"] == "topic-1"
    assert client.deleted == "material-1"
    assert result.id == "material-2"


@pytest.mark.asyncio
async def test_update_material_does_not_recreate_for_non_material_errors():
    client = RecreateRejectingClient(status_code=403)
    service = ClassroomService(client=client)

    with pytest.raises(UpstreamServiceError):
        await service.update_course_material(
            telegram_id=42,
            course_id="course-1",
            material_id="material-1",
            title=None,
            description=None,
            materials=[{"link": {"url": "https://example.com"}}],
            topic_id=None,
        )

    # Permission/network style errors must not trigger a destructive recreate.
    assert client.created is None
    assert client.deleted is None


@pytest.mark.asyncio
async def test_update_material_does_not_recreate_without_materials_change():
    client = RecreateRejectingClient(status_code=400)
    service = ClassroomService(client=client)

    with pytest.raises(UpstreamServiceError):
        await service.update_course_material(
            telegram_id=42,
            course_id="course-1",
            material_id="material-1",
            title="New title",
            description=None,
            materials=None,
            topic_id=None,
        )

    # A title-only update never needs the recreate fallback.
    assert client.created is None
    assert client.deleted is None