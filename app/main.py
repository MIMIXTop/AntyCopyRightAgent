import asyncio

from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command
from settings import settings


bot = Bot(token=settings.BOT_TOKEN.get_secret_value())
dp = Dispatcher()

@dp.message(Command('start'))
async def handle_start(message: Message):
    await message.answer("Hello bro")


async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    print("Starting bot...")
    asyncio.run(main())