import asyncio

from app.bootstrap import build_application
from app.config.settings import settings


async def main() -> None:
    application = await build_application(settings)
    try:
        await application.dispatcher.start_polling(application.bot)
    finally:
        await application.close()

if __name__ == "__main__":
    asyncio.run(main())