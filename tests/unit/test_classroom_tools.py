import json

import httpx
import pytest
from anyio import run

from app.agent.models import TelegramAttachment, ToolContext
from app.agent.tools import ToolRegistry
from app.classroom.models import ResultRequest
from app.classroom.models import Course
from app.classroom.service import ClassroomService
from app.core.errors import ToolArgumentsError
from app.registers import telegram
from app.registers.classroom import register_classroom_tools
from app.telegram.service import TelegramService


class FakeClassroomService(ClassroomService):
    def __init__(self):
        super().__init__(
            client=None
        )
        self.received = None


    async def create_course(
            self,
            telegram_id,
            course_name,
            course_description="",
            course_section=None,
    ):
        self.received = {
            "telegram_id": telegram_id,
            "course_name": course_name,
            "course_description": course_description,
            "section": course_section,
        }

        return ResultRequest(
            status=201,
            body={"id": "new-course", "name": course_name}
        )

class FakeTelegramService(TelegramService):
    def __init__(self):
        super().__init__(
            bot=FakeBot()
        )
        self.announcement_confirmation = None
        self.update_confirmation = None

    async def request_course_announcement(self, **kwargs):
        self.announcement_confirmation = kwargs

    async def request_course_update(self, **kwargs):
        self.update_confirmation = kwargs

    async def request_announcement_update(self, **kwargs):
        self.update_confirmation = kwargs

    async def request_assignment_update(self, **kwargs):
        self.update_confirmation = kwargs


class FakeBot:
    async def send_message(self, **kwargs):
        return None


class FakeAnnouncementService(FakeClassroomService):
    async def get_concrete_course(self, telegram_id, course_id):
        return type("Course", (), {"name": "Test course"})()

    async def get_structure(self, telegram_id):
        return [
            Course.model_validate(
                {
                    "id": "course-1",
                    "name": "Test course",
                    "creationTime": "2026-10-03T16:00:00Z",
                }
            )
        ]


@pytest.mark.asyncio
async def test_create_course_maps_name_and_return_json():
    service = FakeClassroomService()
    registry = ToolRegistry()
    telegram = FakeTelegramService()
    register_classroom_tools(registry, service, telegram=telegram)

    result = await registry.call(
        "create_course",
        ToolContext(chat_id=1, user_id=42, call_id="call-1"),
        {
            "name": "test",
            "description": "Description",
        }
    )

    payload = json.loads(result.content)
    assert payload["status"] == "paused"
    assert service.get_pending_course(next(iter(service._pending_courses)))["name"] == "test"

@pytest.mark.asyncio
async def test_create_course_empty_name():
    service = FakeClassroomService()
    registry = ToolRegistry()
    register_classroom_tools(registry, service, telegram=FakeTelegramService())

    with pytest.raises(ToolArgumentsError) as exc_inf:
        await registry.call(
            "create_course",
            ToolContext(chat_id=1, user_id=42, call_id="call-1"),
            {
                "description": "Description",
            }
        )

    assert "name is required" in str(exc_inf.value)

    assert service.received is None


@pytest.mark.asyncio
async def test_create_announcement_keeps_links_drive_ids_and_telegram_attachment():
    service = FakeAnnouncementService()
    telegram = FakeTelegramService()
    registry = ToolRegistry()
    register_classroom_tools(registry, service, telegram=telegram)

    result = await registry.call(
        "create_announcement",
        ToolContext(
            chat_id=1,
            user_id=42,
            call_id="call-2",
            attachments=[
                TelegramAttachment(
                    file_id="tg-file",
                    file_name="notes.pdf",
                    mime_type="application/pdf",
                    size=123,
                )
            ],
        ),
        {
            "course_id": "course-1",
            "text": "Материалы к лекции",
            "links": ["https://example.com"],
            "drive_file_ids": ["drive-1"],
        },
    )

    assert json.loads(result.content)["status"] == "paused"
    pending = service.get_pending_announcement(
        next(iter(service._pending_announcements))
    )
    assert pending["materials"] == [
        {"link": {"url": "https://example.com"}},
        {
            "driveFile": {
                "driveFile": {"id": "drive-1"},
                "shareMode": "VIEW",
            }
        },
    ]
    assert pending["telegram_attachments"][0].file_id == "tg-file"
    assert telegram.announcement_confirmation["course_name"] == "Test course"


@pytest.mark.asyncio
async def test_get_courses_serializes_datetime_fields():
    service = FakeAnnouncementService()
    registry = ToolRegistry()
    register_classroom_tools(registry, service, telegram=FakeTelegramService())

    result = await registry.call(
        "get_courses",
        ToolContext(chat_id=1, user_id=42, call_id="call-3"),
        {},
    )

    payload = json.loads(result.content)
    assert payload["courses"][0]["creation_time"] == "2026-10-03T16:00:00Z"


@pytest.mark.asyncio
async def test_update_course_uses_confirmation_keyboard_flow():
    service = FakeAnnouncementService()
    telegram = FakeTelegramService()
    registry = ToolRegistry()
    register_classroom_tools(registry, service, telegram=telegram)

    result = await registry.call(
        "update_course",
        ToolContext(chat_id=1, user_id=42, call_id="call-4"),
        {"course_id": "course-1", "name": "Renamed"},
    )

    payload = json.loads(result.content)
    assert result.terminal is True
    assert payload["status"] == "paused"
    assert telegram.update_confirmation["course_name"] == "Test course"
    pending = service.get_pending_update(payload["pending_id"])
    assert pending["resource"] == "course"
    assert pending["name"] == "Renamed"
