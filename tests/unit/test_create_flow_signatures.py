"""Regression tests for the confirmation flows in ``app/api/telegram/callbacks.py``.

Each test calls the ``ClassroomService`` method with the exact keyword arguments
the corresponding callback passes, so a signature change on either side fails
here instead of as "❌ Ошибка при создании…" in Telegram.
"""

import pytest

from app.api.classroom.service import ClassroomService
from app.core.errors import UpstreamServiceError


class RecordingClient:
    def __init__(self):
        self.calls = {}

    async def create_assigment(self, **kwargs):
        self.calls["assignment"] = kwargs
        return {"id": "work-1"}

    async def create_announcement(self, **kwargs):
        self.calls["announcement"] = kwargs
        return {"id": "announcement-1"}

    async def create_course_material(self, **kwargs):
        self.calls["material"] = kwargs
        return {"id": "material-1"}


@pytest.mark.asyncio
async def test_assignment_creation_forwards_topic_id_from_callback():
    client = RecordingClient()
    service = ClassroomService(client=client)

    # Exact kwargs used by confirm_work_creation.
    await service.create_assignment(
        telegram_id=42,
        course_id="course-1",
        title="Лабораторная работа №1",
        description="Сделать всё",
        max_points=100,
        due_date=None,
        due_time=None,
        materials=None,
        topic_id="topic-1",
    )

    assert client.calls["assignment"]["topic_id"] == "topic-1"


@pytest.mark.asyncio
async def test_assignment_creation_accepts_missing_topic_id():
    # The callback always forwards topic_id, even when no topic was chosen,
    # so None must be accepted instead of raising TypeError.
    client = RecordingClient()
    service = ClassroomService(client=client)

    await service.create_assignment(
        telegram_id=42,
        course_id="course-1",
        title="Задание по Python",
        description=None,
        max_points=None,
        due_date=None,
        due_time=None,
        materials=None,
        topic_id=None,
    )

    assert client.calls["assignment"]["topic_id"] is None


@pytest.mark.asyncio
async def test_announcement_creation_accepts_callback_kwargs():
    client = RecordingClient()
    service = ClassroomService(client=client)

    # Exact kwargs used by confirm_course_announcement_creation.
    await service.create_announcement(
        telegram_id=42,
        course_id="course-1",
        text="Анонс недели",
        state="PUBLISHED",
        materials=[{"link": {"url": "https://example.com"}}],
    )

    assert client.calls["announcement"]["text"] == "Анонс недели"
    assert client.calls["announcement"]["state"] == "PUBLISHED"


@pytest.mark.asyncio
async def test_material_creation_accepts_callback_kwargs():
    client = RecordingClient()
    service = ClassroomService(client=client)

    # Exact kwargs used by confirm_material_creation.
    await service.create_course_material(
        telegram_id=42,
        course_id="course-1",
        title="Конспекты",
        description="PDF с лекциями",
        materials=[{"driveFile": {"driveFile": {"id": "file-1"}, "shareMode": "VIEW"}}],
        topic_id=None,
    )

    assert client.calls["material"]["title"] == "Конспекты"
    assert client.calls["material"]["topic_id"] is None


def test_upstream_error_includes_upstream_reason():
    error = UpstreamServiceError(
        400,
        service="Classroom",
        body={"error": {"code": 400, "message": "Invalid value at 'topicId'" }},
    )

    assert "HTTP 400" in str(error)
    assert "Invalid value at 'topicId'" in str(error)


def test_upstream_error_without_reason_stays_clean():
    assert str(UpstreamServiceError(502, service="Classroom", body={})) == (
        "Classroom returned HTTP 502"
    )
