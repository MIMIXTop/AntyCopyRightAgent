import base64
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
    data: bytes | None = None

    @property
    def base64_data(self) -> str | None:
        if self.data:
            return base64.b64encode(self.data).decode("utf-8")
        return None

GROUP_CHAT_TYPES = {"group", "supergroup"}


@dataclass(frozen=True)
class DeliveryContext:
    """Where a visible message must go and who is allowed to see it.

    In group chats ``ephemeral`` requests a Telegram ephemeral message that is
    visible only to ``user_id``. ``callback_query_id`` is set when the message is
    a direct answer to an inline button press; ``ephemeral_message_id`` when it
    replies to an incoming ephemeral command.
    """

    chat_id: int
    user_id: int
    chat_type: str = "private"
    ephemeral: bool = False
    callback_query_id: str | None = None
    ephemeral_message_id: int | None = None
    author_name: str | None = None

    @property
    def is_group(self) -> bool:
        return self.chat_type in GROUP_CHAT_TYPES

    @property
    def use_ephemeral(self) -> bool:
        return self.ephemeral and self.is_group


@dataclass
class ToolContext:
    chat_id: int
    user_id: int
    call_id: str
    attachments: list[TelegramAttachment] = field(default_factory=list)
    role: str = "teacher"
    delivery: DeliveryContext | None = None
    # True when the attachments come from an earlier message (remembered for a
    # confirmation turn) instead of the message that triggered this run.
    attachments_reused: bool = False

    @property
    def chat_type(self) -> str:
        return self.delivery.chat_type if self.delivery is not None else "private"

    @property
    def is_group(self) -> bool:
        return self.chat_type in GROUP_CHAT_TYPES

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
    finish_reason: str | None = None
    refusal: str | None = None

@dataclass
class Message:
    role: str
    content: str | list[dict] | None
    tool_call_id: str | None = None
    tool_calls: list[ToolCallInfo] | None = None
    attachments: list[TelegramAttachment] = field(default_factory=list)
    # Forward origin ("из канала «X» (@x)") and a quoted forwarded message the
    # user replied to. Kept separate from ``content`` so logs and history show
    # what the user actually wrote.
    forwarded_from: str | None = None
    reply_context: str | None = None

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