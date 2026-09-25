from aiogram import Bot
from app.core.errors import ApplicationError


class TelegramService:

    def __init__(self, bot: Bot):
        self._bot = bot

    async def send_message(self, text: str, chat_id: int):
        await self._bot.send_message(chat_id=chat_id, text=text)

    async def send_error(self, chat_id: int, error: ApplicationError):
        await self.send_message(
            chat_id=chat_id,
            text=f"Не удалось выполнить запрос: {error}",
        )
