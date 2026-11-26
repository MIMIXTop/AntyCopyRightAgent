import io
import re

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message as TgMessage

from app.agent.conversation import is_group_chat
from app.agent.models import DeliveryContext, TelegramAttachment
from app.agent.service import AgentService
from app.agent.voice_service import VoiceService

# from app.classroom.service import ClassroomService
from app.core.errors import ApplicationError
from app.core.logging import logger
from app.api.telegram.keyboards import get_auth_keyboard
from app.api.telegram.forwarding import describe_forward, describe_reply_context
from app.api.telegram.media_groups import MediaGroupBuffer
from app.api.telegram.service import TelegramService


def _mention_regex(bot_username: str | None) -> re.Pattern[str] | None:
    username = (bot_username or "").lstrip("@").lower()
    if not username:
        return None
    return re.compile(rf"@{re.escape(username)}(?![A-Za-z0-9_])", re.IGNORECASE)


def has_bot_mention(message: TgMessage, bot_username: str | None) -> bool:
    pattern = _mention_regex(bot_username)
    if pattern is None:
        return False
    text = message.text or message.caption or ""
    if pattern.search(text):
        return True
    if getattr(message, "ephemeral_message_id", None):
        return True
    username = (bot_username or "").lstrip("@").lower()
    entities = list(message.entities or []) + list(message.caption_entities or [])
    for entity in entities:
        if entity.type != "text_mention" or entity.user is None:
            continue
        if (entity.user.username or "").lower() == username:
            return True
    return False


def is_reply_to_bot(message: TgMessage, bot_username: str | None) -> bool:
    username = (bot_username or "").lstrip("@").lower()
    if not username:
        return False
    replied = message.reply_to_message
    user = getattr(replied, "from_user", None) if replied is not None else None
    if user is None or not user.is_bot:
        return False
    return (user.username or "").lower() == username


def is_addressed(
    message: TgMessage,
    bot_username: str | None,
    allow_reply_to_bot: bool = False,
) -> bool:
    """In groups only an @mention, ephemeral message or reply may wake the agent."""
    if message.from_user is None or message.from_user.is_bot:
        return False
    # Anonymous admins post on behalf of the chat; never act for them.
    if getattr(message, "sender_chat", None) is not None:
        return False
    if not is_group_chat(message.chat.type):
        return True
    if has_bot_mention(message, bot_username):
        return True
    if allow_reply_to_bot and is_reply_to_bot(message, bot_username):
        return True
    return False


def strip_bot_mention(text: str, bot_username: str | None) -> str:
    pattern = _mention_regex(bot_username)
    if pattern is None:
        return text.strip()
    return pattern.sub("", text).strip()


def build_delivery(
    message: TgMessage,
    *,
    group_replies_ephemeral: bool = True,
    ephemeral: bool | None = None,
) -> DeliveryContext:
    in_group = is_group_chat(message.chat.type)
    if ephemeral is None:
        ephemeral = in_group and group_replies_ephemeral
    return DeliveryContext(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        chat_type=message.chat.type,
        ephemeral=bool(ephemeral and in_group),
        ephemeral_message_id=getattr(message, "ephemeral_message_id", None),
        author_name=message.from_user.full_name,
    )


def create_router(
    agent: AgentService,
    bot: Bot,
    voice_service: VoiceService,
    telegram: TelegramService,
    bot_username: str | None = None,
    group_replies_ephemeral: bool = True,
    group_allow_reply_to_bot: bool = False,
) -> Router:
    router = Router()

    def _delivery(message: TgMessage, *, ephemeral: bool | None = None) -> DeliveryContext:
        return build_delivery(
            message,
            group_replies_ephemeral=group_replies_ephemeral,
            ephemeral=ephemeral,
        )

    def _should_handle(message: TgMessage) -> bool:
        return is_addressed(message, bot_username, group_allow_reply_to_bot)

    async def _reply(message: TgMessage, text: str, delivery: DeliveryContext) -> None:
        await telegram.send_message(
            text=text,
            chat_id=message.chat.id,
            delivery=delivery,
        )

    async def _process_media_group(parts: list[TgMessage]) -> None:
        """Handle an entire album as a single agent turn with all attachments."""
        first_message = parts[0]
        # The caption lives on exactly one part of an album, so the address
        # check must use that part instead of blindly trusting parts[0].
        representative = next((part for part in parts if part.caption), first_message)
        if not _should_handle(representative):
            logger.info(
                "Media group ignored: no bot mention chat_id=%s parts=%s",
                first_message.chat.id,
                len(parts),
            )
            return

        attachments: list[TelegramAttachment] = []
        caption: str | None = None

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

        delivery = _delivery(first_message)
        text = strip_bot_mention(caption, bot_username) if caption else ""
        if not text:
            text = f"Пользователь отправил файлы ({len(attachments)} шт.)."
        try:
            answer = await agent.handle(
                chat_id=first_message.chat.id,
                user_id=first_message.from_user.id,
                text=text,
                attachments=attachments,
                delivery=delivery,
                forwarded_from=describe_forward(representative),
                reply_context=describe_reply_context(representative),
            )
        except ApplicationError as error:
            await telegram.send_error(
                first_message.chat.id,
                error,
                delivery=delivery,
            )
            return

        if answer:
            await _reply(first_message, answer, delivery)

    media_groups = MediaGroupBuffer(_process_media_group)

    @router.message(Command("auth"))
    async def auth(message: TgMessage):
        if message.from_user is None or message.from_user.is_bot:
            return
        if is_group_chat(message.chat.type):
            await message.answer(
                "Авторизация доступна только в личном чате с ботом."
            )
            return
        logger.info(
            "Telegram /auth called: chat_id=%s user_id=%s chat_type=%s",
            message.chat.id,
            message.from_user.id,
            message.chat.type,
        )
        await message.answer(
            (
            "Для доступа к вашим курсам и работам в Google Classroom необходимо авторизоваться:\n\n"
            "Нажмите кнопку ниже, разрешите доступ в Google, после чего возвращайтесь в чат."
            ),
            reply_markup=get_auth_keyboard(message.from_user.id),
        )

    @router.message(Command("ask"))
    async def ask(message: TgMessage, command: CommandObject):
        if message.from_user is None or message.from_user.is_bot:
            return
        # /ask is the fully private path: both the question and the answer are
        # ephemeral, even if group replies are configured as public.
        delivery = _delivery(message, ephemeral=is_group_chat(message.chat.type))
        question = (command.args or "").strip()
        if not question:
            await _reply(message, "Напишите вопрос после команды: /ask@бот ваш вопрос", delivery)
            return

        logger.info(
            "Telegram /ask called: chat_id=%s user_id=%s text=%r",
            message.chat.id,
            message.from_user.id,
            question,
        )
        try:
            answer = await agent.handle(
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                text=question,
                delivery=delivery,
                forwarded_from=describe_forward(message),
                reply_context=describe_reply_context(message),
            )
        except ApplicationError as error:
            await telegram.send_error(message.chat.id, error, delivery=delivery)
            return
        if answer:
            await _reply(message, answer, delivery)

    @router.message(Command("reset"))
    async def reset(message: TgMessage):
        if message.from_user is None or message.from_user.is_bot:
            return
        delivery = _delivery(message, ephemeral=is_group_chat(message.chat.type))
        await agent.reset(
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            chat_type=message.chat.type,
        )
        await _reply(message, "Контекст диалога очищен.", delivery)

    @router.message(F.voice)
    async def handle_voice_message(message: TgMessage):
        if message.from_user is None or message.voice is None:
            return
        # There is no caption on a voice message, so in groups a voice can only
        # be addressed with the reply-to-bot mode or an ephemeral command.
        if is_group_chat(message.chat.type) and not (
            getattr(message, "ephemeral_message_id", None)
            or (group_allow_reply_to_bot and is_reply_to_bot(message, bot_username))
        ):
            logger.info(
                "Voice ignored in group without mention: chat_id=%s",
                message.chat.id,
            )
            return

        delivery = _delivery(message)
        voice = message.voice

        voice_io = io.BytesIO()
        await bot.download(voice, voice_io)
        voice_bytes = voice_io.getvalue()

        text = await voice_service.transcription_voice(voice_bytes)
        logger.info(f"Распознанный голос от {message.from_user.id}: {text!r}")

        answer = await agent.handle(
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            text=text,
            delivery=delivery,
            forwarded_from=describe_forward(message),
            reply_context=describe_reply_context(message),
        )
        if answer:
            await _reply(message, answer, delivery)

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
        # Unknown commands must never reach the model as regular text.
        if message.text.startswith("/"):
            return
        if not _should_handle(message):
            logger.info(
                "Group message ignored: no mention chat_id=%s user_id=%s text=%r",
                message.chat.id,
                message.from_user.id,
                message.text,
            )
            return

        text = strip_bot_mention(message.text, bot_username)
        delivery = _delivery(message)
        logger.info(
            "Telegram message received: chat_id=%s user_id=%s chat_type=%s text=%r",
            message.chat.id,
            message.from_user.id,
            message.chat.type,
            text,
        )

        if not text:
            await _reply(
                message,
                "Напишите вопрос после упоминания, например: @бот создай курс",
                delivery,
            )
            return

        try:
            answer = await agent.handle(
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                text=text,
                delivery=delivery,
                forwarded_from=describe_forward(message),
                reply_context=describe_reply_context(message),
            )
        except ApplicationError as error:
            await telegram.send_error(message.chat.id, error, delivery=delivery)
            return

        if answer:
            logger.info(
                "Telegram answer sent: chat_id=%s user_id=%s text=%r",
                message.chat.id,
                message.from_user.id,
                answer,
            )
            await _reply(message, answer, delivery)

    @router.message(F.photo)
    async def handle_photo_message(message: TgMessage):
        if message.from_user is None or not message.photo:
            return
        if message.media_group_id:
            # Handled by handle_media_group above.
            return
        await media_groups.add(message)

    return router
