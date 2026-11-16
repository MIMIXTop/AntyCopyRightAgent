import asyncio
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.bootstrap import build_application
from app.config.settings import settings
from app.core.logging import configure_logging, logger


async def main() -> None:
    # 1. Сначала настраиваем логирование один раз
    configure_logging()
    logger.info("Application starting")

    # 2. Собираем приложение
    application = await build_application(settings)

    try:
        # 3. Запускаем бота. Панель логов живёт на сервере: агент только
        # отправляет туда записи через RemoteLogHandler.
        await application.dispatcher.start_polling(application.bot)
    finally:
        logger.info("Application shutting down")
        await application.close()


if __name__ == "__main__":
    asyncio.run(main())
