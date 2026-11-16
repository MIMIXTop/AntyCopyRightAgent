import pytest

from app.agent.attachment_memory import AttachmentMemory
from app.agent.history import InMemoryHistoryStore
from app.agent.models import (
    LLMResponse,
    TelegramAttachment,
    ToolCallInfo,
    ToolContext,
    ToolResult,
)
from app.agent.service import AgentService
from app.agent.tools import ToolRegistry


class FakeLLM:
    def __init__(self, responses):
        self.responses = iter(responses)

    async def complete(self, messages, tools=None):
        return next(self.responses)


def _attachment(file_id: str = "file-1", name: str = "knight.jpg") -> TelegramAttachment:
    return TelegramAttachment(
        file_id=file_id,
        file_name=name,
        mime_type="image/jpeg",
        kind="photo",
        data=b"jpeg",
    )


def test_attachment_memory_expires_and_forgets():
    now = [100.0]
    memory = AttachmentMemory(ttl_seconds=30, clock=lambda: now[0])

    memory.remember(1, [_attachment()])
    assert [item.file_id for item in memory.recent(1)] == ["file-1"]

    now[0] += 31
    assert memory.recent(1) == []

    memory.remember(1, [_attachment()])
    memory.forget(1)
    assert memory.recent(1) == []


def test_attachment_memory_remembers_latest_only():
    memory = AttachmentMemory(ttl_seconds=30)
    memory.remember(1, [_attachment("old")])
    memory.remember(1, [_attachment("new", "new.jpg")])

    assert [item.file_id for item in memory.recent(1)] == ["new"]


@pytest.mark.asyncio
async def test_confirmation_turn_reuses_attachments_from_the_previous_message():
    seen: list[ToolContext] = []

    async def demo(context: ToolContext, args: dict):
        seen.append(context)
        return ToolResult(context.call_id, '{"status":"ok"}')

    registry = ToolRegistry()
    registry.register("demo", demo, {"name": "demo"})
    llm = FakeLLM([
        LLMResponse("Жду подтверждения."),
        LLMResponse("", [ToolCallInfo("call-1", "demo", "{}")]),
        LLMResponse("Готово."),
    ])
    service = AgentService(llm, InMemoryHistoryStore(), registry, max_iterations=3)

    await service.handle(1, 2, "сделай анонс с этой картинкой", [_attachment()])
    await service.resume_after_action(
        1,
        2,
        {"type": "action_result", "action": "create_announcement", "status": "confirmed"},
    )

    assert len(seen) == 1
    assert [item.file_id for item in seen[0].attachments] == ["file-1"]
    assert seen[0].attachments_reused is True


@pytest.mark.asyncio
async def test_new_text_message_clears_remembered_attachments():
    seen: list[ToolContext] = []

    async def demo(context: ToolContext, args: dict):
        seen.append(context)
        return ToolResult(context.call_id, '{"status":"ok"}')

    registry = ToolRegistry()
    registry.register("demo", demo, {"name": "demo"})
    llm = FakeLLM([
        LLMResponse("ok"),
        LLMResponse("ok"),
        LLMResponse("", [ToolCallInfo("call-1", "demo", "{}")]),
        LLMResponse("done"),
    ])
    service = AgentService(llm, InMemoryHistoryStore(), registry, max_iterations=3)

    await service.handle(1, 2, "картинка", [_attachment()])
    # A later text-only request is a different intent and must not inherit it.
    await service.handle(1, 2, "а теперь просто текст")
    await service.resume_after_action(
        1, 2, {"type": "action_result", "action": "x", "status": "confirmed"}
    )

    assert len(seen) == 1
    assert seen[0].attachments == []
    assert seen[0].attachments_reused is False
