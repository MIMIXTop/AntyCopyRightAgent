from collections.abc import Hashable, Sequence
from typing import Protocol, Any

from app.agent.models import Message, LLMResponse


class LLMClient(Protocol):
    async def complete(self, messages: Sequence[Message],
                       tools: list[dict[str, Any]] | None = None) -> LLMResponse:
        ...

    async def transcription_voice(self, voice_bytes: bytes):
        ...


class HistoryStore(Protocol):
    async def get(self, conversation_id: Hashable) -> list[Any]:
        ...

    async def append(self, conversation_id: Hashable, *message: Any) -> None:
        ...

    async def clear(self, conversation_id: Hashable) -> None:
        ...