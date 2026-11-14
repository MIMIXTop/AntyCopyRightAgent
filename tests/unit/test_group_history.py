import pytest

from app.agent.conversation import conversation_key, is_group_chat
from app.agent.history import InMemoryHistoryStore
from app.agent.models import DeliveryContext, LLMResponse
from app.agent.service import AgentService
from app.agent.tools import ToolRegistry

GROUP_ID = -100123
ALICE = 111
BOB = 222


class FakeLLM:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    async def complete(self, messages, tools=None):
        self.calls.append(messages)
        return next(self.responses)


def make_service(responses):
    return AgentService(
        FakeLLM(responses),
        InMemoryHistoryStore(),
        ToolRegistry(),
        3,
    )


def group_delivery(user_id: int) -> DeliveryContext:
    return DeliveryContext(
        chat_id=GROUP_ID,
        user_id=user_id,
        chat_type="supergroup",
        ephemeral=True,
    )


def user_messages(history):
    return [message.content for message in history if message.role == "user"]


def test_group_key_is_chat_and_user_private_key_is_chat():
    assert conversation_key("supergroup", GROUP_ID, ALICE) == (GROUP_ID, ALICE)
    assert conversation_key("group", GROUP_ID, ALICE) == (GROUP_ID, ALICE)
    assert conversation_key("private", ALICE, ALICE) == ALICE
    assert is_group_chat("supergroup") is True
    assert is_group_chat("private") is False


@pytest.mark.asyncio
async def test_group_members_have_isolated_history():
    service = make_service([LLMResponse("a"), LLMResponse("b")])

    await service.handle(GROUP_ID, ALICE, "alice question", delivery=group_delivery(ALICE))
    await service.handle(GROUP_ID, BOB, "bob question", delivery=group_delivery(BOB))

    alice_history = await service._history.get((GROUP_ID, ALICE))
    bob_history = await service._history.get((GROUP_ID, BOB))

    assert user_messages(alice_history) == ["alice question"]
    assert user_messages(bob_history) == ["bob question"]


@pytest.mark.asyncio
async def test_private_history_key_is_unchanged():
    service = make_service([LLMResponse("ok")])

    await service.handle(
        ALICE,
        ALICE,
        "private question",
        delivery=DeliveryContext(chat_id=ALICE, user_id=ALICE),
    )

    assert user_messages(await service._history.get(ALICE)) == ["private question"]


@pytest.mark.asyncio
async def test_reset_clears_only_the_callers_group_context():
    service = make_service([LLMResponse("a"), LLMResponse("b")])

    await service.handle(GROUP_ID, ALICE, "alice", delivery=group_delivery(ALICE))
    await service.handle(GROUP_ID, BOB, "bob", delivery=group_delivery(BOB))

    await service.reset(GROUP_ID, ALICE, chat_type="supergroup")

    assert user_messages(await service._history.get((GROUP_ID, ALICE))) == []
    assert user_messages(await service._history.get((GROUP_ID, BOB))) == ["bob"]
