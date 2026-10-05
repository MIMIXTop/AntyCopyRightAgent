import io

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message as TgMessage

from app.agent.service import AgentService
from app.agent.models import TelegramAttachment
from app.agent.voice_service import VoiceService
from app.classroom.service import ClassroomService
from app.core.errors import ApplicationError
from app.telegram.keyboards import get_auth_keyboard
from app.core.logging import logger


def create_router(agent: AgentService, bot: Bot, voice_service: VoiceService, error_presenter) -> Router:
    router = Router()

    @router.message(Command("auth"))
    async def auth(message: TgMessage):
        logger.info("Telegram /auth called: chat_id=%s user_id=%s", message.chat.id, message.from_user.id)
        await message.answer(
            "Для доступа к вашим курсам и работам в Google Classroom необходимо авторизоваться:\n\n"
            "Нажмите кнопку ниже, разрешите доступ в Google, после чего возвращайтесь в чат.",
            reply_markup=get_auth_keyboard(message.from_user.id)
        )

    @router.message(F.voice)
    async def handle_voice_message(message: TgMessage):
        if message.from_user is None or message.voice is None:
            return

        voice = message.voice

        voice_io = io.BytesIO()
        await bot.download(voice, voice_io)
        voice_bytes = voice_io.getvalue()

        text = await voice_service.transcription_voice(voice_bytes)
        logger.info(f"Распознанный голос от {message.from_user.id}: {text!r}")

        answer = await agent.handle(chat_id=message.chat.id, user_id=message.from_user.id, text=text)
        if answer:
            await message.answer(answer)



    @router.message(F.document)
    async def handle_document_message(message: TgMessage):
        if message.from_user is None or message.document is None:
            return

        doc = message.document
        caption = message.caption or "Пользователь отправил файл."

        text_for_agent = (
            caption
        )

        try:
            answer = await agent.handle(
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                text=text_for_agent,
                attachments=[
                    TelegramAttachment(
                        file_id=doc.file_id,
                        file_name=doc.file_name,
                        mime_type=doc.mime_type,
                        size=doc.file_size,
                    )
                ],
            )
        except ApplicationError as error:
            await error_presenter.send_error(message.chat.id, error)
            return

        if answer:
            await message.answer(answer)

    @router.message(F.text)
    async def handle_message(message: TgMessage) -> None:
        if message.from_user is None or message.text is None:
            return
        logger.info(
            "Telegram message received: chat_id=%s user_id=%s text=%r",
            message.chat.id,
            message.from_user.id,
            message.text,
        )

        try:
            answer = await agent.handle(
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                text=message.text,
            )
        except ApplicationError as error:
            await error_presenter.send_error(message.chat.id, error)
            return

        if answer:
            logger.info("Telegram answer sent: chat_id=%s text=%r", message.chat.id, answer)
            await message.answer(answer)

    @router.message(F.photo)
    async def handle_photo_message(message: TgMessage):
        if message.from_user is None or not message.photo:
            return

        photo = message.photo[-1]

        attachment = TelegramAttachment(
            file_id=photo.file_id,
            file_name=f"photo_{photo.file_unique_id}.jpg",
            mime_type="image/jpeg",
            size=photo.file_size,
            kind="photo",
        )

        try:
            answer = await agent.handle(
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                text=message.caption or "Пользователь отправил фотографию.",
                attachments=[attachment],
            )
        except ApplicationError as error:
            await error_presenter.send_error(message.chat.id, error)
            return

        if answer:
            await message.answer(answer)

    return router
