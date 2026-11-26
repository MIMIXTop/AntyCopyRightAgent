"""Human-readable context for forwarded messages.

Telegram only exposes what the update contains. If the sender hid their
account, the bot sees a display name without a username or id — the prompt
must never fill those gaps with guesses.
"""

from aiogram.types import Chat, Message as TgMessage, User

# A quoted forward can be a whole channel post. Keep the prompt bounded.
REPLY_CONTEXT_MAX_CHARS = 2000


def _user_source(user: User | None) -> str | None:
    if user is None:
        return None
    name = user.full_name or user.first_name or "пользователь"
    if user.username:
        return f"от пользователя {name} (@{user.username})"
    return f"от пользователя {name}"


def _chat_source(chat: Chat | None, *, channel: bool) -> str | None:
    if chat is None:
        return None
    kind = "канала" if channel else "чата"
    title = chat.title or chat.username or str(chat.id)
    if chat.username:
        return f"из {kind} «{title}» (@{chat.username})"
    return f"из {kind} «{title}»"


def _with_signature(source: str, signature: str | None) -> str:
    if signature:
        return f"{source}, подпись автора: {signature}"
    return source


def describe_forward(message: TgMessage) -> str | None:
    """Return the forward origin as a clause, e.g. ``из канала «X» (@x)``.

    Supports both the modern ``forward_origin`` and the legacy
    ``forward_from`` fields, so older clients keep working.
    """
    origin = getattr(message, "forward_origin", None)
    if origin is not None:
        kind = getattr(origin, "type", None)
        if kind == "user":
            source = _user_source(getattr(origin, "sender_user", None))
            if source:
                return source
        elif kind == "hidden_user":
            name = getattr(origin, "sender_user_name", None)
            if name:
                return f"от пользователя со скрытым профилем «{name}»"
        elif kind == "chat":
            source = _chat_source(
                getattr(origin, "sender_chat", None),
                channel=False,
            )
            if source:
                return _with_signature(
                    source,
                    getattr(origin, "author_signature", None),
                )
        elif kind == "channel":
            source = _chat_source(
                getattr(origin, "chat", None),
                channel=True,
            )
            if source:
                source = _with_signature(
                    source,
                    getattr(origin, "author_signature", None),
                )
                if getattr(message, "is_automatic_forward", False):
                    source += " (автоматическая пересылка)"
                return source

    # Legacy fields are still populated by some clients.
    forward_from = getattr(message, "forward_from", None)
    if forward_from is not None:
        source = _user_source(forward_from)
        if source:
            return source

    forward_from_chat = getattr(message, "forward_from_chat", None)
    if forward_from_chat is not None:
        source = _chat_source(
            forward_from_chat,
            channel=getattr(forward_from_chat, "type", None) == "channel",
        )
        if source:
            return _with_signature(
                source,
                getattr(message, "forward_signature", None),
            )

    hidden_name = getattr(message, "forward_sender_name", None)
    if hidden_name:
        return f"от пользователя со скрытым профилем «{hidden_name}»"

    if getattr(message, "is_automatic_forward", False):
        return "из канала (название недоступно)"

    return None


def _quoted_text(message: TgMessage) -> str:
    text = (message.text or message.caption or "").strip()
    if text:
        return text
    # Media-only forwards have no text; at least tell the model what it is.
    parts: list[str] = []
    if message.photo:
        parts.append("фото")
    if message.document:
        parts.append(f"файл {message.document.file_name or ''}".strip())
    if message.voice:
        parts.append("голосовое сообщение")
    if message.video:
        parts.append("видео")
    if message.audio:
        parts.append("аудио")
    return ", ".join(parts)


def describe_reply_context(message: TgMessage) -> str | None:
    """Return the quoted text when the user replies to a forwarded message."""
    replied = message.reply_to_message
    if replied is None:
        return None

    # Do not skip bot-authored replies: automatic channel forwards in
    # discussion groups are authored by Channel_Bot. Kira's own messages are
    # not forwarded, so describe_forward already filters them out.
    source = describe_forward(replied)
    if source is None:
        return None

    quoted = _quoted_text(replied)
    if len(quoted) > REPLY_CONTEXT_MAX_CHARS:
        quoted = quoted[:REPLY_CONTEXT_MAX_CHARS].rstrip() + "…"
    if not quoted:
        return (
            "Пользователь отвечает на сообщение, пересланное "
            f"{source}, но в нём нет текста."
        )
    return (
        "Пользователь отвечает на сообщение, пересланное "
        f"{source}. Цитата:\n{quoted}\nКонец цитаты."
    )
