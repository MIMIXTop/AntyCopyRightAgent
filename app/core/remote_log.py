"""Ship formatted log records to the Kurvot server dashboard.

The agent runs on the host now, so ``docker logs`` is gone. Instead of
running its own web panel, every record is pushed to the server, which
already owns the admin dashboard and its WebSocket log stream.

The handler is deliberately fire-and-forget: logging must never block the
bot or crash it when the server is down.
"""

from __future__ import annotations

import atexit
import json
import logging
import queue
import threading
import urllib.request


class RemoteLogHandler(logging.Handler):
    """Batches formatted log lines and POSTs them to the server."""

    def __init__(
        self,
        url: str,
        token: str,
        service: str = "telegram-agent",
        batch_size: int = 50,
        timeout: float = 5.0,
        max_queue: int = 2000,
    ) -> None:
        super().__init__()
        self.url = url
        self.token = token
        self.service = service
        self.batch_size = batch_size
        self.timeout = timeout
        self._queue: queue.Queue[str] = queue.Queue(maxsize=max_queue)
        self._closed = threading.Event()
        self._close_lock = threading.Lock()
        self._closed_done = False
        self._thread = threading.Thread(
            target=self._run,
            name="remote-log",
            daemon=True,
        )
        self._thread.start()
        atexit.register(self.close)

    def emit(self, record: logging.LogRecord) -> None:
        if self._closed.is_set():
            return
        try:
            message = self.format(record)
        except Exception:
            self.handleError(record)
            return
        try:
            self._queue.put_nowait(message)
        except queue.Full:
            # Server is down or slow: drop instead of blocking the event loop
            # or growing memory forever.
            pass

    def _run(self) -> None:
        while not self._closed.is_set():
            try:
                first = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            batch = [first]
            while len(batch) < self.batch_size:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            self._send(batch)

        # Best effort: flush what is left before the process exits.
        remaining: list[str] = []
        while len(remaining) < self.batch_size * 4:
            try:
                remaining.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if remaining:
            self._send(remaining)

    def _send(self, lines: list[str]) -> None:
        payload = json.dumps(
            {"service": self.service, "lines": lines},
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-Log-Token": self.token,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                response.read()
        except Exception:
            # Never log from here: it would recurse into this handler.
            pass

    def close(self) -> None:
        with self._close_lock:
            if self._closed_done:
                return
            self._closed_done = True
        self._closed.set()
        self._thread.join(timeout=self.timeout + 1)
        super().close()
