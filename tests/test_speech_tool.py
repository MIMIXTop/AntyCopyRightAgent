import json

import pytest

from app.agent.models import ToolContext
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
    async def get_speech(self, text: str) -> bytes:
        return b"opus-audio"


@pytest.mark.asyncio
async def test_speech_tool_sends_voice_and_returns_result():
    registry = ToolRegistry()
    register_telegram_tools(
        registry,
        TelegramService(FakeBot()),
        FakeSpeechService(),
    )

    result = await registry.call(
        "speech",
        ToolContext(chat_id=1, user_id=42, call_id="call-1"),
        {"text": "Добрый день"},
    )

    assert json.loads(result.content) == {"status": "delivered"}
    assert result.terminal is False


@pytest.mark.asyncio
async def test_speech_tool_requires_text():
    registry = ToolRegistry()
    register_telegram_tools(
        registry,
        TelegramService(FakeBot()),
        FakeSpeechService(),
    )

    with pytest.raises(ToolArgumentsError):
        await registry.call(
            "speech",
            ToolContext(chat_id=1, user_id=42, call_id="call-1"),
            {},
        )
