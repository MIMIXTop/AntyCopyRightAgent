import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config.settings import settings
from app.core.remote_log import RemoteLogHandler


def configure_logging(file_path: str | None = None) -> None:
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        # Close only handlers we created (the remote one owns a thread).
        # Foreign handlers from pytest or the host app are left untouched.
        if getattr(handler, "_kira_managed", False):
            try:
                handler.close()
            except Exception:
                pass
    console_handler._kira_managed = True
    root_logger.addHandler(console_handler)

    if settings.LOG_FILE_ENABLED:
        path = Path(file_path or settings.LOG_FILE_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            path,
            maxBytes=settings.LOG_FILE_MAX_BYTES,
            backupCount=settings.LOG_FILE_BACKUPS,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler._kira_managed = True
        root_logger.addHandler(file_handler)

    # The server owns the log panel; the agent only pushes records to it.
    if settings.REMOTE_LOG_ENABLED and settings.LOG_REMOTE_TOKEN:
        url = settings.LOG_REMOTE_URL or (
            f"{settings.CPP_SERVER_URL.rstrip('/')}/dashboard/api/logs/ingest"
        )
        remote_handler = RemoteLogHandler(
            url=url,
            token=settings.LOG_REMOTE_TOKEN,
            service=settings.LOG_REMOTE_SERVICE,
        )
        remote_handler.setFormatter(formatter)
        remote_handler._kira_managed = True
        root_logger.addHandler(remote_handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)


logger = logging.getLogger("KiraAgent")
