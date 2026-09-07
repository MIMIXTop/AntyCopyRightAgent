import asyncio

from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command

BOT_TOKEN = '8679957581:AAGw_grdQj_TAHLKty7RvNjZ2CsHBM7YP2I'

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command('start'))
async def handle_start(message: Message):
    await message.answer("Hello bro")


async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())