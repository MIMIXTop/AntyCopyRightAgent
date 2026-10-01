from typing import Sequence, Any
from dataclasses import asdict

import openai
from openai import AsyncOpenAI

from app.core.types import LLMClient
from app.core.errors import LLMServiceError
from app.agent.models import Message, LLMResponse, ToolCallInfo
from app.core.logging import logger


class OpenAIAdapter(LLMClient):
    def __init__(self, client: AsyncOpenAI, model: str) -> None:
        self._client = client
        self._model = model

    async def complete(
            self,
            messages: Sequence[Message],
            tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        logger.info(
            "LLM complete called: model=%s messages=%s tools=%s",
            self._model,
            [asdict(message) for message in messages],
            tools,
        )

        ai_messages = []
        for msg in messages:
            ai_msg = {"role": msg.role, "content": msg.content or ""}
            if msg.tool_call_id:
                ai_msg["tool_call_id"] = msg.tool_call_id
            if msg.tool_calls:
                ai_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments}
                    } for tc in msg.tool_calls
                ]
            ai_messages.append(ai_msg)

        kwargs = {
            "model": self._model,
            "messages": ai_messages,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            response = await self._client.chat.completions.create(**kwargs)
        except openai.OpenAIError as error:
            logger.exception("LLM request failed: model=%s", self._model)
            raise LLMServiceError(f"LLM API request failed: {error}") from error

        choice = response.choices[0].message
        logger.info(
            "LLM response received: model=%s text=%r tool_calls=%s",
            self._model,
            choice.content,
            [
                {"id": call.id, "name": call.function.name, "arguments": call.function.arguments}
                for call in (choice.tool_calls or [])
            ],
        )

        parsed_tool_calls = []
        if choice.tool_calls:
            for tc in choice.tool_calls:
                parsed_tool_calls.append(
                    ToolCallInfo(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=tc.function.arguments
                    )
                )

        return LLMResponse(
            text=choice.content or "",
            tool_calls=parsed_tool_calls
        )