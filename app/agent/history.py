from collections import defaultdict
from collections.abc import Hashable
from dataclasses import asdict

from app.agent.models import Message
from app.core.logging import logger


class InMemoryHistoryStore:

    def __init__(self, system_message: Message | None = None, max_messages: int = 30):
        self._items: defaultdict[Hashable, list[Message]] = defaultdict(list)
        self._system_message = system_message
        self._max_messages = max_messages

    async def get(self, conversation_id: Hashable) -> list[Message]:
        if self._system_message and (
            not self._items[conversation_id]
            or self._items[conversation_id][0].role != "system"
        ):
            self._items[conversation_id].insert(0, self._system_message)
        messages = list(self._items[conversation_id])
        log_messages = [
            {"role": message.role, "content": "[system prompt omitted]"}
            if message.role == "system"
            else asdict(message)
            for message in messages
        ]
        logger.info("History loaded: conversation=%s messages=%s", conversation_id, log_messages)
        return messages

    async def append(self, conversation_id: Hashable, *messages: Message):
        items = self._items[conversation_id]
        items.extend(messages)
        self._items[conversation_id] = items[-self._max_messages:]
        logger.info(
            "History appended: conversation=%s messages=%s size=%s",
            conversation_id,
            [asdict(message) for message in messages],
            len(self._items[conversation_id]),
        )

    async def clear(self, conversation_id: Hashable):
        self._items.pop(conversation_id, None)
        logger.info("History cleared: conversation=%s", conversation_id)
