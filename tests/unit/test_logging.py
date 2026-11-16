import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.config.settings import settings
from app.core.logging import configure_logging
from app.core.remote_log import RemoteLogHandler


def test_configure_logging_writes_a_file(tmp_path, monkeypatch):
    # Keep the test offline: the remote handler is covered separately.
    monkeypatch.setattr(settings, "REMOTE_LOG_ENABLED", False)
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    log_path = tmp_path / "kira.log"

    try:
        configure_logging(file_path=str(log_path))
        logging.getLogger("test.file").info("hello from the file handler")
        for handler in root.handlers:
            handler.flush()
        content = log_path.read_text(encoding="utf-8")
    finally:
        for handler in list(root.handlers):
            if getattr(handler, "_kira_managed", False):
                handler.close()
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)

    assert "hello from the file handler" in content
    assert "INFO" in content


def test_remote_log_handler_posts_batches_with_token():
    received: list[tuple[str | None, dict]] = []

    class CaptureHandler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - stdlib naming
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            received.append((self.headers.get("X-Log-Token"), payload))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):  # silence the test server
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), CaptureHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    handler = RemoteLogHandler(
        url=f"http://127.0.0.1:{server.server_address[1]}/ingest",
        token="secret-token",
        batch_size=1,
        timeout=2.0,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    try:
        handler.emit(
            logging.LogRecord(
                "test", logging.INFO, __file__, 1, "hello from the agent", None, None
            )
        )
        deadline = time.monotonic() + 3
        while not received and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        handler.close()
        server.shutdown()
        server.server_close()

    assert received, "the handler did not post anything"
    token, payload = received[0]
    assert token == "secret-token"
    assert payload["service"] == "telegram-agent"
    assert payload["lines"] == ["hello from the agent"]


def test_remote_log_handler_survives_an_unreachable_server():
    handler = RemoteLogHandler(
        url="http://127.0.0.1:1/ingest",
        token="secret-token",
        batch_size=1,
        timeout=0.2,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    try:
        handler.emit(
            logging.LogRecord(
                "test", logging.INFO, __file__, 1, "server is down", None, None
            )
        )
    finally:
        handler.close()
