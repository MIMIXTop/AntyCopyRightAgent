import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from aiogram.types import Chat, Document, Message, User, Voice

from app.api.telegram.handlers import (
    build_delivery,
    create_router,
    has_bot_mention,
    is_addressed,
    is_reply_to_bot,
    strip_bot_mention,
)

GROUP_ID = -100123
ALICE = 111
BOB = 222


class FakeAgent:
    def __init__(self):
        self.calls = []

    async def handle(self, **kwargs):
        self.calls.append(kwargs)
        return "answer"

    async def reset(self, **kwargs):
        self.calls.append({"reset": kwargs})


class FakeTelegram:
    def __init__(self):
        self.messages = []

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)

    async def send_error(self, *args, **kwargs):
        pass


class FakeVoice:
    async def transcription_voice(self, data):
        return "voice text"


class FakeBot:
    async def download(self, *args, **kwargs):
        return b""


def make_message(
    text: str,
    *,
    chat_type: str = "supergroup",
    chat_id: int = GROUP_ID,
    user_id: int = ALICE,
    is_bot: bool = False,
    usernames: str = "alice",
    reply_to: Message | None = None,
    sender_chat: bool = False,
) -> Message:
    kwargs = {}
    if reply_to is not None:
        kwargs["reply_to_message"] = reply_to
    if sender_chat:
        kwargs["sender_chat"] = Chat(id=-100999, type="channel", title="Channel")
    return Message(
        message_id=1,
        date=datetime.now(),
        chat=Chat(id=chat_id, type=chat_type),
        from_user=User(
            id=user_id,
            is_bot=is_bot,
            first_name="Alice" if user_id == ALICE else "Bob",
            username=usernames,
        ),
        text=text,
        **kwargs,
    )


def handler(router, name):
    for item in router.message.handlers:
        if item.callback.__name__ == name:
            return item.callback
    raise AssertionError(f"handler {name} not registered")


@pytest.mark.asyncio
async def test_group_message_without_mention_is_ignored():
    agent, telegram = FakeAgent(), FakeTelegram()
    router = create_router(
        agent, FakeBot(), FakeVoice(), telegram, bot_username="Kira"
    )

    await handler(router, "handle_message")(make_message("просто болтаем"))

    assert agent.calls == []
    assert telegram.messages == []


@pytest.mark.asyncio
async def test_group_mention_starts_agent_and_is_stripped():
    agent, telegram = FakeAgent(), FakeTelegram()
    router = create_router(
        agent, FakeBot(), FakeVoice(), telegram, bot_username="Kira"
    )

    await handler(router, "handle_message")(make_message("@Kira создай курс"))

    assert len(agent.calls) == 1
    call = agent.calls[0]
    assert call["text"] == "создай курс"
    assert call["delivery"].chat_id == GROUP_ID
    assert call["delivery"].chat_type == "supergroup"
    assert call["delivery"].ephemeral is True
    assert call["delivery"].author_name == "Alice"
    assert telegram.messages[0]["delivery"].ephemeral is True


@pytest.mark.asyncio
async def test_mention_of_another_bot_is_ignored():
    agent = FakeAgent()
    router = create_router(
        agent, FakeBot(), FakeVoice(), FakeTelegram(), bot_username="Kira"
    )

    await handler(router, "handle_message")(make_message("@AnotherBot привет"))

    assert agent.calls == []


@pytest.mark.asyncio
async def test_bots_and_anonymous_admins_are_ignored():
    agent = FakeAgent()
    router = create_router(
        agent, FakeBot(), FakeVoice(), FakeTelegram(), bot_username="Kira"
    )
    run = handler(router, "handle_message")

    await run(make_message("@Kira привет", is_bot=True))
    await run(make_message("@Kira привет", sender_chat=True))

    assert agent.calls == []


@pytest.mark.asyncio
async def test_private_message_needs_no_mention():
    agent = FakeAgent()
    router = create_router(
        agent, FakeBot(), FakeVoice(), FakeTelegram(), bot_username="Kira"
    )

    await handler(router, "handle_message")(
        make_message("привет", chat_type="private", chat_id=ALICE)
    )

    assert len(agent.calls) == 1
    assert agent.calls[0]["delivery"].ephemeral is False


@pytest.mark.asyncio
async def test_reply_to_bot_is_enabled_by_flag_only():
    bot_user = User(id=999, is_bot=True, first_name="Kira", username="Kira")
    reply = make_message("@Kira hi").model_copy(update={"from_user": bot_user})

    assert is_reply_to_bot(make_message("hi", reply_to=reply), "Kira") is True
    # The reply is not accepted unless the deployment enables the mode.
    assert (
        is_addressed(make_message("hi", reply_to=reply), "Kira", allow_reply_to_bot=False)
        is False
    )
    assert (
        is_addressed(make_message("hi", reply_to=reply), "Kira", allow_reply_to_bot=True)
        is True
    )


@pytest.mark.asyncio
async def test_mention_without_question_gets_private_hint():
    agent, telegram = FakeAgent(), FakeTelegram()
    router = create_router(
        agent, FakeBot(), FakeVoice(), telegram, bot_username="Kira"
    )

    await handler(router, "handle_message")(make_message("@Kira"))

    assert agent.calls == []
    assert "Напишите вопрос" in telegram.messages[0]["text"]


def test_helpers_match_username_case_insensitively():
    message = make_message("@kira тест")
    assert has_bot_mention(message, "@Kira") is True
    assert has_bot_mention(make_message("@Kira2 тест"), "Kira") is False
    assert strip_bot_mention("@kira  тест", "Kira") == "тест"
    assert strip_bot_mention("почта a@kiramail.ru", "Kira") == "почта a@kiramail.ru"


def test_delivery_can_be_made_public_in_groups():
    delivery = build_delivery(
        make_message("@Kira hi"), group_replies_ephemeral=False
    )
    assert delivery.is_group is True
    assert delivery.use_ephemeral is False

    private = build_delivery(
        make_message("hi", chat_type="private", chat_id=ALICE)
    )
    assert private.use_ephemeral is False


def test_album_caption_and_incoming_ephemeral_message_are_addressed():
    album = make_message("@Kira вот файлы").model_copy(
        update={"text": None, "caption": "@Kira вот файлы"}
    )
    assert is_addressed(album, "Kira") is True

    ephemeral = make_message("приватный вопрос").model_copy(
        update={"ephemeral_message_id": 321}
    )
    assert is_addressed(ephemeral, "Kira") is True


def make_album_part(caption: str | None = None) -> Message:
    return Message(
        message_id=1,
        date=datetime.now(),
        chat=Chat(id=GROUP_ID, type="supergroup"),
        from_user=User(id=ALICE, is_bot=False, first_name="Alice", username="alice"),
        media_group_id="album-1",
        document=Document(
            file_id="file-1",
            file_unique_id="unique-1",
            file_name="notes.txt",
            mime_type="text/plain",
        ),
        caption=caption,
    )


@pytest.mark.asyncio
async def test_album_is_addressed_by_a_caption_on_any_part():
    agent, telegram = FakeAgent(), FakeTelegram()
    router = create_router(
        agent, FakeBot(), FakeVoice(), telegram, bot_username="Kira"
    )
    run = handler(router, "handle_media_group")

    # The mention lives only on the second part of the album.
    await asyncio.gather(
        run(make_album_part()),
        run(make_album_part("@Kira вот файлы")),
    )

    assert len(agent.calls) == 1
    assert agent.calls[0]["text"] == "вот файлы"
    assert len(agent.calls[0]["attachments"]) == 2
    assert agent.calls[0]["delivery"].ephemeral is True


@pytest.mark.asyncio
async def test_album_without_mention_is_ignored():
    agent = FakeAgent()
    router = create_router(
        agent, FakeBot(), FakeVoice(), FakeTelegram(), bot_username="Kira"
    )
    run = handler(router, "handle_media_group")

    await asyncio.gather(run(make_album_part()), run(make_album_part()))

    assert agent.calls == []


@pytest.mark.asyncio
async def test_voice_in_group_needs_ephemeral_or_reply_mode():
    agent = FakeAgent()
    router = create_router(
        agent, FakeBot(), FakeVoice(), FakeTelegram(), bot_username="Kira"
    )
    run = handler(router, "handle_voice_message")
    voice = Voice(file_id="voice-1", file_unique_id="unique-1", duration=1)
    message = make_message("").model_copy(
        update={"text": None, "voice": voice}
    )

    await run(message)
    assert agent.calls == []

    # An incoming ephemeral voice message is already visible only to the author.
    await run(message.model_copy(update={"ephemeral_message_id": 42}))
    assert len(agent.calls) == 1
    assert agent.calls[0]["text"] == "voice text"
    assert agent.calls[0]["delivery"].ephemeral is True


