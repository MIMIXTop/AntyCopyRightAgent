from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import EditEphemeralMessageText

from app.agent.models import DeliveryContext
from app.api.telegram.service import TelegramService

GROUP_ID = -100123
USER_ID = 111


class FakeBot:
    def __init__(self, fail_ephemeral: bool = False, fail_dm: bool = False):
        self.fail_ephemeral = fail_ephemeral
        self.fail_dm = fail_dm
        self.sent = []
        self.calls = []

    async def send_message(self, **kwargs):
        ephemeral = kwargs.get("ephemeral_message_parameters")
        if ephemeral is not None and self.fail_ephemeral:
            raise TelegramBadRequest(method=None, message="Bad Request: no ephemeral")
        if (
            ephemeral is None
            and kwargs.get("chat_id") == USER_ID
            and self.fail_dm
        ):
            raise TelegramForbiddenError(method=None, message="Forbidden: bot was blocked")
        self.sent.append(kwargs)

    async def send_photo(self, **kwargs):
        self.sent.append(kwargs)

    async def send_voice(self, **kwargs):
        self.sent.append(kwargs)

    async def __call__(self, method, *args, **kwargs):
        self.calls.append(method)
        return method


def group_delivery(**overrides) -> DeliveryContext:
    values = dict(
        chat_id=GROUP_ID,
        user_id=USER_ID,
        chat_type="supergroup",
        ephemeral=True,
    )
    values.update(overrides)
    return DeliveryContext(**values)


@pytest.mark.asyncio
async def test_group_answer_is_sent_ephemeral_to_the_author():
    bot = FakeBot()
    service = TelegramService(bot)

    await service.send_message(
        text="ответ",
        chat_id=GROUP_ID,
        delivery=group_delivery(),
    )

    params = bot.sent[0]["ephemeral_message_parameters"]
    assert params.receiver_user_id == USER_ID
    assert params.callback_query_id is None
    assert bot.sent[0]["chat_id"] == GROUP_ID


@pytest.mark.asyncio
async def test_private_chat_never_uses_ephemeral_parameters():
    bot = FakeBot()
    service = TelegramService(bot)

    await service.send_message(
        text="ответ",
        chat_id=USER_ID,
        delivery=DeliveryContext(chat_id=USER_ID, user_id=USER_ID),
    )

    assert "ephemeral_message_parameters" not in bot.sent[0]


@pytest.mark.asyncio
async def test_confirmation_is_forced_ephemeral_in_groups():
    bot = FakeBot()
    service = TelegramService(bot)

    await service.request_course_confirmation(
        chat_id=GROUP_ID,
        course_name="Python",
        pending_id="p1",
        delivery=group_delivery(ephemeral=False),
    )

    params = bot.sent[0]["ephemeral_message_parameters"]
    assert params.receiver_user_id == USER_ID
    assert bot.sent[0]["reply_markup"] is not None


@pytest.mark.asyncio
async def test_group_question_follows_reply_visibility_not_action_flag():
    bot = FakeBot()
    # Even with forced-ephemeral actions, a question is conversation, so its
    # visibility follows GROUP_REPLIES_EPHEMERAL (delivery.ephemeral).
    service = TelegramService(bot, group_actions_ephemeral=True)

    await service.request_choice(
        chat_id=GROUP_ID,
        user_id=USER_ID,
        question="Какой курс?",
        options=[{"label": "Python", "value": "python"}],
        delivery=group_delivery(ephemeral=False),
    )

    assert "ephemeral_message_parameters" not in bot.sent[0]
    assert bot.sent[0]["chat_id"] == GROUP_ID
    assert bot.sent[0]["reply_markup"] is not None


@pytest.mark.asyncio
async def test_callback_answer_carries_callback_query_id():
    bot = FakeBot()
    service = TelegramService(bot)

    await service.send_message(
        text="готово",
        chat_id=GROUP_ID,
        delivery=group_delivery(callback_query_id="cb-1"),
    )

    assert bot.sent[0]["ephemeral_message_parameters"].callback_query_id == "cb-1"


@pytest.mark.asyncio
async def test_ephemeral_failure_falls_back_to_dm():
    bot = FakeBot(fail_ephemeral=True)
    service = TelegramService(bot)

    await service.send_message(
        text="ответ",
        chat_id=GROUP_ID,
        delivery=group_delivery(),
    )

    assert len(bot.sent) == 1
    assert bot.sent[0]["chat_id"] == USER_ID
    assert "ephemeral_message_parameters" not in bot.sent[0]


@pytest.mark.asyncio
async def test_ephemeral_and_dm_failure_falls_back_to_public_group_message():
    bot = FakeBot(fail_ephemeral=True, fail_dm=True)
    service = TelegramService(bot)

    await service.send_message(
        text="ответ",
        chat_id=GROUP_ID,
        delivery=group_delivery(),
    )

    assert len(bot.sent) == 1
    assert bot.sent[0]["chat_id"] == GROUP_ID
    assert "ephemeral_message_parameters" not in bot.sent[0]


@pytest.mark.asyncio
async def test_reply_to_incoming_ephemeral_command_uses_reply_parameters():
    bot = FakeBot()
    service = TelegramService(bot)

    await service.send_message(
        text="ответ",
        chat_id=GROUP_ID,
        delivery=group_delivery(ephemeral_message_id=777),
    )

    assert bot.sent[0]["reply_parameters"].ephemeral_message_id == 777
    assert bot.sent[0]["ephemeral_message_parameters"].receiver_user_id == USER_ID


@pytest.mark.asyncio
async def test_edit_status_edits_an_ephemeral_message_with_the_right_method():
    bot = FakeBot()
    service = TelegramService(bot)
    edited = []

    async def edit_text(text, **kwargs):
        edited.append(text)

    message = SimpleNamespace(
        chat=SimpleNamespace(id=GROUP_ID, type="supergroup"),
        ephemeral_message_id=55,
        edit_text=edit_text,
    )
    call = SimpleNamespace(
        id="cb-1",
        from_user=SimpleNamespace(id=USER_ID),
        message=message,
    )

    await service.edit_status(call, "готово")

    assert edited == []
    assert len(bot.calls) == 1
    method = bot.calls[0]
    assert isinstance(method, EditEphemeralMessageText)
    assert method.chat_id == GROUP_ID
    assert method.receiver_user_id == USER_ID
    assert method.ephemeral_message_id == 55


@pytest.mark.asyncio
async def test_edit_status_without_message_sends_ephemeral_callback_reply():
    bot = FakeBot()
    service = TelegramService(bot)
    call = SimpleNamespace(
        id="cb-2",
        from_user=SimpleNamespace(id=USER_ID),
        message=None,
    )

    await service.edit_status(call, "готово", chat_id=GROUP_ID)

    assert bot.sent[0]["chat_id"] == GROUP_ID
    assert bot.sent[0]["ephemeral_message_parameters"].callback_query_id == "cb-2"
