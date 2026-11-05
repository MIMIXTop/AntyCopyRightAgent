import json

import pytest

from app.agent.models import ToolContext
from app.agent.prompt import load_speech_prompt
from app.agent.speech_service import SpeechService
from app.agent.tools import ToolRegistry
from app.api.telegram.service import TelegramService
from app.core.errors import ToolArgumentsError
from app.registers.telegram import register_telegram_tools


class FakeBot:
    async def send_voice(self, **kwargs):
        return None

    async def send_message(self, **kwargs):
        return None


class FakeSpeechService:
    def __init__(self):
        self.calls: list[dict] = []

    async def get_speech(self, text: str, instructions: str | None = None) -> bytes:
        self.calls.append({"text": text, "instructions": instructions})
        return b"opus-audio"


def make_registry(speech_service=None) -> ToolRegistry:
    registry = ToolRegistry()
    register_telegram_tools(
        registry,
        TelegramService(FakeBot()),
        speech_service or FakeSpeechService(),
    )
    return registry


@pytest.mark.asyncio
async def test_speech_tool_sends_voice_and_returns_result():
    registry = make_registry()

    result = await registry.call(
        "speech",
        ToolContext(chat_id=1, user_id=42, call_id="call-1"),
        {"text": "Добрый день"},
    )

    assert json.loads(result.content) == {"status": "delivered"}
    assert result.terminal is False


@pytest.mark.asyncio
async def test_speech_tool_requires_text():
    registry = make_registry()

    with pytest.raises(ToolArgumentsError):
        await registry.call(
            "speech",
            ToolContext(chat_id=1, user_id=42, call_id="call-1"),
            {},
        )


@pytest.mark.asyncio
async def test_speech_tool_passes_instructions_to_service():
    speech_service = FakeSpeechService()
    registry = make_registry(speech_service)

    await registry.call(
        "speech",
        ToolContext(chat_id=1, user_id=42, call_id="call-2"),
        {"text": "Дедлайн в пятницу", "instructions": "slow and solemn"},
    )

    assert speech_service.calls == [
        {"text": "Дедлайн в пятницу", "instructions": "slow and solemn"}
    ]


@pytest.mark.asyncio
async def test_speech_tool_treats_blank_instructions_as_missing():
    speech_service = FakeSpeechService()
    registry = make_registry(speech_service)

    await registry.call(
        "speech",
        ToolContext(chat_id=1, user_id=42, call_id="call-3"),
        {"text": "Привет", "instructions": "   "},
    )

    assert speech_service.calls == [{"text": "Привет", "instructions": None}]


@pytest.mark.asyncio
async def test_speech_tool_rejects_non_string_instructions():
    registry = make_registry()

    with pytest.raises(ToolArgumentsError):
        await registry.call(
            "speech",
            ToolContext(chat_id=1, user_id=42, call_id="call-4"),
            {"text": "Привет", "instructions": 42},
        )


@pytest.mark.asyncio
async def test_speech_tool_rejects_too_long_instructions():
    from app.agent.speech_service import MAX_EXTRA_CHARS

    registry = make_registry()

    with pytest.raises(ToolArgumentsError):
        await registry.call(
            "speech",
            ToolContext(chat_id=1, user_id=42, call_id="call-5"),
            {"text": "Привет", "instructions": "x" * (MAX_EXTRA_CHARS + 1)},
        )


def test_build_instructions_returns_base_without_extra():
    service = SpeechService.__new__(SpeechService)
    service.base_instructions = "BASE PERSONA"

    assert service._build_instructions() == "BASE PERSONA"
    assert service._build_instructions("  ") == "BASE PERSONA"


def test_build_instructions_appends_extra():
    from app.agent.speech_service import MAX_INSTRUCTION_CHARS

    service = SpeechService.__new__(SpeechService)
    service.base_instructions = "BASE PERSONA"

    combined = service._build_instructions("whisper, confidential")

    assert combined.startswith("BASE PERSONA")
    assert "For this phrase: whisper, confidential" in combined
    assert len(combined) <= MAX_INSTRUCTION_CHARS


def test_build_instructions_truncates_long_extra():
    from app.agent.speech_service import MAX_INSTRUCTION_CHARS

    service = SpeechService.__new__(SpeechService)
    service.base_instructions = "BASE PERSONA"

    combined = service._build_instructions("y" * 2000)

    assert len(combined) <= MAX_INSTRUCTION_CHARS
    assert combined.startswith("BASE PERSONA")


def test_build_instructions_drops_extra_when_base_fills_budget():
    from app.agent.speech_service import MAX_INSTRUCTION_CHARS

    service = SpeechService.__new__(SpeechService)
    service.base_instructions = "z" * MAX_INSTRUCTION_CHARS

    combined = service._build_instructions("whisper")

    assert combined == "z" * MAX_INSTRUCTION_CHARS


def test_real_base_prompt_fits_api_budget_alone():
    """The shipped persona must pass the endpoint's 500-char limit by itself."""
    from app.agent.speech_service import MAX_INSTRUCTION_CHARS

    service = SpeechService.__new__(SpeechService)
    service.base_instructions = load_speech_prompt().strip()

    assert len(service.base_instructions) <= MAX_INSTRUCTION_CHARS
    # and it must leave room for a per-phrase addition
    combined = service._build_instructions("slow and solemn")
    assert len(combined) <= MAX_INSTRUCTION_CHARS
    assert "For this phrase: slow and solemn" in combined
