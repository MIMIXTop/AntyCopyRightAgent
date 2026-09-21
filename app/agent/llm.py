from typing import Sequence, Any

from app.core.types import LLMClient
from openai import AsyncClient
from app.config.settings import settings

class LLMAdaptor(LLMClient):
    def __init__(self):
        super().__init__()
        self._client = AsyncClient(
            base_url=settings.LLM_BASE_URL,
            api_key=settings.openai_api_key,
        )

    async def complete(self, message: Sequence[Any], tools: list[dict[str, Any]]) -> Any:
        try:
            response = await self._client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=message,
                tools=tools,
                tool_choice= "auto"
            )
        except Exception as e:
            raise e