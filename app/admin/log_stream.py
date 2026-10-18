import asyncio
import collections
import logging

class LogBroadcaster(logging.Handler):
    def __init__(self, max_history: int = 150):
        super().__init__()
        self.history: collections.deque[str] = collections.deque(maxlen=max_history)
        self.subscribers: set[asyncio.Queue] = set()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.history.append(msg)
            # Рассылаем всем открытым вкладкам браузера
            for queue in list(self.subscribers):
                try:
                    queue.put_nowait(msg)
                except asyncio.QueueFull:
                    pass
        except Exception:
            self.handleError(record)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.subscribers.discard(q)

log_broadcaster = LogBroadcaster()