import pytest

from app.api.forms.models import Form
from app.api.forms.service import FormsService


class FakeFormsClient:
    def __init__(self):
        self.created = None
        self.batches = []

    async def create_form(self, telegram_id, title, document_title=""):
        self.created = {
            "telegram_id": telegram_id,
            "title": title,
            "document_title": document_title,
        }
        return Form.model_validate(
            {
                "formId": "form-1",
                "info": {"title": title, "documentTitle": document_title},
                "responderUri": "https://docs.google.com/forms/d/form-1/viewform",
            }
        )

    async def batch_update(self, telegram_id, form_id, requests):
        self.batches.append(
            {"telegram_id": telegram_id, "form_id": form_id, "requests": requests}
        )
        return {}


@pytest.mark.asyncio
async def test_create_form_sets_description_and_quiz_with_batch_update():
    client = FakeFormsClient()
    service = FormsService(client)

    form = await service.create_form_with_questions(
        telegram_id=42,
        title="Тест",
        description="Вариант 1",
        is_quiz=True,
        questions=[
            {
                "title": "Сколько будет 2 + 2?",
                "type": "radio",
                "options": ["3", "4"],
                "correct_answers": ["4"],
            }
        ],
    )

    # forms.create only receives the fields Google copies.
    assert client.created == {
        "telegram_id": 42,
        "title": "Тест",
        "document_title": "Тест",
    }
    assert form.form_id == "form-1"

    # Description and quiz mode share the first batchUpdate.
    setup = client.batches[0]
    assert setup["form_id"] == "form-1"
    assert setup["requests"] == [
        {
            "updateFormInfo": {
                "info": {"description": "Вариант 1"},
                "updateMask": "description",
            }
        },
        {
            "updateSettings": {
                "settings": {"quizSettings": {"isQuiz": True}},
                "updateMask": "quizSettings",
            }
        },
    ]

    items = client.batches[1]["requests"]
    assert len(items) == 1
    item = items[0]["createItem"]
    assert item["location"] == {"index": 0}
    assert item["item"]["title"] == "Сколько будет 2 + 2?"
    assert item["item"]["questionItem"]["question"]["choiceQuestion"]["options"] == [
        {"value": "3"},
        {"value": "4"},
    ]


def test_build_question_item_uses_fields_accepted_by_google():
    # Google rejects pointValues (the field is pointValue) and DROPDOWN (the
    # enum value is DROP_DOWN); both used to fail with 400 INVALID_ARGUMENT.
    from app.api.forms.service import build_question_item

    dropdown = build_question_item(
        {
            "title": "Какой стандарт ввёл co_await?",
            "type": "dropdown",
            "options": ["C++20", "C++17"],
            "correct_answers": ["C++20"],
            "points": 2,
            "required": True,
        }
    ).to_create_item_request(0)

    question = dropdown["createItem"]["item"]["questionItem"]["question"]
    assert question["choiceQuestion"]["type"] == "DROP_DOWN"
    assert question["grading"] == {
        "pointValue": 2,
        "correctAnswers": {"answers": [{"value": "C++20"}]},
    }

    text = build_question_item(
        {
            "title": "Структура данных в основе std::map",
            "type": "short_text",
            "correct_answers": ["Красно-чёрное дерево"],
            "points": 1,
            "required": True,
        }
    ).to_create_item_request(1)

    text_question = text["createItem"]["item"]["questionItem"]["question"]
    assert text_question["textQuestion"] == {"paragraph": False}
    assert text_question["grading"]["pointValue"] == 1


@pytest.mark.asyncio
async def test_create_form_without_description_skips_update_form_info():
    client = FakeFormsClient()
    service = FormsService(client)

    await service.create_form_with_questions(
        telegram_id=42,
        title="Тест",
        is_quiz=True,
    )

    assert client.batches == [
        {
            "telegram_id": 42,
            "form_id": "form-1",
            "requests": [
                {
                    "updateSettings": {
                        "settings": {"quizSettings": {"isQuiz": True}},
                        "updateMask": "quizSettings",
                    }
                }
            ],
        }
    ]


@pytest.mark.asyncio
async def test_create_empty_form_makes_no_batch_update():
    client = FakeFormsClient()
    service = FormsService(client)

    await service.create_form_with_questions(
        telegram_id=42,
        title="Пустая форма",
    )

    assert client.created == {
        "telegram_id": 42,
        "title": "Пустая форма",
        "document_title": "Пустая форма",
    }
    assert client.batches == []
