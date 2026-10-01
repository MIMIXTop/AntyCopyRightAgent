from dataclasses import dataclass
from typing import Any

from app.agent.models import ToolResult, ToolHandler, ToolContext
from app.core.errors import ToolNotFoundError
from app.core.logging import logger


@dataclass
class RegisteredTools:
    handler: ToolHandler
    schema: dict[str, Any]

class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, RegisteredTools] = {}

    def register(self, name: str, handler: ToolHandler, schema: dict[str, Any]):
        if name in self._tools:
            raise ValueError(f"Tool {name} already registered")
        self._tools[name] = RegisteredTools(handler, schema)
        logger.info("Tool registered: name=%s schema=%s", name, schema)

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema for tool in self._tools.values()]

    async def call(self, name: str, context: ToolContext, args: dict[str, Any]) -> ToolResult:
        logger.info(
            "Tool call started: name=%s chat_id=%s user_id=%s call_id=%s arguments=%s",
            name,
            context.chat_id,
            context.user_id,
            context.call_id,
            args,
        )
        tool = self._tools.get(name)
        if tool is None:
            logger.error("Tool not found: name=%s arguments=%s", name, args)
            raise ToolNotFoundError(name)

        result = await tool.handler(context, args)
        logger.info(
            "Tool call finished: name=%s call_id=%s terminal=%s content=%s",
            name,
            context.call_id,
            result.terminal,
            result.content,
        )
        return result