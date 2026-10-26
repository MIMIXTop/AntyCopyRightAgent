import io

from aiogram import Bot
from aiogram.types import BufferedInputFile

from app.core.errors import ApplicationError
from app.api.telegram.keyboards import *
from app.core.logging import logger

class TelegramService:

    def __init__(self, bot: Bot):
        self._bot = bot
        logger.info("TelegramService initialized")

    async def send_message(self, text: str, chat_id: int):
        logger.info("TelegramService.send_message called: chat_id=%s text=%r", chat_id, text)
        await self._bot.send_message(
            chat_id=chat_id,
            text=text,
        )

    async def send_speech(self, speech: bytes, chat_id: int):
        logger.info("TelegramService.send_speech called: chat_id=%s bytes=%s", chat_id, len(speech))
        voice = BufferedInputFile(speech, filename="voice.ogg")
        await self._bot.send_voice(voice=voice, chat_id=chat_id)

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
            text=f"Вы уверены, что хотите создать курс *«{course_name}»*?",
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
            text=(
                f"Вы уверены, что хотите в курс *«{course_name}»* "
                f"добавить следующий анонс:\n\n{announcement_text}?"
            ),
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
        deadline_text = f"\n⏰ Дедлайн: *{due_date}*" if due_date else ""
        msg_text = (
            f"📝 Создать задание в курсе *«{course_name}»*?\n\n"
            f"Название: *{title}*"
            f"{deadline_text}"
        )

        await self._bot.send_message(
            chat_id=chat_id,
            text=msg_text,
            reply_markup=get_course_work_keyboard(pending_id=pending_id),
        )

    async def request_course_update(self, chat_id: int, pending_id: str, course_name: str, changes: dict):
        details = "\n".join(
            f"• {key}: {value}"
            for key, value in changes.items() if value is not None
        )
        await self._bot.send_message(
            chat_id=chat_id,
            text=f"Изменить курс *«{course_name}»*?\n\n{details}",
            reply_markup=get_update_course_keyboard(pending_id),
        )

    async def request_announcement_update(self, chat_id: int, pending_id: str, changes: dict):
        details = "\n".join(
            f"• {key}: {value}"
            for key, value in changes.items() if value is not None
        )
        await self._bot.send_message(
            chat_id=chat_id,
            text=f"Изменить анонс?\n\n{details}",
            reply_markup=get_update_announcement_keyboard(pending_id),
        )

    async def request_assignment_update(self, chat_id: int, pending_id: str, changes: dict):
        details = "\n".join(
            f"• {key}: {value}"
            for key, value in changes.items() if value is not None
        )
        await self._bot.send_message(
            chat_id=chat_id,
            text=f"Изменить задание?\n\n{details}",
            reply_markup=get_update_work_keyboard(pending_id),
        )

    async def request_invite_link(self, chat_id: int, text: str, url: str):
        await self._bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=get_invite_url_keyboard(url=url)
        )

    async def request_course_topic_create(self, chat_id: int, pending_id: str,topic_name: str):
        await self._bot.send_message(
            chat_id=chat_id,
            text=f"Вы уверены, что хотите создать раздел *«{topic_name}»*?",
            reply_markup=get_create_course_topic_keyboard(pending_id=pending_id)
        )

    async def request_course_topic_update(self, chat_id: int, pending_id: str, changes: dict):
        details = "\n".join(
            f"• {key}: {value}"
            for key, value in changes.items() if value is not None
        )

        await self._bot.send_message(
            chat_id=chat_id,
            text=f"Изменить раздел?\n\n{details}",
            reply_markup=get_update_course_topic_keyboard(pending_id=pending_id),
        )

    async def request_course_material_create(self, chat_id: int, pending_id: str, title: str, description: str, materials_payload: list | None = None):
        details = (
            f"Название: *{title}*\n"
            f"Описание: {description}"
        )
        if materials_payload:
            details += "\nМатериалы:\n" + "\n".join(
                f"• {material.get('link', {}).get('url') or material.get('driveFile', {}).get('driveFile', {}).get('id', 'вложение')}"
                for material in materials_payload
            )

        await self._bot.send_message(
            chat_id=chat_id,
            text=f"Вы уверены, что хотите создать материал курса?\n\n{details}",
            reply_markup=get_create_course_material_keyboard(pending_id=pending_id)
        )

    async def request_course_material_update(self, chat_id: int, pending_id: str, changes: dict):
        details = "\n".join(
            f"• {key}: {value}"
            for key, value in changes.items() if value is not None
        )

        await self._bot.send_message(
            chat_id=chat_id,
            text=f"Изменить материал курса?\n\n{details}",
            reply_markup=get_update_course_material_keyboard(pending_id=pending_id),
        )
