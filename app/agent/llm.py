import base64
from typing import Sequence, Any

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

    async def transcription_voice(self, voice_bytes: bytes):

        res = await self._client.audio.transcriptions.create(
            file=("voice.ogg", voice_bytes, "audio/ogg"),
            model=self._model,
            languages=["en", "ru"],
        )
        return res

    async def complete(
            self,
            messages: Sequence[Message],
            tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
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

        request_messages = []
        for m in ai_messages:
            if m["role"] == "system":
                continue
            if isinstance(m["content"], list):
                request_messages.append({
                    "role": m["role"],
                    "content": f"[Multimodal content: {len(m['content'])} parts]"
                })
            else:
                request_messages.append(m)

        logger.info(
            "LLM request: model=%s messages_count=%d messages=%s tools_count=%d",
            self._model,
            len(request_messages),
            request_messages,
            len(tools or []),
        )

        kwargs = {
            "model": self._model,
            "messages": ai_messages,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
            kwargs["parallel_tool_calls"] = False

        try:
            response = await self._client.chat.completions.create(**kwargs)
        except openai.OpenAIError as error:
            logger.exception("LLM request failed: model=%s", self._model)
            raise LLMServiceError(f"LLM API request failed: {error}") from error

        choice = response.choices[0].message
        logger.info(
            "LLM response received: model=%s finish_reason=%s refusal=%r text=%r tool_calls=%s",
            self._model,
            response.choices[0].finish_reason,
            choice.refusal,
            choice.content,
            [
                {"id": call.id, "name": call.function.name, "arguments": call.function.arguments}
                for call in (choice.tool_calls or [])
            ],
        )

        parsed_tool_calls = []
        if choice.tool_calls:
            parsed_tool_calls = [
                ToolCallInfo(
                    id=tool_call.id,
                    name=tool_call.function.name,
                    arguments=tool_call.function.arguments,
                )
                for tool_call in choice.tool_calls
            ]

        return LLMResponse(
            text=choice.content or "",
            tool_calls=parsed_tool_calls,
            finish_reason=response.choices[0].finish_reason,
            refusal=choice.refusal,
        )