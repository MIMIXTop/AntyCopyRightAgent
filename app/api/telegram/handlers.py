import io

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import Message as TgMessage

from app.agent.models import TelegramAttachment
from app.agent.service import AgentService
from app.agent.voice_service import VoiceService

# from app.classroom.service import ClassroomService
from app.core.errors import ApplicationError
from app.core.logging import logger
from app.api.telegram.keyboards import get_auth_keyboard
from app.api.telegram.media_groups import MediaGroupBuffer


def create_router(
    agent: AgentService, bot: Bot, voice_service: VoiceService, error_presenter
) -> Router:
    router = Router()

    async def _process_media_group(parts: list[TgMessage]) -> None:
        """Handle an entire album as a single agent turn with all attachments."""
        attachments: list[TelegramAttachment] = []
        caption: str | None = None
        first_message = parts[0]

        for part in parts:
            if caption is None and part.caption:
                caption = part.caption
            if part.from_user is None:
                continue
            if part.document is not None:
                document_io = io.BytesIO()
                await bot.download(part.document, document_io)
                attachments.append(
                    TelegramAttachment(
                        file_id=part.document.file_id,
                        file_name=part.document.file_name,
                        mime_type=part.document.mime_type,
                        size=part.document.file_size,
                        data=document_io.getvalue(),
                    )
                )
            elif part.photo:
                photo = part.photo[-1]
                photo_io = io.BytesIO()
                await bot.download(photo, photo_io)
                attachments.append(
                    TelegramAttachment(
                        file_id=photo.file_id,
                        file_name=f"photo_{photo.file_unique_id}.jpg",
                        mime_type="image/jpeg",
                        size=photo.file_size,
                        kind="photo",
                        data=photo_io.getvalue(),
                    )
                )

        if not attachments or first_message.from_user is None:
            logger.info(
                "Media group skipped: no processable attachments parts=%s",
                len(parts),
            )
            return

        text = caption or f"Пользователь отправил файлы ({len(attachments)} шт.)."
        try:
            answer = await agent.handle(
                chat_id=first_message.chat.id,
                user_id=first_message.from_user.id,
                text=text,
                attachments=attachments,
            )
        except ApplicationError as error:
            await error_presenter.send_error(first_message.chat.id, error)
            return

        if answer:
            await first_message.answer(answer)

    media_groups = MediaGroupBuffer(_process_media_group)

    @router.message(Command("auth"))
    async def auth(message: TgMessage):
        logger.info(
            "Telegram /auth called: chat_id=%s user_id=%s",
            message.chat.id,
            message.from_user.id,
        )
        await message.answer(
            "Для доступа к вашим курсам и работам в Google Classroom необходимо авторизоваться:\n\n"
            "Нажмите кнопку ниже, разрешите доступ в Google, после чего возвращайтесь в чат.",
            reply_markup=get_auth_keyboard(message.from_user.id),
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

        answer = await agent.handle(
            chat_id=message.chat.id, user_id=message.from_user.id, text=text
        )
        if answer:
            await message.answer(answer)

    # Registered before the single-document/photo handlers so every album part
    # (each part carries media_group_id) is consumed here and processed as one
    # batch instead of spawning a parallel agent run per file.
    @router.message(F.media_group_id)
    async def handle_media_group(message: TgMessage):
        if message.from_user is None:
            return
        if message.document is None and not message.photo:
            return
        await media_groups.add(message)

    @router.message(F.document)
    async def handle_document_message(message: TgMessage):
        if message.from_user is None or message.document is None:
            return
        if message.media_group_id:
            # Handled by handle_media_group above.
            return
        # Some Telegram clients send selected documents as separate updates
        # without media_group_id. Debounce them into one agent turn as well.
        await media_groups.add(message)

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
            logger.info(
                "Telegram answer sent: chat_id=%s text=%r", message.chat.id, answer
            )
            await message.answer(answer)

    @router.message(F.photo)
    async def handle_photo_message(message: TgMessage):
        if message.from_user is None or not message.photo:
            return
        if message.media_group_id:
            # Handled by handle_media_group above.
            return
        await media_groups.add(message)

    return router
