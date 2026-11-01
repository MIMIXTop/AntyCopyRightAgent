import asyncio

import pytest

from app.agent.history import InMemoryHistoryStore
from app.agent.models import LLMResponse, ToolCallInfo, ToolContext, ToolResult
from app.agent.service import AgentService
from app.agent.tools import ToolRegistry
from app.core.errors import AgentIterationLimitError, ToolArgumentsError


class FakeLLM:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    async def complete(self, messages, tools=None):
        self.calls.append((messages, tools))
        return next(self.responses)


def make_service(llm, handler=None, max_iterations=3):
    registry = ToolRegistry()
    if handler:
        async def wrapped(context: ToolContext, args: dict):
            return await handler(context, args)
        registry.register("demo", wrapped, {"name": "demo"})
    return AgentService(llm, InMemoryHistoryStore(), registry, max_iterations)


@pytest.mark.asyncio
async def test_agent_returns_text_and_preserves_history():
    llm = FakeLLM([LLMResponse("hello")])
    service = make_service(llm)

    assert await service.handle(1, 2, "hi") == "hello"
    history = await service._history.get(1)
    assert [message.role for message in history] == ["user", "assistant"]
    assert llm.calls[0][0][0].content == "hi"


@pytest.mark.asyncio
async def test_agent_executes_tool_then_returns_final_text():
    called = {}

    async def handler(context, args):
        called.update(args)
        return ToolResult(context.call_id, '{"ok":true}')

    llm = FakeLLM([
        LLMResponse("", [ToolCallInfo("call-1", "demo", '{"value": 7}')]),
        LLMResponse("done"),
    ])
    service = make_service(llm, handler)

    assert await service.handle(1, 2, "run") == "done"
    assert called == {"value": 7}
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_agent_returns_tool_exception_to_llm_without_raising():
    async def handler(context, args):
        raise ToolArgumentsError("demo", "value is invalid")

    llm = FakeLLM([
        LLMResponse("", [ToolCallInfo("call-1", "demo", "{}")]),
        LLMResponse("Параметр оказался некорректным."),
    ])
    service = make_service(llm, handler)

    assert await service.handle(1, 2, "run") == "Параметр оказался некорректным."
    tool_message = llm.calls[1][0][-1]
    assert '"status": "error"' in tool_message.content
    assert "ToolArgumentsError" in tool_message.content


@pytest.mark.asyncio
async def test_agent_ignores_terminal_flag_on_non_finish_tool():
    async def handler(context, args):
        return ToolResult(context.call_id, '{"status":"paused"}', terminal=True)

    llm = FakeLLM([
        LLMResponse("", [ToolCallInfo("call-1", "demo", "{}")]),
        LLMResponse("continued"),
    ])
    service = make_service(llm, handler)

    assert await service.handle(1, 2, "run") == "continued"
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_agent_stops_only_when_finish_tool_returns_terminal():
    async def handler(context, args):
        return ToolResult(context.call_id, '{"status":"ok"}', terminal=True)

    llm = FakeLLM([
        LLMResponse("", [ToolCallInfo("call-1", "finish", "{}")]),
    ])
    registry = ToolRegistry()
    registry.register("finish", handler, {"name": "finish"})
    service = AgentService(llm, InMemoryHistoryStore(), registry, max_iterations=1)

    assert await service.handle(1, 2, "run") == ""
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_agent_can_resume_after_confirmation_event():
    llm = FakeLLM([LLMResponse("Продолжаю работу.")])
    service = make_service(llm)

    result = await service.resume_after_action(
        chat_id=1,
        user_id=2,
        event={
            "type": "action_result",
            "action": "create_topic",
            "status": "confirmed",
            "success": True,
        },
    )

    assert result == "Продолжаю работу."
    history = await service._history.get(1)
    assert history[-1].content == "Продолжаю работу."


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", ["not-json", "[]", "null"])
async def test_agent_rejects_invalid_tool_arguments(arguments):
    llm = FakeLLM([
        LLMResponse("", [ToolCallInfo("call-1", "demo", arguments)]),
        LLMResponse("Параметры запроса некорректны."),
    ])
    service = make_service(llm)

    assert await service.handle(1, 2, "run") == "Параметры запроса некорректны."


@pytest.mark.asyncio
async def test_agent_enforces_iteration_limit():
    response = LLMResponse("", [ToolCallInfo("call-1", "unknown", "{}")])
    llm = FakeLLM([response])
    service = make_service(llm, max_iterations=1)

    with pytest.raises(AgentIterationLimitError):
        await service.handle(1, 2, "run")

    async def non_terminal(context, args):
        return ToolResult(context.call_id, "again")

    llm = FakeLLM([response])
    service = make_service(llm, non_terminal, max_iterations=1)
    response = LLMResponse("", [ToolCallInfo("call-1", "demo", "{}")])
    llm.responses = iter([response])
    with pytest.raises(AgentIterationLimitError):
        await service.handle(1, 2, "run")


class SlowLLM:
    """LLM stub that tracks how many runs are inside complete() concurrently."""

    def __init__(self, delay: float = 0.05):
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self.runs = 0

    async def complete(self, messages, tools=None):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delay)
            self.runs += 1
            return LLMResponse(f"ok-{self.runs}")
        finally:
            self.active -= 1


@pytest.mark.asyncio
async def test_concurrent_handles_in_same_chat_never_interleave():
    llm = SlowLLM()
    service = AgentService(llm, InMemoryHistoryStore(), ToolRegistry(), max_iterations=1)

    # Two rapid messages in one chat (the pre-album-bug scenario): runs must be
    # serialized, so history stays strictly ordered instead of scrambling.
    await asyncio.gather(
        service.handle(1, 2, "first"),
        service.handle(1, 2, "second"),
    )

    assert llm.max_active == 1
    history = await service._history.get(1)
    roles = [message.role for message in history]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert [history[0].content, history[2].content] == ["first", "second"]


@pytest.mark.asyncio
async def test_handles_in_different_chats_run_concurrently():
    llm = SlowLLM()
    service = AgentService(llm, InMemoryHistoryStore(), ToolRegistry(), max_iterations=1)

    await asyncio.gather(
        service.handle(1, 2, "chat one"),
        service.handle(2, 3, "chat two"),
    )

    # The lock is per chat: unrelated chats must not block each other.
    assert llm.max_active == 2
