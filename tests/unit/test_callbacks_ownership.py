from types import SimpleNamespace

import pytest

from app.api.telegram.callbacks import create_callback_router

GROUP_ID = -100123
ALICE = 111
BOB = 222


class FakeClassroom:
    def __init__(self, data=None):
        self.data = data
        self.removed = []
        self.created = []

    def get_pending_course(self, pending_id):
        return self.data

    def remove_pending_course(self, pending_id):
        self.removed.append(pending_id)

    async def create_course(self, **kwargs):
        self.created.append(kwargs)
        return {"id": "course-1"}


class FakeUpdateClassroom(FakeClassroom):
    def __init__(self, data):
        super().__init__(data)
        self.updates = []

    def get_pending_update(self, pending_id):
        return self.data

    def remove_pending_update(self, pending_id):
        self.removed.append(pending_id)

    async def update_assignment(self, **kwargs):
        self.updates.append(kwargs)
        return SimpleNamespace(id=kwargs["assignment_id"])


class FakeHistory:
    def __init__(self):
        self.appended = []

    async def append(self, conversation_id, *messages):
        self.appended.append((conversation_id, messages))


class FakeTelegram:
    def __init__(self):
        self.edits = []
        self.messages = []

    async def edit_status(self, call, text, **kwargs):
        self.edits.append((call, text, kwargs))

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)


def make_call(user_id: int = ALICE):
    answers = []

    async def answer(text=None, **kwargs):
        answers.append((text, kwargs))

    call = SimpleNamespace(
        id="cb-1",
        data="course:create:cancel:p1",
        from_user=SimpleNamespace(id=user_id),
        message=None,
        answer=answer,
    )
    return call, answers


def find_handler(router, name):
    for item in router.callback_query.handlers:
        if item.callback.__name__ == name:
            return item.callback
    raise AssertionError(f"callback {name} not registered")


@pytest.mark.asyncio
async def test_assignment_update_forwards_topic_id_on_confirmation():
    classroom = FakeUpdateClassroom(
        {
            "resource": "assignment",
            "telegram_id": ALICE,
            "chat_id": ALICE,
            "chat_type": "private",
            "course_id": "course-1",
            "assignment_id": "work-1",
            "title": None,
            "description": None,
            "max_points": None,
            "due_date": None,
            "due_time": None,
            "state": None,
            "topic_id": "topic-1",
        }
    )
    telegram = FakeTelegram()
    router = create_callback_router(
        classroom=classroom,
        history_store=FakeHistory(),
        telegram=telegram,
        agent=None,
    )
    call, answers = make_call(ALICE)
    call.data = "course:work:update:confirm:p1"

    await find_handler(router, "confirm_assignment_update")(call)

    assert classroom.updates == [
        {
            "telegram_id": ALICE,
            "course_id": "course-1",
            "assignment_id": "work-1",
            "title": None,
            "description": None,
            "max_points": None,
            "due_date": None,
            "due_time": None,
            "state": None,
            "topic_id": "topic-1",
        }
    ]
    assert classroom.removed == ["p1"]
    assert telegram.edits[0][1] == "✅ Задание успешно изменено."


@pytest.mark.asyncio
async def test_group_callback_uses_pending_chat_even_without_message():
    classroom = FakeClassroom(
        {
            "telegram_id": ALICE,
            "chat_id": GROUP_ID,
            "chat_type": "supergroup",
            "name": "Python",
        }
    )
    history = FakeHistory()
    telegram = FakeTelegram()
    router = create_callback_router(
        classroom=classroom,
        history_store=history,
        telegram=telegram,
        agent=None,
    )
    call, answers = make_call(ALICE)

    await find_handler(router, "cancel_course_creation")(call)

    assert classroom.removed == ["p1"]
    assert answers and answers[0][0] is None
    # The status edit targets the group chat, not a fallback DM.
    assert telegram.edits[0][2]["chat_id"] == GROUP_ID
    # History is written for the presser's group conversation.
    assert history.appended[0][0] == (GROUP_ID, ALICE)
    assert len(history.appended) == 2  # cancellation + action_result event


@pytest.mark.asyncio
async def test_foreign_button_is_rejected_and_pending_is_kept():
    classroom = FakeClassroom(
        {
            "telegram_id": ALICE,
            "chat_id": GROUP_ID,
            "chat_type": "supergroup",
            "name": "Python",
        }
    )
    history = FakeHistory()
    telegram = FakeTelegram()
    router = create_callback_router(
        classroom=classroom,
        history_store=history,
        telegram=telegram,
        agent=None,
    )
    call, answers = make_call(BOB)

    await find_handler(router, "cancel_course_creation")(call)

    assert classroom.removed == []
    assert telegram.edits == []
    assert history.appended == []
    assert answers[0][0] == "Эта кнопка не для вас"
    assert answers[0][1]["show_alert"] is True


@pytest.mark.asyncio
async def test_group_confirmation_is_rejected_in_safe_mode():
    classroom = FakeClassroom(
        {
            "telegram_id": ALICE,
            "chat_id": GROUP_ID,
            "chat_type": "supergroup",
            "name": "Python",
            "description": "Course",
            "section": None,
        }
    )
    history = FakeHistory()
    telegram = FakeTelegram()
    router = create_callback_router(
        classroom=classroom,
        history_store=history,
        telegram=telegram,
        agent=None,
        group_safe_mode=True,
    )
    call, answers = make_call(ALICE)
    call.data = "course:create:confirm:p1"

    await find_handler(router, "confirm_course_creation")(call)

    assert classroom.created == []
    assert classroom.removed == []
    assert telegram.edits == []
    assert history.appended == []
    assert "личные сообщения" in answers[0][0]
    assert answers[0][1]["show_alert"] is True


@pytest.mark.asyncio
async def test_private_confirmation_still_works_in_safe_mode():
    classroom = FakeClassroom(
        {
            "telegram_id": ALICE,
            "chat_id": ALICE,
            "chat_type": "private",
            "name": "Python",
            "description": "Course",
            "section": None,
        }
    )
    telegram = FakeTelegram()
    router = create_callback_router(
        classroom=classroom,
        history_store=FakeHistory(),
        telegram=telegram,
        agent=None,
        group_safe_mode=True,
    )
    call, answers = make_call(ALICE)
    call.data = "course:create:confirm:p1"

    await find_handler(router, "confirm_course_creation")(call)

    assert len(classroom.created) == 1
    assert classroom.created[0]["course_name"] == "Python"
    assert classroom.removed == ["p1"]
    assert answers[0][0] is None
