import asyncio
import json

from app.agent.models import Message, ToolContext, TelegramAttachment, ToolResult
from app.core.errors import ApplicationError, AgentIterationLimitError
from app.core.logging import logger
from app.core.types import HistoryStore, LLMClient
from app.agent.tools import ToolRegistry


class AgentService:
    EMPTY_RESPONSE_MESSAGE = (
        "Не удалось получить содержательный ответ от AI. "
        "Попробуйте повторить запрос немного позже."
    )

    def __init__(self, llm: LLMClient, history: HistoryStore, tools: ToolRegistry, max_iterations: int = 10):
        self._llm = llm
        self._history = history
        self._tools = tools
        self._max_iterations = max_iterations
        # Agent runs for the same chat must never interleave: the history store
        # is shared and each loop reads it on every iteration. Without this
        # lock, an album of 4 files (or two rapid messages) drives several
        # parallel loops that scramble the conversation and race on tool calls.
        self._chat_locks: dict[int, asyncio.Lock] = {}

    def _lock_for(self, chat_id: int) -> asyncio.Lock:
        lock = self._chat_locks.get(chat_id)
        if lock is None:
            lock = asyncio.Lock()
            self._chat_locks[chat_id] = lock
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
    ) -> str:
        logger.info(
            "Agent.handle called: chat_id=%s user_id=%s text=%r attachments=%s",
            chat_id,
            user_id,
            text,
            attachments or [],
        )
        async with self._lock_for(chat_id):
            await self._history.append(
                chat_id,
                Message("user", content=text, attachments=attachments or []),
            )
            return await self._run_loop(chat_id, user_id, attachments or [])

    async def resume_after_action(
        self,
        chat_id: int,
        user_id: int,
        event: dict,
    ) -> str:
        """Resume the agent after an external confirmation callback."""
        async with self._lock_for(chat_id):
            await self._history.append(
                chat_id,
                Message(
                    "system",
                    json.dumps(event, ensure_ascii=False),
                ),
            )
            return await self._run_loop(chat_id, user_id, [])

    async def _run_loop(
        self,
        chat_id: int,
        user_id: int,
        attachments: list[TelegramAttachment],
    ) -> str:
        initial_history = await self._history.get(chat_id)
        confirmed_draft = self._has_draft_before_confirmation(initial_history)
        for iteration in range(self._max_iterations):
            logger.info("Agent iteration started: chat_id=%s iteration=%s", chat_id, iteration + 1)
            history = await self._history.get(chat_id)
            response = await self._llm.complete(
                messages=history,
                tools=self._tools.schemas(),
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
                await self._history.append(
                    chat_id,
                    Message("assistant", response_text),
                )
                return response_text

            await self._history.append(
                chat_id,
                Message(
                    "assistant",
                    response.text or None,
                    tool_calls=response.tool_calls,
                ),
            )
            has_form_creation_call = any(call.name == "create_form" for call in response.tool_calls)
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
                    await self._history.append(
                        chat_id,
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
                    await self._history.append(
                        chat_id,
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
                        ToolContext(chat_id, user_id, call.id, attachments or []),
                        arguments,
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

                if (
                    call.name == "finish"
                    and confirmed_draft
                    and not has_form_creation_call
                ):
                    result = ToolResult(
                        call_id=call.id,
                        content=json.dumps(
                            {
                                "status": "error",
                                "error_type": "IncompleteFormCreation",
                                "message": (
                                    "Подтверждён ранее подготовленный тест. "
                                    "Сначала вызови create_form с полным списком вопросов, "
                                    "затем дождись подтверждения формы. Не заверши диалог сейчас."
                                ),
                            },
                            ensure_ascii=False,
                        ),
                    )
                    await self._history.append(
                        chat_id,
                        Message("tool", result.content, call.id),
                    )
                    logger.warning(
                        "Blocked premature finish after confirmed form draft: chat_id=%s call_id=%s",
                        chat_id,
                        call.id,
                    )
                    continue
                await self._history.append(
                    chat_id,
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
