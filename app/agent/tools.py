from dataclasses import dataclass
from typing import Any

from app.agent.models import ToolResult, ToolHandler, ToolContext
from app.core.errors import ToolNotFoundError


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

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema for tool in self._tools.values()]

    async def call(self, name: str, context: ToolContext, args: dict[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolNotFoundError(name)

        return await tool.handler(context, args)