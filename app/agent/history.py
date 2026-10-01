from collections import defaultdict
from dataclasses import asdict

from app.agent.models import Message
from app.core.logging import logger


class InMemoryHistoryStore:

    def __init__(self, system_message: Message | None = None, max_messages: int = 30):
        self._items: defaultdict[int, list[Message]] = defaultdict(list)
        self._system_message = system_message
        self._max_messages = max_messages

    async def get(self, chat_id: int) -> list[Message]:
        if self._system_message and (
            not self._items[chat_id]
            or self._items[chat_id][0].role != "system"
        ):
            self._items[chat_id].insert(0, self._system_message)
        messages = list(self._items[chat_id])
        logger.info("History loaded: chat_id=%s messages=%s", chat_id, [asdict(message) for message in messages])
        return messages

    async def append(self, chat_id: int, *messages: Message):
        items = self._items[chat_id]
        items.extend(messages)
        self._items[chat_id] = items[-self._max_messages:]
        logger.info(
            "History appended: chat_id=%s messages=%s size=%s",
            chat_id,
            [asdict(message) for message in messages],
            len(self._items[chat_id]),
        )

    async def clear(self, chat_id: int):
        self._items.pop(chat_id, None)
        logger.info("History cleared: chat_id=%s", chat_id)