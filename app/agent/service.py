import json

from app.agent.models import Message, ToolContext
from app.core.errors import AgentIterationLimitError, ToolArgumentsError
from app.core.types import HistoryStore, LLMClient
from app.agent.tools import ToolRegistry


class AgentService:
    def __init__(self, llm: LLMClient, history: HistoryStore, tools: ToolRegistry, max_iterations: int = 10):
        self._llm = llm
        self._history = history
        self._tools = tools
        self._max_iterations = max_iterations

    async def handle(self, chat_id: int, user_id: int, text: str) -> str:
        await self._history.append(chat_id, Message("user", text))

        for _ in range(self._max_iterations):
            response = await self._llm.complete(
                messages=await self._history.get(chat_id),
                tools=self._tools.schemas(),
            )

            if not response.tool_calls:
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

                result = await self._tools.call(
                    call.name,
                    ToolContext(chat_id, user_id, call.id),
                    arguments,
                )

                await self._history.append(
                    chat_id,
                    Message("tool", result.content, call.id)
                )
                if result.terminal:
                    return ""

        raise AgentIterationLimitError(self._max_iterations)
