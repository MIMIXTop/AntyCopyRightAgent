import json

from app.agent.models import Message, ToolContext, TelegramAttachment
from app.core.errors import AgentIterationLimitError, ToolArgumentsError
from app.core.logging import logger
from app.core.types import HistoryStore, LLMClient
from app.agent.tools import ToolRegistry


class AgentService:
    def __init__(self, llm: LLMClient, history: HistoryStore, tools: ToolRegistry, max_iterations: int = 10):
        self._llm = llm
        self._history = history
        self._tools = tools
        self._max_iterations = max_iterations

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
        await self._history.append(
            chat_id,
            Message("user", content=text, attachments=attachments or []),
        )

        for iteration in range(self._max_iterations):
            logger.info("Agent iteration started: chat_id=%s iteration=%s", chat_id, iteration + 1)
            response = await self._llm.complete(
                messages=await self._history.get(chat_id),
                tools=self._tools.schemas(),
            )

            if not response.tool_calls:
                logger.info("Agent completed with text: chat_id=%s text=%r", chat_id, response.text)
                await self._history.append(
                    chat_id,
                    Message("assistant", response.text),
                )
                return response.text

            await self._history.append(
                chat_id,
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
                    raise ToolArgumentsError(
                        call.name,
                        "tool arguments must be valid JSON",
                    ) from error
                if not isinstance(arguments, dict):
                    raise ToolArgumentsError(
                        call.name,
                        "tool arguments must be a JSON object",
                    )

                logger.info(f"arguments: {arguments}")
                logger.info(
                    "Agent tool call: chat_id=%s tool=%s call_id=%s arguments=%s",
                    chat_id,
                    call.name,
                    call.id,
                    arguments,
                )

                result = await self._tools.call(
                    call.name,
                    ToolContext(chat_id, user_id, call.id, attachments or []),
                    arguments,
                )

                await self._history.append(
                    chat_id,
                    Message("tool", result.content, call.id)
                )
                if result.terminal:
                    logger.info(
                        "Agent tool terminated flow: chat_id=%s tool=%s call_id=%s",
                        chat_id,
                        call.name,
                        call.id,
                    )
                    return ""

        logger.error("Agent iteration limit reached: chat_id=%s limit=%s", chat_id, self._max_iterations)
        raise AgentIterationLimitError(self._max_iterations)
