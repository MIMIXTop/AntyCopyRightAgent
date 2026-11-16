import asyncio
import io
from collections import Counter
from uuid import uuid4

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.methods import EditEphemeralMessageText
from aiogram.types import BufferedInputFile, EphemeralMessageParameters, ReplyParameters

from app.agent.models import DeliveryContext
from app.core.errors import ApplicationError, UnauthorizedError, ValidationError
from app.api.telegram.keyboards import *
from app.core.logging import logger

class TelegramService:

    # Telegram rejects messages longer than 4096 characters; keep a small
    # margin so truncation never lands exactly on the limit.
    TELEGRAM_TEXT_LIMIT = 4000

    def __init__(self, bot: Bot, group_actions_ephemeral: bool = True):
        self._bot = bot
        self._group_actions_ephemeral = group_actions_ephemeral
        self._choices: dict[str, dict] = {}
        logger.info("TelegramService initialized")

    # ---------- delivery helpers ----------

    @staticmethod
    def _ephemeral_parameters(
        delivery: DeliveryContext | None,
        force_ephemeral: bool = False,
    ) -> EphemeralMessageParameters | None:
        """Build ephemeral parameters only for groups where it was requested."""
        if delivery is None or not delivery.is_group:
            return None
        if not (force_ephemeral or delivery.ephemeral):
            return None
        return EphemeralMessageParameters(
            receiver_user_id=delivery.user_id,
            callback_query_id=delivery.callback_query_id,
        )

    async def _call(self, method, *args, **kwargs):
        """Call a Bot API method, honouring the group flood limit once."""
        try:
            return await method(*args, **kwargs)
        except TelegramRetryAfter as error:
            logger.warning(
                "Telegram flood limit hit; retrying in %s seconds: chat_id=%s",
                error.retry_after,
                kwargs.get("chat_id"),
            )
            await asyncio.sleep(error.retry_after)
            return await method(*args, **kwargs)

    async def _send_message_plain(self, **kwargs):
        try:
            await self._call(self._bot.send_message, **kwargs)
        except TelegramBadRequest as error:
            if "can't parse entities" not in str(error).lower():
                raise
            logger.warning(
                "Telegram Markdown parsing failed; retrying message without formatting: chat_id=%s",
                kwargs.get("chat_id"),
            )
            await self._call(
                self._bot.send_message,
                **{key: value for key, value in kwargs.items() if key != "parse_mode"},
                parse_mode=None,
            )

    async def _send_message(
        self,
        *,
        delivery: DeliveryContext | None = None,
        force_ephemeral: bool = False,
        **kwargs,
    ):
        params = self._ephemeral_parameters(delivery, force_ephemeral)
        if params is None:
            await self._send_message_plain(**kwargs)
            return

        ephemeral_kwargs = {**kwargs, "ephemeral_message_parameters": params}
        if delivery.ephemeral_message_id and not delivery.callback_query_id:
            # Replying within 15 s to an incoming ephemeral command works even
            # when the bot is not an administrator.
            ephemeral_kwargs.setdefault(
                "reply_parameters",
                ReplyParameters(ephemeral_message_id=delivery.ephemeral_message_id),
            )
        try:
            await self._send_message_plain(**ephemeral_kwargs)
            return
        except (TelegramBadRequest, TelegramForbiddenError) as error:
            logger.warning(
                "Ephemeral message failed, falling back to DM: chat_id=%s user_id=%s error=%s",
                delivery.chat_id,
                delivery.user_id,
                error,
            )
        await self._deliver_fallback(delivery, kwargs)

    async def _send_request(
        self,
        delivery: DeliveryContext | None,
        **kwargs,
    ) -> None:
        """Confirmation/status messages are always ephemeral in groups."""
        await self._send_message(
            delivery=delivery,
            force_ephemeral=self._group_actions_ephemeral,
            **kwargs,
        )

    @staticmethod
    def _without_ephemeral(kwargs: dict) -> dict:
        cleaned = {
            key: value
            for key, value in kwargs.items()
            if key != "ephemeral_message_parameters"
        }
        reply_parameters = cleaned.get("reply_parameters")
        if getattr(reply_parameters, "ephemeral_message_id", None):
            cleaned.pop("reply_parameters", None)
        return cleaned

    async def _deliver_fallback(self, delivery: DeliveryContext, kwargs: dict) -> None:
        """DM the participant first; only then post publicly in the group."""
        plain_kwargs = self._without_ephemeral(kwargs)
        try:
            await self._send_message_plain(
                **{**plain_kwargs, "chat_id": delivery.user_id}
            )
            return
        except (TelegramBadRequest, TelegramForbiddenError) as error:
            logger.warning(
                "Private fallback failed, posting publicly: user_id=%s error=%s",
                delivery.user_id,
                error,
            )
        await self._send_message_plain(**plain_kwargs)

    async def _send_photo_plain(self, **kwargs):
        try:
            await self._call(self._bot.send_photo, **kwargs)
        except TelegramBadRequest as error:
            if "can't parse entities" not in str(error).lower():
                raise
            logger.warning(
                "Telegram Markdown parsing failed; retrying photo without formatting: chat_id=%s",
                kwargs.get("chat_id"),
            )
            await self._call(
                self._bot.send_photo,
                **{key: value for key, value in kwargs.items() if key != "parse_mode"},
                parse_mode=None,
            )

    async def _send_speech_plain(self, **kwargs):
        await self._call(self._bot.send_voice, **kwargs)

    async def _send_ephemeral_capable(self, plain_sender, *, delivery, force_ephemeral, **kwargs):
        params = self._ephemeral_parameters(delivery, force_ephemeral)
        if params is None:
            await plain_sender(**kwargs)
            return
        ephemeral_kwargs = {**kwargs, "ephemeral_message_parameters": params}
        if delivery.ephemeral_message_id and not delivery.callback_query_id:
            ephemeral_kwargs.setdefault(
                "reply_parameters",
                ReplyParameters(ephemeral_message_id=delivery.ephemeral_message_id),
            )
        try:
            await plain_sender(**ephemeral_kwargs)
            return
        except (TelegramBadRequest, TelegramForbiddenError) as error:
            logger.warning(
                "Ephemeral delivery failed, falling back to DM: chat_id=%s user_id=%s error=%s",
                delivery.chat_id,
                delivery.user_id,
                error,
            )
        plain_kwargs = self._without_ephemeral(kwargs)
        try:
            await plain_sender(**{**plain_kwargs, "chat_id": delivery.user_id})
            return
        except (TelegramBadRequest, TelegramForbiddenError) as error:
            logger.warning(
                "Private fallback failed, posting publicly: user_id=%s error=%s",
                delivery.user_id,
                error,
            )
        await plain_sender(**plain_kwargs)

    async def send_message(
        self,
        text: str,
        chat_id: int,
        delivery: DeliveryContext | None = None,
        reply_markup=None,
    ):
        logger.info("TelegramService.send_message called: chat_id=%s text=%r", chat_id, text)
        await self._send_message(
            delivery=delivery,
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
        )

    async def send_photo(
        self,
        photo: bytes,
        chat_id: int,
        caption: str | None = None,
        filename: str = "image.jpg",
        delivery: DeliveryContext | None = None,
    ):
        logger.info(
            "TelegramService.send_photo called: chat_id=%s bytes=%s caption=%r",
            chat_id,
            len(photo),
            caption,
        )
        input_file = BufferedInputFile(photo, filename=filename)
        await self._send_ephemeral_capable(
            self._send_photo_plain,
            delivery=delivery,
            force_ephemeral=False,
            chat_id=chat_id,
            photo=input_file,
            caption=caption,
        )

    async def send_speech(
        self,
        speech: bytes,
        chat_id: int,
        delivery: DeliveryContext | None = None,
    ):
        logger.info("TelegramService.send_speech called: chat_id=%s bytes=%s", chat_id, len(speech))
        voice = BufferedInputFile(speech, filename="voice.ogg")
        await self._send_ephemeral_capable(
            self._send_speech_plain,
            delivery=delivery,
            force_ephemeral=False,
            voice=voice,
            chat_id=chat_id,
        )

    async def send_error(
        self,
        chat_id: int,
        error: ApplicationError,
        delivery: DeliveryContext | None = None,
    ):
        logger.error("TelegramService.send_error called: chat_id=%s error=%s", chat_id, error)
        if isinstance(error, UnauthorizedError):
            user_id = delivery.user_id if delivery is not None else chat_id
            await self.send_message(
                chat_id=chat_id,
                text=(
                    "Google-доступ истёк или был отозван. "
                    "Подключите Google Classroom заново — нажмите кнопку ниже."
                ),
                delivery=delivery,
                reply_markup=get_auth_keyboard(user_id),
            )
            return
        await self.send_message(
            chat_id=chat_id,
            text=f"Не удалось выполнить запрос: {error}",
            delivery=delivery,
        )

    async def edit_status(
        self,
        call,
        text: str,
        chat_id: int | None = None,
        ephemeral: bool = True,
    ):
        """Edit the message a button belongs to, ephemeral-safe.

        For ephemeral-message buttons ``message.edit_text`` is not available:
        the Bot API requires ``editEphemeralMessageText`` with the receiver id.
        If the callback carries no message at all, send a new ephemeral reply.
        """
        message = call.message
        receiver_id = call.from_user.id

        ephemeral_message_id = getattr(message, "ephemeral_message_id", None)
        if message is not None and ephemeral_message_id:
            try:
                await self._call(
                    self._bot,
                    EditEphemeralMessageText(
                        chat_id=message.chat.id,
                        receiver_user_id=receiver_id,
                        ephemeral_message_id=ephemeral_message_id,
                        text=text,
                    ),
                )
                return
            except (TelegramBadRequest, TelegramForbiddenError) as error:
                logger.warning(
                    "Unable to edit ephemeral message: chat_id=%s error=%s",
                    message.chat.id,
                    error,
                )

        if message is not None:
            try:
                await message.edit_text(text)
                return
            except (TelegramBadRequest, TelegramForbiddenError) as error:
                logger.warning(
                    "Unable to edit callback message: chat_id=%s error=%s",
                    message.chat.id,
                    error,
                )

        target_chat = chat_id or (message.chat.id if message is not None else receiver_id)
        if message is not None:
            chat_type = message.chat.type
        elif target_chat == receiver_id:
            chat_type = "private"
        else:
            chat_type = "group"
        await self.send_message(
            text=text,
            chat_id=target_chat,
            delivery=DeliveryContext(
                chat_id=target_chat,
                user_id=receiver_id,
                chat_type=chat_type,
                ephemeral=ephemeral,
                callback_query_id=call.id,
            ),
        )

    async def get_file_content(self, file_id: str):
        logger.info("TelegramService.get_file_content called: file_id=%s", file_id)

        try:
            tg_file = await self._bot.get_file(file_id)
            file_io = io.BytesIO()
            await self._bot.download_file(tg_file.file_path, destination=file_io)
        except TelegramBadRequest as error:
            # An invented/expired file_id must surface as a structured tool
            # error instead of an unhandled aiogram exception.
            logger.warning(
                "Telegram rejected file_id=%s error=%s",
                file_id,
                error,
            )
            raise ValidationError(
                f"Telegram file_id '{file_id}' is invalid or expired; "
                "use only the file_id values supplied by the runtime for the "
                "attached files, never invent them"
            ) from error
        file_name = tg_file.file_path.split("/")[-1]
        return file_name, file_io.getvalue()

    async def request_course_confirmation(
            self, chat_id: int, course_name: str, pending_id: str,
            delivery: DeliveryContext | None = None,
    ):
        logger.info(
            "TelegramService.request_course_confirmation called: chat_id=%s course_name=%r pending_id=%s",
            chat_id,
            course_name,
            pending_id,
        )
        await self._send_request(
            delivery,
            chat_id=chat_id,
            text=f"Вы уверены, что хотите создать курс *«{course_name}»*?",
            reply_markup=get_course_confirm_keyboard(pending_id=pending_id),
        )

    async def request_course_announcement(
            self, chat_id: int, course_name: str, announcement_text: str, pending_id: str,
            attachment_names: list[str] | None = None,
            attachments_reused: bool = False,
            delivery: DeliveryContext | None = None,
    ):
        logger.info(
            "TelegramService.request_course_announcement called: chat_id=%s course_name=%r pending_id=%s",
            chat_id,
            course_name,
            pending_id,
        )
        text = (
            f"Вы уверены, что хотите в курс *«{course_name}»* "
            f"добавить следующий анонс:\n\n{announcement_text}?"
        )
        text += self._attachments_line(attachment_names, attachments_reused)
        await self._send_request(
            delivery,
            chat_id=chat_id,
            text=self._cap_text(text),
            reply_markup=get_course_announcement_keyboard(pending_id=pending_id),
        )

    @staticmethod
    def _attachments_line(
            attachment_names: list[str] | None,
            attachments_reused: bool = False,
    ) -> str:
        """Show exactly which files will be attached before confirmation."""
        if not attachment_names:
            return "\n\n📎 Вложений нет — файлы не прикрепятся."
        shown = ", ".join(attachment_names[:5])
        hidden = len(attachment_names) - 5
        if hidden > 0:
            shown += f" и ещё {hidden}"
        source = " (из предыдущего сообщения)" if attachments_reused else ""
        return f"\n\n📎 Вложения{source}: {shown}"

    async def request_course_work(
            self,
            chat_id: int,
            pending_id: str,
            title: str,
            course_name: str,
            due_date: str | None = None,
            attachment_names: list[str] | None = None,
            attachments_reused: bool = False,
            delivery: DeliveryContext | None = None,
    ):
        deadline_text = f"\n⏰ Дедлайн: *{due_date}*" if due_date else ""
        msg_text = (
            f"📝 Создать задание в курсе *«{course_name}»*?\n\n"
            f"Название: *{title}*"
            f"{deadline_text}"
        )
        msg_text += self._attachments_line(attachment_names, attachments_reused)

        await self._send_request(
            delivery,
            chat_id=chat_id,
            text=self._cap_text(msg_text),
            reply_markup=get_course_work_keyboard(pending_id=pending_id),
        )

    async def request_course_update(
            self, chat_id: int, pending_id: str, course_name: str, changes: dict,
            delivery: DeliveryContext | None = None,
    ):
        details = "\n".join(
            f"• {key}: {value}"
            for key, value in changes.items() if value is not None
        )
        await self._send_request(
            delivery,
            chat_id=chat_id,
            text=f"Изменить курс *«{course_name}»*?\n\n{details}",
            reply_markup=get_update_course_keyboard(pending_id),
        )

    async def request_announcement_update(
            self, chat_id: int, pending_id: str, changes: dict,
            delivery: DeliveryContext | None = None,
    ):
        details = "\n".join(
            f"• {key}: {value}"
            for key, value in changes.items() if value is not None
        )
        await self._send_request(
            delivery,
            chat_id=chat_id,
            text=f"Изменить анонс?\n\n{details}",
            reply_markup=get_update_announcement_keyboard(pending_id),
        )

    async def request_assignment_update(
            self, chat_id: int, pending_id: str, changes: dict,
            delivery: DeliveryContext | None = None,
    ):
        details = "\n".join(
            f"• {key}: {value}"
            for key, value in changes.items() if value is not None
        )
        await self._send_request(
            delivery,
            chat_id=chat_id,
            text=f"Изменить задание?\n\n{details}",
            reply_markup=get_update_work_keyboard(pending_id),
        )

    async def request_invite_link(
            self, chat_id: int, text: str, url: str,
            delivery: DeliveryContext | None = None,
    ):
        await self._send_request(
            delivery,
            chat_id=chat_id,
            text=text,
            reply_markup=get_invite_url_keyboard(url=url)
        )

    async def request_course_topic_create(
            self, chat_id: int, pending_id: str, topic_name: str,
            delivery: DeliveryContext | None = None,
    ):
        await self._send_request(
            delivery,
            chat_id=chat_id,
            text=f"Вы уверены, что хотите создать раздел *«{topic_name}»*?",
            reply_markup=get_create_course_topic_keyboard(pending_id=pending_id)
        )

    async def request_course_topic_update(
            self, chat_id: int, pending_id: str, changes: dict,
            delivery: DeliveryContext | None = None,
    ):
        details = "\n".join(
            f"• {key}: {value}"
            for key, value in changes.items() if value is not None
        )

        await self._send_request(
            delivery,
            chat_id=chat_id,
            text=f"Изменить раздел?\n\n{details}",
            reply_markup=get_update_course_topic_keyboard(pending_id=pending_id),
        )

    async def request_course_material_create(
            self, chat_id: int, pending_id: str, title: str, description: str,
            materials_payload: list | None = None,
            attachment_names: list[str] | None = None,
            attachments_reused: bool = False,
            delivery: DeliveryContext | None = None,
    ):
        details = (
            f"Название: *{title}*\n"
            f"Описание: {description}"
        )
        if materials_payload:
            details += "\nМатериалы:\n" + "\n".join(
                f"• {material.get('link', {}).get('url') or material.get('driveFile', {}).get('driveFile', {}).get('id', 'вложение')}"
                for material in materials_payload
            )
        details += self._attachments_line(attachment_names, attachments_reused)

        await self._send_request(
            delivery,
            chat_id=chat_id,
            text=self._cap_text(f"Вы уверены, что хотите создать материал курса?\n\n{details}"),
            reply_markup=get_create_course_material_keyboard(pending_id=pending_id)
        )

    async def request_course_material_update(
            self, chat_id: int, pending_id: str, changes: dict,
            delivery: DeliveryContext | None = None,
    ):
        details = "\n".join(
            f"• {key}: {value}"
            for key, value in changes.items() if value is not None
        )

        await self._send_request(
            delivery,
            chat_id=chat_id,
            text=f"Изменить материал курса?\n\n{details}",
            reply_markup=get_update_course_material_keyboard(pending_id=pending_id),
        )

    @classmethod
    def _cap_text(cls, text: str) -> str:
        """Last-resort guard so a single confirmation message never exceeds
        Telegram's 4096-character limit (an overlong message raises
        TelegramBadRequest before the keyboard reaches the user)."""
        if len(text) <= cls.TELEGRAM_TEXT_LIMIT:
            return text
        return text[: cls.TELEGRAM_TEXT_LIMIT - 1] + "…"

    _QUESTION_TYPE_LABELS = {
        "radio": "Выбор одного варианта",
        "checkbox": "Выбор нескольких вариантов",
        "dropdown": "Выпадающий список",
        "short_text": "Короткий ответ",
        "long_text": "Развёрнутый ответ",
    }

    @classmethod
    def _format_question_preview(cls, question: dict) -> str:
        """One compact line per question for the creation confirmation."""
        title = str(question.get("title", ""))
        if len(title) > 120:
            title = title[:119] + "…"
        label = cls._QUESTION_TYPE_LABELS.get(
            question.get("type", ""), question.get("type", "")
        )
        details = [label]
        options = question.get("options") or []
        if options:
            details.append(f"вариантов: {len(options)}")
        if question.get("correct_answers"):
            details.append(f"+{question.get('points') or 1} балл.")
        return f"• {title} — {', '.join(details)}"

    @classmethod
    def _format_question_summary(cls, question: dict) -> str:
        lines = [f"• {question['title']}"]
        question_type = question.get("type", "")
        type_label = cls._QUESTION_TYPE_LABELS.get(question_type, question_type)
        lines.append(f"  Тип: {type_label}")
        options = question.get("options") or []
        if options:
            shown = options[:8]
            suffix = f" …ещё {len(options) - 8}" if len(options) > 8 else ""
            lines.append("  Варианты: " + "; ".join(shown) + suffix)
        correct = question.get("correct_answers") or []
        if correct:
            points = question.get("points") or 1
            lines.append(f"  Верный ответ: {'; '.join(correct)} (+{points} балл.)")
        if question.get("required"):
            lines.append("  Обязательный вопрос")
        return "\n".join(lines)

    async def request_form_creation(
            self,
            chat_id: int,
            pending_id: str,
            title: str,
            description: str,
            is_quiz: bool,
            questions: list[dict],
            publish: bool = False,
            delivery: DeliveryContext | None = None,
    ):
        logger.info(
            "TelegramService.request_form_creation called: chat_id=%s title=%r pending_id=%s",
            chat_id,
            title,
            pending_id,
        )
        form_kind = "тест/викторину" if is_quiz else "форму/опрос"
        # Keep the header bounded: Telegram truncates nothing for us, and a
        # message over 4096 chars is rejected before the keyboard is sent.
        shown_title = str(title)[:200]
        text = f"Создать Google Forms {form_kind} *«{shown_title}»*?"
        if description:
            text += f"\nОписание: {str(description)[:1000]}"
        if is_quiz:
            text += "\n🎯 Режим квиза (с оценками)"
        if publish:
            text += "\n📢 После создания будет запрошено отдельное подтверждение публикации"
        if questions:
            # A full list of 70+ questions overflows Telegram and is unreadable.
            # Show compact statistics and a short preview instead.
            text += f"\n\nВопросов: {len(questions)}"
            counts = Counter(question.get("type", "") for question in questions)
            stats = ", ".join(
                f"{count}× {self._QUESTION_TYPE_LABELS.get(kind, kind)}"
                for kind, count in counts.items()
            )
            if stats:
                text += f" ({stats})"
            total_points = sum(
                question.get("points") or 0
                for question in questions
                if question.get("correct_answers")
            )
            if total_points:
                text += f"\nМаксимум баллов: {total_points}"
            preview = questions[:3]
            text += "\n" + "\n".join(
                self._format_question_preview(question) for question in preview
            )
            hidden = len(questions) - len(preview)
            if hidden:
                text += (
                    f"\n…и ещё {hidden} вопрос(ов) — "
                    "все они будут созданы при подтверждении"
                )

        await self._send_request(
            delivery,
            chat_id=chat_id,
            text=self._cap_text(text),
            reply_markup=get_form_create_keyboard(pending_id=pending_id),
        )

    async def request_form_question(
            self,
            chat_id: int,
            pending_id: str,
            form_title: str,
            question: dict,
            delivery: DeliveryContext | None = None,
    ):
        logger.info(
            "TelegramService.request_form_question called: chat_id=%s form_title=%r pending_id=%s",
            chat_id,
            form_title,
            pending_id,
        )
        text = (
            f"Добавить вопрос в форму *«{form_title}»*?\n\n"
            f"{self._format_question_summary(question)}"
        )
        text = self._cap_text(text)
        await self._send_request(
            delivery,
            chat_id=chat_id,
            text=text,
            reply_markup=get_form_question_keyboard(pending_id=pending_id),
        )

    async def request_form_publish(
            self, chat_id: int, pending_id: str, form_title: str,
            delivery: DeliveryContext | None = None,
    ):
        logger.info(
            "TelegramService.request_form_publish called: chat_id=%s form_title=%r pending_id=%s",
            chat_id,
            form_title,
            pending_id,
        )
        await self._send_request(
            delivery,
            chat_id=chat_id,
            text=self._cap_text(
                f"Опубликовать форму *«{form_title}»* и открыть приём ответов?"
            ),
            reply_markup=get_form_publish_keyboard(pending_id=pending_id),
        )

    async def send_form_link(
            self, chat_id: int, title: str, responder_uri: str,
            delivery: DeliveryContext | None = None,
    ):
        logger.info(
            "TelegramService.send_form_link called: chat_id=%s title=%r",
            chat_id,
            title,
        )
        await self._send_request(
            delivery,
            chat_id=chat_id,
            text=f"Форма *«{title}»* готова:\n{responder_uri}",
            reply_markup=get_form_link_keyboard(url=responder_uri),
        )

    async def request_choice(
        self,
        chat_id: int,
        user_id: int,
        question: str,
        options: list[dict[str, str]],
        delivery: DeliveryContext | None = None,
    ) -> str:
        choice_id = uuid4().hex
        self._choices[choice_id] = {
            "chat_id": chat_id,
            "user_id": user_id,
            "question": question,
            "options": options,
            "delivery": delivery,
            "chat_type": delivery.chat_type if delivery is not None else "private",
        }
        await self._send_message(
            delivery=delivery,
            chat_id=chat_id,
            text=question,
            reply_markup=get_choice_keyboard(choice_id, options),
        )
        return choice_id

    def claim_choice(self, choice_id: str, option_index: int, user_id: int) -> dict | None:
        choice = self._choices.get(choice_id)
        if not choice or choice["user_id"] != user_id:
            return None
        if option_index < 0 or option_index >= len(choice["options"]):
            return None
        self._choices.pop(choice_id, None)
        return {
            **choice,
            "selected": choice["options"][option_index],
            "option_index": option_index,
        }
