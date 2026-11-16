import time
from collections.abc import Callable, Hashable
from dataclasses import dataclass

from app.agent.models import TelegramAttachment


@dataclass
class _Entry:
    attachments: list[TelegramAttachment]
    expires_at: float


class AttachmentMemory:
    """Remembers the files of the latest user message for a short while.

    Telegram attachments are bound to the message that carried them: a button
    press arrives as a separate update with no media. Without this store a
    confirmation turn sees no attachments and silently drops the teacher's
    picture. The store keeps the latest media message per conversation until
    the next text-only message (a new intent) or until the TTL expires.
    """

    def __init__(
            self,
            ttl_seconds: float = 1800,
            clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._entries: dict[Hashable, _Entry] = {}

    def remember(
            self,
            conversation_id: Hashable,
            attachments: list[TelegramAttachment],
    ) -> None:
        if not attachments:
            return
        self._entries[conversation_id] = _Entry(
            attachments=list(attachments),
            expires_at=self._clock() + self._ttl,
        )

    def recent(self, conversation_id: Hashable) -> list[TelegramAttachment]:
        entry = self._entries.get(conversation_id)
        if entry is None:
            return []
        if entry.expires_at <= self._clock():
            self._entries.pop(conversation_id, None)
            return []
        return entry.attachments

    def forget(self, conversation_id: Hashable) -> None:
        self._entries.pop(conversation_id, None)
