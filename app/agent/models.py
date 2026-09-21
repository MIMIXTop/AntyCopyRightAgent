from dataclasses import dataclass
from typing import Callable, Any, Awaitable


@dataclass
class Message:
    role: str
    content: str
    tool_call_id: str | None = None

@dataclass
class ToolContext:
    chat_id: int
    user_id: int
    call_id: int

@dataclass
class ToolResult:
    call_id: int
    content: str
    terminal: bool = False

ToolHandler = Callable[
    [ToolContext, dict[str, Any]],
    Awaitable[ToolResult]
]