import pytest

from app.agent.history import InMemoryHistoryStore
from app.agent.models import (
    DeliveryContext,
    LLMResponse,
    ToolCallInfo,
    ToolContext,
    ToolResult,
)
from app.agent.service import AgentService
from app.agent.tool_policy import GROUP_SAFE_TOOLS
from app.agent.tools import ToolRegistry
from app.core.errors import ToolAccessDeniedError

GROUP_ID = -100123
USER_ID = 111


class RecordingLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def complete(self, messages, tools=None):
        self.calls.append((messages, tools))
        return self.responses.pop(0)


async def noop(context, args):
    return ToolResult(context.call_id, "{}")


def make_registry(*names):
    registry = ToolRegistry()
    for name in names:
        registry.register(name, noop, {"name": name})
    return registry


def schema_names(schemas):
    return {schema["name"] for schema in schemas}


def group_delivery():
    return DeliveryContext(
        chat_id=GROUP_ID,
        user_id=USER_ID,
        chat_type="supergroup",
    )


def test_registry_filters_schemas_by_policy():
    registry = make_registry("send_message", "create_course", "web_search")

    assert schema_names(registry.schemas()) == {
        "send_message",
        "create_course",
        "web_search",
    }
    assert schema_names(registry.schemas(allowed=GROUP_SAFE_TOOLS)) == {
        "send_message",
        "web_search",
    }


@pytest.mark.asyncio
async def test_blocked_tool_is_not_executed():
    called = []

    async def handler(context, args):
        called.append(args)
        return ToolResult(context.call_id, "{}")

    registry = ToolRegistry()
    registry.register("create_course", handler, {"name": "create_course"})

    with pytest.raises(ToolAccessDeniedError):
        await registry.call(
            "create_course",
            ToolContext(1, 2, "call-1"),
            {},
            allowed=GROUP_SAFE_TOOLS,
        )

    assert called == []


@pytest.mark.asyncio
async def test_group_turn_only_receives_safe_tools():
    llm = RecordingLLM([LLMResponse("ok")])
    service = AgentService(
        llm,
        InMemoryHistoryStore(),
        make_registry("send_message", "create_course"),
        group_safe_mode=True,
    )

    await service.handle(
        chat_id=GROUP_ID,
        user_id=USER_ID,
        text="привет",
        delivery=group_delivery(),
    )

    assert schema_names(llm.calls[0][1]) == {"send_message"}


@pytest.mark.asyncio
async def test_private_turn_still_receives_all_tools():
    llm = RecordingLLM([LLMResponse("ok")])
    service = AgentService(
        llm,
        InMemoryHistoryStore(),
        make_registry("send_message", "create_course"),
        group_safe_mode=True,
    )

    await service.handle(chat_id=USER_ID, user_id=USER_ID, text="привет")

    assert schema_names(llm.calls[0][1]) == {"send_message", "create_course"}


@pytest.mark.asyncio
async def test_blocked_tool_call_in_group_returns_an_error_to_the_model():
    called = []

    async def handler(context, args):
        called.append(args)
        return ToolResult(context.call_id, "{}")

    registry = ToolRegistry()
    registry.register("create_course", handler, {"name": "create_course"})
    registry.register("send_message", noop, {"name": "send_message"})
    llm = RecordingLLM(
        [
            LLMResponse("", [ToolCallInfo("call-1", "create_course", "{}")]),
            LLMResponse("Не могу сделать это в группе."),
        ]
    )
    service = AgentService(
        llm,
        InMemoryHistoryStore(),
        registry,
        max_iterations=3,
        group_safe_mode=True,
    )

    result = await service.handle(
        chat_id=GROUP_ID,
        user_id=USER_ID,
        text="создай курс",
        delivery=group_delivery(),
    )

    assert result == "Не могу сделать это в группе."
    assert called == []
    history = await service._history.get((GROUP_ID, USER_ID))
    tool_messages = [message for message in history if message.role == "tool"]
    assert len(tool_messages) == 1
    assert "ToolAccessDeniedError" in tool_messages[0].content


@pytest.mark.asyncio
async def test_safe_mode_can_be_disabled_for_groups():
    llm = RecordingLLM([LLMResponse("ok")])
    service = AgentService(
        llm,
        InMemoryHistoryStore(),
        make_registry("send_message", "create_course"),
        group_safe_mode=False,
    )

    await service.handle(
        chat_id=GROUP_ID,
        user_id=USER_ID,
        text="привет",
        delivery=group_delivery(),
    )

    assert schema_names(llm.calls[0][1]) == {"send_message", "create_course"}
