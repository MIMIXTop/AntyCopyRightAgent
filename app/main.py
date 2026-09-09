import asyncio
from app.agent.worker import bot, dp
from app.settings import settings


async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    print("Starting bot...")
    print(f"BOT_TOKEN: {settings.BOT_TOKEN}")
    print(f"MODEL_TOKEN: {settings.OPEN_AI_KEY}")
    asyncio.run(main())