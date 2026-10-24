import asyncio
import sys
from pathlib import Path

from aiohttp import web

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.bootstrap import build_application
from app.config.settings import settings
from app.core.logging import configure_logging, logger
from app.admin.server import create_admin_app

async def start_admin_panel(port: int = 9090) -> web.AppRunner:
    app = create_admin_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Admin panel is available on http://0.0.0.0:%d/admin", port)
    return runner

async def main() -> None:
    # 1. Сначала настраиваем логирование один раз
    configure_logging()
    logger.info("Application starting")

    # 2. Собираем приложение
    application = await build_application(settings)
    admin_runner = None

    try:
        # 3. Запускаем панель и бота
        admin_runner = await start_admin_panel(port=9090)
        await application.dispatcher.start_polling(application.bot)
    finally:
        logger.info("Application shutting down")
        if admin_runner:
            await admin_runner.cleanup()
        await application.close()

if __name__ == "__main__":
    asyncio.run(main())
