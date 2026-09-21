from collections.abc import Sequence
from typing import Protocol, Any

class LLMClient(Protocol):
    async def complete(self, message: Sequence[Any], tools: list[dict[str, Any]]) -> Any:
        ...


class HistoryStore(Protocol):
    async def get(self, chat_id: int) -> list[Any]:
        ...

    async def append(self, chat_id: int, *message: Any) -> None:
        ...

    async def clear(self, chat_id: int) -> None:
        ...