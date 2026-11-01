import asyncio
from typing import Awaitable, Callable

from app.core.logging import logger

# Telegram delivers album (media group) parts as separate updates within a few
# hundred milliseconds; wait briefly so every part is collected before processing.
DEFAULT_AGGREGATION_DELAY = 1.0


class MediaGroupBuffer:
    """Aggregates Telegram media-group parts and processes them as one batch.

    All parts of one album share (chat_id, media_group_id). The first arriving
    part schedules a delayed processing task; every part awaits the same task,
    so a single callback receives the complete album exactly once.
    """

    def __init__(
            self,
            process: Callable[[list], Awaitable[None]],
            delay: float = DEFAULT_AGGREGATION_DELAY,
    ) -> None:
        self._process = process
        self._delay = delay
        self._buffers: dict[tuple[int, str], list] = {}
        self._tasks: dict[tuple[int, str], asyncio.Task] = {}

    async def add(self, message) -> None:
        key = (message.chat.id, message.media_group_id)
        self._buffers.setdefault(key, []).append(message)
        task = self._tasks.get(key)
        if task is None:
            task = asyncio.create_task(self._run(key))
            self._tasks[key] = task
        await task

    async def _run(self, key: tuple[int, str]) -> None:
        try:
            await asyncio.sleep(self._delay)
            parts = self._buffers.pop(key, [])
            logger.info(
                "Media group batch ready: chat_id=%s group=%s parts=%s",
                key[0],
                key[1],
                len(parts),
            )
            if parts:
                await self._process(parts)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Log once; every awaiting handler returns silently instead of
            # producing four duplicated error reports for one album.
            logger.exception("Media group processing failed: chat_id=%s group=%s", key[0], key[1])
        finally:
            self._tasks.pop(key, None)
