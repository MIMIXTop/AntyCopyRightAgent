import asyncio

from app.bootstrap import build_application
from app.config.settings import settings
from app.core.logging import logger


async def main() -> None:
    logger.info("Application starting")
    application = await build_application(settings)
    try:
        await application.dispatcher.start_polling(application.bot)
    finally:
        logger.info("Application shutting down")
        await application.close()

if __name__ == "__main__":
    asyncio.run(main())