import asyncio
import json
from collections.abc import Awaitable, Callable, Hashable

from app.agent.attachment_memory import AttachmentMemory
from app.agent.conversation import conversation_key
from app.agent.models import (
    DeliveryContext,
    Message,
    TelegramAttachment,
    ToolContext,
    ToolResult,
)
from app.agent.tool_policy import GROUP_SAFE_TOOLS
from app.core.errors import ApplicationError, AgentIterationLimitError
from app.core.logging import logger
from app.core.types import HistoryStore, LLMClient
from app.agent.tools import ToolRegistry


class AgentService:
    EMPTY_RESPONSE_MESSAGE = (
        "Не удалось получить содержательный ответ от AI. "
        "Попробуйте повторить запрос немного позже."
    )
    # How many times a finish without a preceding create_form is rejected
    # before the run gives up with FORM_FALLBACK_MESSAGE instead of burning
    # every iteration on the same rejection.
    MAX_PREMATURE_FINISH_BLOCKS = 2
    FORM_FALLBACK_MESSAGE = (
        "⚠️ Не удалось запустить создание формы: ассистент не передал "
        "параметры теста в инструмент создания. Напишите, пожалуйста, "
        "«создай форму» ещё раз — попробуем снова."
    )

    def __init__(
        self,
        llm: LLMClient,
        history: HistoryStore,
        tools: ToolRegistry,
        max_iterations: int = 10,
        role_resolver: Callable[[int], Awaitable[str]] | None = None,
        group_safe_mode: bool = True,
        attachment_ttl_seconds: float = 1800,
    ):
        self._llm = llm
        self._history = history
        self._tools = tools
        self._max_iterations = max_iterations
        self._role_resolver = role_resolver
        self._group_safe_mode = group_safe_mode
        self._attachments = AttachmentMemory(ttl_seconds=attachment_ttl_seconds)
        # Agent runs for the same conversation must never interleave: the
        # history store is shared and each loop reads it on every iteration.
        # Without this lock, an album of 4 files (or two rapid messages) drives
        # several parallel loops that scramble the conversation and race on
        # tool calls. In groups the key is (chat_id, user_id), so one member's
        # long run never blocks another member.
        self._chat_locks: dict[Hashable, asyncio.Lock] = {}

    def _lock_for(self, conversation_id: Hashable) -> asyncio.Lock:
        lock = self._chat_locks.get(conversation_id)
        if lock is None:
            lock = asyncio.Lock()
            self._chat_locks[conversation_id] = lock
        return lock

    @staticmethod
    def _is_confirmation(text: str | None) -> bool:
        if not text:
            return False
        normalized = text.strip().lower().replace("ё", "е")
        return normalized in {
            "да",
            "да делай",
            "делай",
            "создавай",
            "сделай",
            "сделай форму",
            "создавай форму",
        }

    @classmethod
    def _has_draft_before_confirmation(cls, messages: list[Message]) -> bool:
        if not messages or messages[-1].role != "user":
            return False
        if not cls._is_confirmation(messages[-1].content if isinstance(messages[-1].content, str) else None):
            return False

        return any(
            call.name == "send_message"
            for message in messages[:-1]
            if message.role == "assistant"
            for call in (message.tool_calls or [])
        )

    async def handel_voice(self, voice: bytes):
        res = await self._llm.transcription_voice(voice_bytes=voice)
        return res


    async def handle(
        self,
        chat_id: int,
        user_id: int,
        text: str,
        attachments: list[TelegramAttachment] | None = None,
        delivery: DeliveryContext | None = None,
        forwarded_from: str | None = None,
        reply_context: str | None = None,
    ) -> str:
        delivery = delivery or DeliveryContext(chat_id=chat_id, user_id=user_id)
        conversation_id = conversation_key(delivery.chat_type, chat_id, user_id)
        logger.info(
            "Agent.handle called: conversation=%s chat_id=%s user_id=%s chat_type=%s "
            "ephemeral=%s text=%r attachments=%s forwarded_from=%r reply_context=%s",
            conversation_id,
            chat_id,
            user_id,
            delivery.chat_type,
            delivery.use_ephemeral,
            text,
            attachments or [],
            forwarded_from,
            bool(reply_context),
        )
        async with self._lock_for(conversation_id):
            role = await self._resolve_role(user_id)
            # A text-only message starts a new intent, so attachments from the
            # previous one must not leak into it. A media message replaces the
            # remembered set.
            if attachments:
                self._attachments.remember(conversation_id, attachments)
            else:
                self._attachments.forget(conversation_id)
            await self._history.append(
                conversation_id,
                Message(
                    "user",
                    content=text,
                    attachments=attachments or [],
                    forwarded_from=forwarded_from,
                    reply_context=reply_context,
                ),
            )
            return await self._run_loop(
                conversation_id,
                chat_id,
                user_id,
                attachments or [],
                role,
                delivery,
            )

    async def resume_after_action(
        self,
        chat_id: int,
        user_id: int,
        event: dict,
        delivery: DeliveryContext | None = None,
    ) -> str:
        """Resume the agent after an external confirmation callback."""
        delivery = delivery or DeliveryContext(chat_id=chat_id, user_id=user_id)
        conversation_id = conversation_key(delivery.chat_type, chat_id, user_id)
        async with self._lock_for(conversation_id):
            role = await self._resolve_role(user_id)
            # Button presses carry no media: reuse the files from the user's
            # latest media message so a confirmed announcement/assignment keeps
            # the picture the teacher attached a minute ago.
            attachments = self._attachments.recent(conversation_id)
            if attachments:
                logger.info(
                    "Reusing remembered attachments: conversation=%s count=%s",
                    conversation_id,
                    len(attachments),
                )
            await self._history.append(
                conversation_id,
                Message(
                    "system",
                    json.dumps(event, ensure_ascii=False),
                ),
            )
            return await self._run_loop(
                conversation_id,
                chat_id,
                user_id,
                attachments,
                role,
                delivery,
                attachments_reused=bool(attachments),
            )

    async def reset(
        self,
        chat_id: int,
        user_id: int,
        chat_type: str = "private",
    ) -> None:
        """Drop the conversation context of one participant (``/reset``)."""
        await self._history.clear(conversation_key(chat_type, chat_id, user_id))

    async def _resolve_role(self, user_id: int) -> str:
        if self._role_resolver is None:
            return "teacher"
        try:
            role = (await self._role_resolver(user_id)).lower()
        except Exception:
            logger.exception("Unable to resolve user role: user_id=%s", user_id)
            return "teacher"
        return role if role in {"teacher", "admin"} else "teacher"

    async def _run_loop(
        self,
        conversation_id: Hashable,
        chat_id: int,
        user_id: int,
        attachments: list[TelegramAttachment],
        role: str,
        delivery: DeliveryContext,
        attachments_reused: bool = False,
    ) -> str:
        initial_history = await self._history.get(conversation_id)
        confirmed_draft = self._has_draft_before_confirmation(initial_history)
        # Whether create_form succeeded at any point of THIS run (not just in
        # the current response): after a successful create_form the model must
        # be able to call finish in a later iteration to wait for the
        # confirmation keyboard's action_result event.
        form_creation_requested = False
        premature_finish_blocks = 0
        # In groups only the conversation-safe toolset is exposed. Private
        # chats keep the full classroom/drive/sheets/forms toolset.
        allowed_tools = (
            GROUP_SAFE_TOOLS
            if delivery.is_group and self._group_safe_mode
            else None
        )
        if allowed_tools is not None:
            logger.info(
                "Group tool policy active: chat_id=%s allowed=%s",
                chat_id,
                sorted(allowed_tools),
            )
        for iteration in range(self._max_iterations):
            logger.info("Agent iteration started: chat_id=%s iteration=%s", chat_id, iteration + 1)
            role_message = Message(
                "system",
                self._role_prompt(role, delivery),
            )
            response = await self._llm.complete(
                messages=[role_message, *(await self._history.get(conversation_id))],
                tools=self._tools.schemas(allowed=allowed_tools),
            )

            if not response.tool_calls:
                if not response.text.strip():
                    logger.warning(
                        "LLM returned an empty response: chat_id=%s iteration=%s "
                        "finish_reason=%s refusal=%r",
                        chat_id,
                        iteration + 1,
                        response.finish_reason,
                        response.refusal,
                    )
                    response_text = self.EMPTY_RESPONSE_MESSAGE
                else:
                    response_text = response.text

                logger.info("Agent completed with text: chat_id=%s text=%r", chat_id, response_text)
                await self._history.append(conversation_id,
                    Message("assistant", response_text),
                )
                return response_text

            await self._history.append(conversation_id,
                Message(
                    "assistant",
                    response.text or None,
                    tool_calls=response.tool_calls,
                ),
            )
            for call in response.tool_calls:
                try:
                    arguments = json.loads(call.arguments)
                except json.JSONDecodeError as error:
                    result = ToolResult(
                        call_id=call.id,
                        content=json.dumps({
                            "status": "error",
                            "error_type": "ToolArgumentsError",
                            "message": "Аргументы инструмента имеют некорректный JSON.",
                        }, ensure_ascii=False),
                    )
                    logger.warning(
                        "Invalid JSON tool arguments: chat_id=%s tool=%s error=%s",
                        chat_id,
                        call.name,
                        error,
                    )
                    await self._history.append(conversation_id,
                        Message("tool", result.content, call.id),
                    )
                    continue
                if not isinstance(arguments, dict):
                    result = ToolResult(
                        call_id=call.id,
                        content=json.dumps({
                            "status": "error",
                            "error_type": "ToolArgumentsError",
                            "message": "Аргументы инструмента должны быть JSON-объектом.",
                        }, ensure_ascii=False),
                    )
                    await self._history.append(conversation_id,
                        Message("tool", result.content, call.id),
                    )
                    continue

                logger.info(f"arguments: {arguments}")
                logger.info(
                    "Agent tool call: chat_id=%s tool=%s call_id=%s arguments=%s",
                    chat_id,
                    call.name,
                    call.id,
                    arguments,
                )

                try:
                    result = await self._tools.call(
                        call.name,
                        ToolContext(
                            chat_id,
                            user_id,
                            call.id,
                            attachments or [],
                            role,
                            delivery,
                            attachments_reused=attachments_reused,
                        ),
                        arguments,
                        allowed=allowed_tools,
                    )
                except ApplicationError as error:
                    logger.warning(
                        "Agent tool failed: chat_id=%s tool=%s error_type=%s error=%s",
                        chat_id,
                        call.name,
                        type(error).__name__,
                        error,
                    )
                    result = ToolResult(
                        call_id=call.id,
                        content=json.dumps(
                            {
                                "status": "error",
                                "error_type": type(error).__name__,
                                "message": str(error),
                            },
                            ensure_ascii=False,
                        ),
                    )
                except Exception:
                    logger.exception(
                        "Unexpected agent tool failure: chat_id=%s tool=%s",
                        chat_id,
                        call.name,
                    )
                    result = ToolResult(
                        call_id=call.id,
                        content=json.dumps(
                            {
                                "status": "error",
                                "error_type": "UnexpectedToolError",
                                "message": "Инструмент завершился с внутренней ошибкой. "
                                "Не сообщай технические детали пользователю.",
                            },
                            ensure_ascii=False,
                        ),
                    )

                if call.name == "create_form":
                    try:
                        form_payload = json.loads(result.content)
                    except (TypeError, json.JSONDecodeError):
                        form_payload = {}
                    if isinstance(form_payload, dict) and form_payload.get("status") == "paused":
                        # create_form succeeded anywhere in this run: the
                        # confirmation keyboard is already on its way, so the
                        # model may now finish and wait for action_result.
                        form_creation_requested = True

                if (
                    call.name == "finish"
                    and confirmed_draft
                    and not form_creation_requested
                ):
                    premature_finish_blocks += 1
                    if premature_finish_blocks <= self.MAX_PREMATURE_FINISH_BLOCKS:
                        result = ToolResult(
                            call_id=call.id,
                            content=json.dumps(
                                {
                                    "status": "error",
                                    "error_type": "IncompleteFormCreation",
                                    "message": (
                                        "Подтверждён ранее подготовленный тест. "
                                        "Немедленно вызови create_form с полным списком "
                                        "вопросов из черновика (title и все questions), "
                                        "затем дождись подтверждения формы. "
                                        "finish отклоняется, пока create_form не вызван."
                                    ),
                                },
                                ensure_ascii=False,
                            ),
                        )
                        await self._history.append(conversation_id,
                            Message("tool", result.content, call.id),
                        )
                        logger.warning(
                            "Blocked premature finish after confirmed form draft: "
                            "chat_id=%s call_id=%s attempt=%s/%s",
                            chat_id,
                            call.id,
                            premature_finish_blocks,
                            self.MAX_PREMATURE_FINISH_BLOCKS,
                        )
                        continue
                    # The model keeps ignoring the rejection; stop wasting
                    # iterations and tell the teacher honestly instead of
                    # ending with a generic empty-response error.
                    logger.warning(
                        "Giving up on create_form after repeated premature finish: "
                        "chat_id=%s call_id=%s blocks=%s",
                        chat_id,
                        call.id,
                        premature_finish_blocks,
                    )
                    await self._history.append(conversation_id,
                        Message("assistant", self.FORM_FALLBACK_MESSAGE),
                    )
                    return self.FORM_FALLBACK_MESSAGE
                await self._history.append(conversation_id,
                    Message("tool", result.content, call.id)
                )
                # Only the explicit finish tool may end the agent loop. Other
                # tools can return status data such as a pending confirmation
                # and the model must decide whether more actions are needed.
                if result.terminal and call.name in {"finish", "ask_choice"}:
                    logger.info(
                        "Agent tool terminated flow: chat_id=%s tool=%s call_id=%s",
                        chat_id,
                        call.name,
                        call.id,
                    )
                    return ""

        logger.error("Agent iteration limit reached: chat_id=%s limit=%s", chat_id, self._max_iterations)
        raise AgentIterationLimitError(self._max_iterations)

    @staticmethod
    def _role_prompt(role: str, delivery: DeliveryContext | None = None) -> str:
        if role == "teacher":
            prompt = (
                "Текущий пользователь имеет роль TEACHER. Он может работать со своими "
                "курсами, заданиями, объявлениями и студентами, но не имеет доступа к "
                "административному dashboard."
            )
        else:
            prompt = (
                "Текущий пользователь имеет роль ADMIN. Разрешены административные операции "
                "и dashboard, но Google Classroom действия всё равно выполняй только по "
                "явному запросу и с точными идентификаторами."
            )
        if delivery is not None and delivery.is_group:
            speaker = delivery.author_name or "участник группы"
            prompt += (
                f"\n\nТы работаешь в групповом чате Telegram. Сейчас к тебе обращается "
                f"{speaker}. Отвечай именно ему и не выполняй действия от имени других "
                "участников. Не раскрывай данные других людей. Твои ответы в группе могут "
                "быть видны только автору запроса — не проси переслать их остальным."
                "\n\nВ группе тебе доступны только общение, вопросы, поиск информации и "
                "ссылок, картинки и голос. Инструменты курсов, Google Drive, Sheets, Forms "
                "и просмотра документов здесь недоступны. Если просят такое действие, "
                "коротко скажи, что его нужно выполнить в личном чате с ботом. Никогда не "
                "утверждай, что действие с курсом, таблицей или формой выполнено."
            )
        return prompt
