import json

import pytest

from app.agent.models import ToolContext
from app.agent.tools import ToolRegistry
from app.api.forms.models import Form, FormResponsesList
from app.api.forms.service import FormsService
from app.api.telegram.service import TelegramService
from app.core.errors import ToolArgumentsError
from app.registers.forms import register_forms_tools


class FakeBot:
    async def send_message(self, **kwargs):
        return None


class FakeTelegramService(TelegramService):
    def __init__(self):
        super().__init__(bot=FakeBot())
        self.form_creation = None
        self.form_question = None
        self.form_publish = None

    async def request_form_creation(self, **kwargs):
        self.form_creation = kwargs

    async def request_form_question(self, **kwargs):
        self.form_question = kwargs

    async def request_form_publish(self, **kwargs):
        self.form_publish = kwargs


class FakeFormsService(FormsService):
    def __init__(self):
        super().__init__(client=None)
        self.created = None
        self.question_added = None
        self.published = None

    async def create_form_with_questions(self, telegram_id, title, description="", is_quiz=False, questions=None):
        self.created = {
            "telegram_id": telegram_id,
            "title": title,
            "description": description,
            "is_quiz": is_quiz,
            "questions": questions or [],
        }
        return Form.model_validate({
            "formId": "form-1",
            "info": {"title": title},
            "responderUri": "https://docs.google.com/forms/d/form-1/viewform",
        })

    async def add_question(self, telegram_id, form_id, question_spec):
        self.question_added = {
            "telegram_id": telegram_id,
            "form_id": form_id,
            "question": question_spec,
        }
        return {}

    async def publish_form(self, telegram_id, form_id):
        self.published = {"telegram_id": telegram_id, "form_id": form_id}
        return {}

    async def get_form(self, telegram_id, form_id):
        return Form.model_validate({
            "formId": form_id,
            "info": {"title": "Тест по алгебре"},
            "settings": {"quizSettings": {"isQuiz": True}},
            "publishSettings": {
                "publishState": {
                    "isPublished": True,
                    "isAcceptingResponses": True,
                }
            },
            "responderUri": f"https://docs.google.com/forms/d/{form_id}/viewform",
        })

    async def get_responses(self, telegram_id, form_id):
        return FormResponsesList.model_validate({"responses": [], "totalResponses": 0})


def build_registry(service=None, telegram=None):
    service = service or FakeFormsService()
    telegram = telegram or FakeTelegramService()
    registry = ToolRegistry()
    register_forms_tools(registry, service, telegram)
    return registry, service, telegram


@pytest.mark.asyncio
async def test_create_form_holds_pending_and_requests_confirmation():
    registry, service, telegram = build_registry()

    result = await registry.call(
        "create_form",
        ToolContext(chat_id=1, user_id=42, call_id="call-1"),
        {
            "title": "Тест по алгебре",
            "description": "Вариант 1",
            "is_quiz": True,
            "questions": [
                {
                    "title": "Сколько будет 2 + 2?",
                    "type": "radio",
                    "options": ["3", "4"],
                    "correct_answers": ["4"],
                    "points": 5,
                    "required": True,
                },
                {
                    "title": "Решите уравнение",
                    "type": "long_text",
                },
            ],
        },
    )

    payload = json.loads(result.content)
    assert result.terminal is True
    assert payload["status"] == "paused"

    pending = service.get_pending_form(payload["pending_id"])
    assert pending["title"] == "Тест по алгебре"
    assert pending["is_quiz"] is True
    assert pending["publish"] is False
    assert pending["questions"][0] == {
        "title": "Сколько будет 2 + 2?",
        "type": "radio",
        "options": ["3", "4"],
        "correct_answers": ["4"],
        "points": 5,
        "required": True,
    }
    assert pending["questions"][1]["type"] == "long_text"
    assert pending["questions"][1]["points"] is None

    assert telegram.form_creation["pending_id"] == payload["pending_id"]
    assert telegram.form_creation["is_quiz"] is True
    assert service.created is None  # nothing is created before confirmation


@pytest.mark.asyncio
async def test_create_form_accepts_explicit_publish_request():
    registry, service, telegram = build_registry()

    result = await registry.call(
        "create_form",
        ToolContext(chat_id=1, user_id=42, call_id="call-publish"),
        {
            "title": "Опубликовать тест",
            "is_quiz": True,
            "publish": True,
            "questions": [],
        },
    )

    payload = json.loads(result.content)
    pending = service.get_pending_form(payload["pending_id"])
    assert pending["publish"] is True
    assert telegram.form_creation["publish"] is True


@pytest.mark.asyncio
async def test_create_form_rejects_missing_title():
    registry, service, _ = build_registry()

    with pytest.raises(ToolArgumentsError, match="title is required"):
        await registry.call(
            "create_form",
            ToolContext(chat_id=1, user_id=42, call_id="call-2"),
            {"description": "без названия"},
        )

    assert service._pending_forms == {}


@pytest.mark.asyncio
async def test_create_form_rejects_unknown_question_type():
    registry, service, _ = build_registry()

    with pytest.raises(ToolArgumentsError, match="question type"):
        await registry.call(
            "create_form",
            ToolContext(chat_id=1, user_id=42, call_id="call-3"),
            {
                "title": "Тест",
                "questions": [{"title": "Вопрос", "type": "scale"}],
            },
        )

    assert service._pending_forms == {}


@pytest.mark.asyncio
async def test_create_form_rejects_correct_answer_outside_options():
    registry, service, _ = build_registry()

    with pytest.raises(ToolArgumentsError, match="exactly match one of the options"):
        await registry.call(
            "create_form",
            ToolContext(chat_id=1, user_id=42, call_id="call-4"),
            {
                "title": "Тест",
                "questions": [
                    {
                        "title": "Вопрос",
                        "type": "checkbox",
                        "options": ["а", "б"],
                        "correct_answers": ["в"],
                    }
                ],
            },
        )

    assert service._pending_forms == {}


@pytest.mark.asyncio
async def test_create_form_rejects_options_for_text_question():
    registry, _, _ = build_registry()

    with pytest.raises(ToolArgumentsError, match="not allowed for the short_text"):
        await registry.call(
            "create_form",
            ToolContext(chat_id=1, user_id=42, call_id="call-5"),
            {
                "title": "Тест",
                "questions": [
                    {"title": "Вопрос", "type": "short_text", "options": ["а"]}
                ],
            },
        )


@pytest.mark.asyncio
async def test_add_form_question_holds_pending_with_form_title():
    registry, service, telegram = build_registry()

    result = await registry.call(
        "add_form_question",
        ToolContext(chat_id=1, user_id=42, call_id="call-6"),
        {
            "form_id": "form-1",
            "title": "Новый вопрос",
            "type": "dropdown",
            "options": ["а", "б", "в"],
        },
    )

    payload = json.loads(result.content)
    assert payload["status"] == "paused"

    pending = service.get_pending_question(payload["pending_id"])
    assert pending["form_id"] == "form-1"
    assert pending["form_title"] == "Тест по алгебре"
    assert pending["question"]["type"] == "dropdown"

    assert telegram.form_question["form_title"] == "Тест по алгебре"
    assert service.question_added is None  # not added before confirmation


@pytest.mark.asyncio
async def test_publish_form_holds_pending():
    registry, service, telegram = build_registry()

    result = await registry.call(
        "publish_form",
        ToolContext(chat_id=1, user_id=42, call_id="call-7"),
        {"form_id": "form-1"},
    )

    payload = json.loads(result.content)
    assert payload["status"] == "paused"

    pending = service.get_pending_publish(payload["pending_id"])
    assert pending["form_id"] == "form-1"
    assert pending["form_title"] == "Тест по алгебре"

    assert telegram.form_publish["form_title"] == "Тест по алгебре"
    assert service.published is None  # not published before confirmation


@pytest.mark.asyncio
async def test_get_form_returns_serialized_form():
    registry, _, _ = build_registry()

    result = await registry.call(
        "get_form",
        ToolContext(chat_id=1, user_id=42, call_id="call-8"),
        {"form_id": "form-1"},
    )

    payload = json.loads(result.content)
    assert payload["form"]["form_id"] == "form-1"
    assert payload["form"]["title"] == "Тест по алгебре"
    assert payload["form"]["is_quiz"] is True
    assert payload["form"]["questions_total"] == 0
    assert "items" not in payload["form"]
    assert payload["publish"] == {
        "is_published": True,
        "is_accepting_responses": True,
        "student_link_usable": True,
        "responder_uri": "https://docs.google.com/forms/d/form-1/viewform",
        "edit_uri": "https://docs.google.com/forms/d/form-1/edit",
    }


@pytest.mark.asyncio
async def test_get_form_reports_closed_form_link_as_unusable():
    class ClosedFormsService(FakeFormsService):
        async def get_form(self, telegram_id, form_id):
            # Google returns isPublished=true and omits isAcceptingResponses
            # for a form whose responses are closed.
            return Form.model_validate({
                "formId": form_id,
                "info": {"title": "Закрытый тест"},
                "publishSettings": {"publishState": {"isPublished": True}},
                "responderUri": f"https://docs.google.com/forms/d/{form_id}/viewform",
            })

    registry, _, _ = build_registry(service=ClosedFormsService())

    result = await registry.call(
        "get_form",
        ToolContext(chat_id=1, user_id=42, call_id="call-10"),
        {"form_id": "form-1"},
    )

    payload = json.loads(result.content)
    assert payload["publish"]["is_published"] is True
    assert payload["publish"]["is_accepting_responses"] is False
    assert payload["publish"]["student_link_usable"] is False


@pytest.mark.asyncio
async def test_get_form_responses_returns_empty_list():
    registry, _, _ = build_registry()

    result = await registry.call(
        "get_form_responses",
        ToolContext(chat_id=1, user_id=42, call_id="call-9"),
        {"form_id": "form-1"},
    )

    payload = json.loads(result.content)
    assert payload["responses"] == []
    assert payload["total_responses"] == 0


@pytest.mark.asyncio
async def test_get_form_summarizes_questions_unless_explicitly_requested():
    class FormWithQuestions(FakeFormsService):
        async def get_form(self, telegram_id, form_id):
            return Form.model_validate({
                "formId": "form-1",
                "info": {"title": "Тест", "description": "Демо"},
                "settings": {"quizSettings": {"isQuiz": True}},
                "publishSettings": {
                    "publishState": {
                        "isPublished": True,
                        "isAcceptingResponses": True,
                    }
                },
                "responderUri": "https://docs.google.com/forms/d/form-1/viewform",
                "items": [
                    {
                        "itemId": "item-1",
                        "title": "2 + 2?",
                        "questionItem": {
                            "question": {
                                "questionId": "q-1",
                                "required": True,
                                "grading": {"pointValue": 2},
                                "choiceQuestion": {
                                    "type": "RADIO",
                                    "options": [{"value": "3"}, {"value": "4"}],
                                },
                            }
                        },
                    },
                    {
                        "itemId": "item-2",
                        "title": "Столица Франции?",
                        "questionItem": {
                            "question": {
                                "questionId": "q-2",
                                "choiceQuestion": {
                                    "type": "RADIO",
                                    "options": [{"value": "Париж"}],
                                },
                            }
                        },
                    },
                ],
            })

    registry, _, _ = build_registry(service=FormWithQuestions())

    result = await registry.call(
        "get_form",
        ToolContext(chat_id=1, user_id=42, call_id="call-11"),
        {"form_id": "form-1"},
    )
    payload = json.loads(result.content)["form"]
    assert payload["questions_total"] == 2
    assert payload["total_points"] == 2
    assert len(payload["questions_preview"]) == 2
    assert "questions" not in payload
    assert "items" not in payload

    detailed = await registry.call(
        "get_form",
        ToolContext(chat_id=1, user_id=42, call_id="call-12"),
        {"form_id": "form-1", "include_items": True},
    )
    questions = json.loads(detailed.content)["form"]["questions"]
    assert [question["question_id"] for question in questions] == ["q-1", "q-2"]
    assert questions[0]["options_count"] == 2
    # Options and grading payloads stay out of the tool result.
    assert "options" not in questions[0]
    assert "grading" not in questions[0]
