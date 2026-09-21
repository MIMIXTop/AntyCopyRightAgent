from collections import defaultdict

from app.agent.models import Message


class InMemoryHistoryStore:

    def __init__(self, max_messages: int = 30):
        self._items: defaultdict[str, list[Message]] = defaultdict(list)
        self._max_messages = max_messages

    async def get(self, chat_id: int) -> list[Message]:
        return list(self._items[chat_id])

    async def append(self, chat_id: int, *message: Message):
        items = self._items[chat_id]
        items.append(message)
        self._items[chat_id] = items[-self._max_messages:]

    async def clear(self, chat_id: int):
        self._items.pop(chat_id, None)