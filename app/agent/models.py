from dataclasses import dataclass, field
from typing import Callable, Any, Awaitable


@dataclass
class ToolContext:
    chat_id: int
    user_id: int
    call_id: str

@dataclass
class ToolResult:
    call_id: str
    content: str
    terminal: bool = False

@dataclass
class ToolCallInfo:
    id: str
    name: str
    arguments: str

@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCallInfo] = field(default_factory=list)

@dataclass
class Message:
    role: str
    content: str | None
    tool_call_id: str | None = None
    tool_calls: list[ToolCallInfo] | None = None

ToolHandler = Callable[
    [ToolContext, dict[str, Any]],
    Awaitable[ToolResult]
]