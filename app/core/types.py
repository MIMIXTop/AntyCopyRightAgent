from collections.abc import Sequence
from typing import Protocol, Any

from app.agent.models import Message, LLMResponse


class LLMClient(Protocol):
    async def complete(self, messages: Sequence[Message],
                       tools: list[dict[str, Any]] | None = None) -> LLMResponse:
        ...


class HistoryStore(Protocol):
    async def get(self, chat_id: int) -> list[Any]:
        ...

    async def append(self, chat_id: int, *message: Any) -> None:
        ...

    async def clear(self, chat_id: int) -> None:
        ...
