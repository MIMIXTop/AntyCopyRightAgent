import base64
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
            attachments = msg.attachments or []

            photo_attachments = [
                att for att in attachments
                if att.kind == "photo" and att.data
            ]

            if photo_attachments:
                content_parts: list[dict[str, Any]] = []
                if msg.content:
                    content_parts.append({"type": "text", "text": str(msg.content)})

                for photo in photo_attachments:
                    b64_img = base64.b64encode(photo.data).decode("utf-8")
                    mime = photo.mime_type or "image/jpeg"
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime};base64,{b64_img}"
                        }
                    })
                ai_content = content_parts
            else:
                ai_content = msg.content or ""

            ai_msg: dict[str, Any] = {"role": msg.role, "content": ai_content}
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

        debug_messages = []
        for m in ai_messages:
            if isinstance(m["content"], list):
                debug_messages.append({
                    "role": m["role"],
                    "content": f"[Multimodal content: {len(m['content'])} parts]"
                })
            else:
                debug_messages.append(m)

        logger.info(
            "LLM complete called: model=%s messages_count=%d tools_count=%d",
            self._model,
            len(ai_messages),
            len(tools or []),
        )

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