import io

from aiogram import Bot

from app.core.errors import ApplicationError
from app.telegram.keyboards import get_course_confirm_keyboard, get_course_announcement_keyboard, get_course_work_keyboard
from app.core.logging import logger

class TelegramService:

    def __init__(self, bot: Bot):
        self._bot = bot
        logger.info("TelegramService initialized")

    async def send_message(self, text: str, chat_id: int):
        logger.info("TelegramService.send_message called: chat_id=%s text=%r", chat_id, text)
        await self._bot.send_message(chat_id=chat_id, text=text)

    async def send_error(self, chat_id: int, error: ApplicationError):
        logger.error("TelegramService.send_error called: chat_id=%s error=%s", chat_id, error)
        await self.send_message(
            chat_id=chat_id,
            text=f"Не удалось выполнить запрос: {error}",
        )

    async def get_file_content(self, file_id: str):
        logger.info("TelegramService.get_file_content called: file_id=%s", file_id)

        tg_file = await self._bot.get_file(file_id)
        file_io = io.BytesIO()
        await self._bot.download_file(tg_file.file_path, destination=file_io)
        file_name = tg_file.file_path.split("/")[-1]
        return file_name, file_io.getvalue()

    async def request_course_confirmation(self, chat_id: int, course_name: str, pending_id: str):
        logger.info(
            "TelegramService.request_course_confirmation called: chat_id=%s course_name=%r pending_id=%s",
            chat_id,
            course_name,
            pending_id,
        )
        await self._bot.send_message(
            chat_id=chat_id,
            text=f"Вы уверены, что хотите создать курс **'{course_name}'**?",
            reply_markup=get_course_confirm_keyboard(pending_id=pending_id),
        )

    async def request_course_announcement(self, chat_id: int, course_name: str, announcement_text: str, pending_id: str):
        logger.info(
            "TelegramService.request_course_announcement called: chat_id=%s course_name=%r pending_id=%s",
            chat_id,
            course_name,
            pending_id,
        )
        await self._bot.send_message(
            chat_id=chat_id,
            text=f"Вы уверены, что хотите в курс **'{course_name}'** добавить следующий анонс:\n\n {announcement_text}?",
            reply_markup=get_course_announcement_keyboard(pending_id=pending_id),
        )

    async def request_course_work(
            self,
            chat_id: int,
            pending_id: str,
            title: str,
            course_name: str,
            due_date: str | None = None,
    ):
        deadline_text = f"\n⏰ Дедлайн: <b>{due_date}</b>" if due_date else ""
        msg_text = (
            f"📝 Создать задание в курсе <b>«{course_name}»</b>?\n\n"
            f"Название: <b>{title}</b>"
            f"{deadline_text}"
        )

        await self._bot.send_message(
            chat_id=chat_id,
            text=msg_text,
            reply_markup=get_course_work_keyboard(pending_id=pending_id),
            parse_mode="HTML",
        )
