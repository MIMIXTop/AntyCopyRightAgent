from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Any, Awaitable


@dataclass
class TelegramAttachment:
    file_id: str
    file_name: str | None = None
    mime_type: str | None = None
    size: int | None = None
    kind: str = "document"

@dataclass
class ToolContext:
    chat_id: int
    user_id: int
    call_id: str
    attachments: list[TelegramAttachment] = field(default_factory=list)

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

@dataclass
class PendingCourseCreated:
    id: str
    chat_id: int
    user_id: int
    name: str
    description: str
    section: str | None
    expires_at: datetime