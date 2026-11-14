from typing import Hashable

from app.agent.models import GROUP_CHAT_TYPES


def is_group_chat(chat_type: str | None) -> bool:
    return (chat_type or "private") in GROUP_CHAT_TYPES


def conversation_key(chat_type: str | None, chat_id: int, user_id: int) -> Hashable:
    """History/lock key for one conversation.

    Private chats keep one context per chat; group chats must not mix course
    identifiers, drafts and confirmations of different participants, so each
    member gets a separate context inside the group.
    """
    if is_group_chat(chat_type):
        return (chat_id, user_id)
    return chat_id
