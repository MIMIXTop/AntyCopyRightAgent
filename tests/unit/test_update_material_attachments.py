import json

import pytest

from app.agent.models import TelegramAttachment, ToolContext
from app.agent.tools import ToolRegistry
from app.api.classroom.service import ClassroomService
from app.api.telegram.service import TelegramService
from app.core.errors import ToolArgumentsError
from app.registers.classroom import register_classroom_tools


class FakeBot:
    async def send_message(self, **kwargs):
        return None


class FakeTelegramService(TelegramService):
    def __init__(self):
        super().__init__(bot=FakeBot())
        self.material_update = None

    async def request_course_material_update(self, **kwargs):
        self.material_update = kwargs


class FakeClassroomService(ClassroomService):
    def __init__(self):
        super().__init__(client=None)


def build_registry():
    service = FakeClassroomService()
    telegram = FakeTelegramService()
    registry = ToolRegistry()
    register_classroom_tools(registry, service, telegram)
    return registry, service, telegram


def make_attachments(count: int) -> list[TelegramAttachment]:
    return [
        TelegramAttachment(
            file_id=f"tg-file-{index}",
            file_name=f"lecture_{index}.pdf",
            mime_type="application/pdf",
            size=100 + index,
        )
        for index in range(count)
    ]


@pytest.mark.asyncio
async def test_update_material_accepts_only_telegram_attachments():
    registry, service, telegram = build_registry()

    result = await registry.call(
        "update_material",
        ToolContext(
            chat_id=1,
            user_id=42,
            call_id="call-1",
            attachments=make_attachments(4),
        ),
        {
            "course_id": "course-1",
            "material_id": "material-1",
        },
    )

    payload = json.loads(result.content)
    assert result.terminal is True
    assert payload["status"] == "paused"

    pending = service.get_pending_update(payload["pending_id"])
    assert pending["resource"] == "material"
    assert len(pending["telegram_attachments"]) == 4
    assert pending["telegram_attachments"][0].file_name == "lecture_0.pdf"
    assert pending["materials"] is None

    # The confirmation message must mention the attached files.
    assert telegram.material_update["pending_id"] == payload["pending_id"]
    assert "4 файл(ов) из Telegram" in telegram.material_update["changes"]["files"]


@pytest.mark.asyncio
async def test_update_material_rejects_empty_resource_lists():
    registry, service, _ = build_registry()

    # An empty list must not become an empty materials PATCH: that is what made
    # Google reject the request with "Не удалось изменить объект".
    with pytest.raises(ToolArgumentsError, match="At least one field"):
        await registry.call(
            "update_material",
            ToolContext(chat_id=1, user_id=42, call_id="call-2"),
            {
                "course_id": "course-1",
                "material_id": "material-1",
                "links": [],
                "drive_file_ids": [],
            },
        )

    assert service._pending_updates == {}


@pytest.mark.asyncio
async def test_update_material_keeps_links_flow():
    registry, service, _ = build_registry()

    result = await registry.call(
        "update_material",
        ToolContext(chat_id=1, user_id=42, call_id="call-3"),
        {
            "course_id": "course-1",
            "material_id": "material-1",
            "links": ["https://example.com/lecture"],
        },
    )

    payload = json.loads(result.content)
    pending = service.get_pending_update(payload["pending_id"])
    assert pending["materials"] == [{"link": {"url": "https://example.com/lecture"}}]
    assert pending["telegram_attachments"] == []
