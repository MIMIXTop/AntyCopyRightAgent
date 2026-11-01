import pytest
from pydantic import ValidationError

from app.api.forms.models import (
    Form,
    FormItemModel,
    FormResponsesList,
    Question,
    build_enable_quiz_request,
    build_publish_request,
)


QUIZ_FORM_PAYLOAD = {
    "formId": "form-123",
    "info": {
        "title": "Тест по алгебре",
        "description": "Вариант 1",
        "documentTitle": "Тест по алгебре (вариант 1)",
    },
    "settings": {
        "languageCode": "ru",
        "emailCollectionType": "VERIFIED",
        "quizSettings": {"isQuiz": True},
    },
    "publishState": {
        "isPublished": True,
        "isAcceptingResponses": True,
    },
    "revisionId": "00000001",
    "responderUri": "https://docs.google.com/forms/d/form-123/viewform",
    "items": [
        {
            "itemId": "item-1",
            "title": "Сколько будет 2 + 2?",
            "questionItem": {
                "question": {
                    "questionId": "q-1",
                    "required": True,
                    "grading": {
                        "pointValues": 5,
                        "correctAnswers": {"answers": [{"value": "4"}]},
                    },
                    "choiceQuestion": {
                        "type": "RADIO",
                        "options": [{"value": "3"}, {"value": "4"}],
                        "shuffle": True,
                    },
                }
            },
        }
    ],
}


def test_form_parses_quiz_payload_with_aliases():
    form = Form.model_validate(QUIZ_FORM_PAYLOAD)

    assert form.form_id == "form-123"
    assert form.info.title == "Тест по алгебре"
    assert form.info.document_title == "Тест по алгебре (вариант 1)"
    assert form.is_quiz is True
    assert form.publish_state is not None
    assert form.publish_state.is_published is True
    assert form.responder_uri == "https://docs.google.com/forms/d/form-123/viewform"
    assert form.edit_uri == "https://docs.google.com/forms/d/form-123/edit"

    item = form.items[0]
    assert item.item_id == "item-1"
    question = item.question
    assert question is not None
    assert question.question_id == "q-1"
    assert question.required is True
    assert question.grading is not None
    assert question.grading.point_values == 5
    assert question.grading.correct_answers.answers[0].value == "4"
    assert question.choice_question is not None
    assert question.choice_question.type.value == "RADIO"
    assert [option.value for option in question.choice_question.options] == ["3", "4"]


def test_form_parses_minimal_payload():
    form = Form.model_validate({"formId": "only-id"})

    assert form.form_id == "only-id"
    assert form.info.title == ""
    assert form.settings is None
    assert form.publish_state is None
    assert form.items == []
    assert form.is_quiz is False
    assert form.responder_uri is None


def test_question_requires_exactly_one_kind():
    with pytest.raises(ValidationError):
        Question.model_validate({"questionId": "q-1"})

    with pytest.raises(ValidationError):
        Question.model_validate(
            {
                "textQuestion": {"paragraph": False},
                "choiceQuestion": {"type": "RADIO", "options": [{"value": "a"}]},
            }
        )

    question = Question.model_validate({"textQuestion": {"paragraph": True}})
    assert question.text_question.paragraph is True


def test_create_item_request_builds_location_and_strips_read_only_fields():
    item = FormItemModel.model_validate(
        {
            "itemId": "item-1",
            "title": "Выберите верный ответ",
            "questionItem": {
                "question": {
                    "questionId": "q-1",
                    "required": True,
                    "grading": {
                        "pointValues": 2,
                        "correctAnswers": {"answers": [{"value": "б"}]},
                    },
                    "choiceQuestion": {
                        "type": "CHECKBOX",
                        "options": [{"value": "а"}, {"value": "б"}],
                    },
                }
            },
        }
    )

    request = item.to_create_item_request(index=3)

    assert request == {
        "createItem": {
            "item": {
                "title": "Выберите верный ответ",
                "questionItem": {
                    "question": {
                        "required": True,
                        "grading": {
                            "pointValues": 2,
                            "correctAnswers": {"answers": [{"value": "б"}]},
                        },
                        "choiceQuestion": {
                            "type": "CHECKBOX",
                            "options": [{"value": "а"}, {"value": "б"}],
                        },
                    }
                },
            },
            "location": {"index": 3},
        }
    }


def test_builders_produce_batch_update_and_publish_bodies():
    assert build_enable_quiz_request() == {
        "updateFormSettings": {
            "settings": {"quizSettings": {"isQuiz": True}},
            "updateMask": "quizSettings",
        }
    }
    assert build_publish_request() == {"updateMask": "publishState"}


def test_responses_list_parses_answers_by_question_id():
    payload = {
        "totalResponses": 2,
        "responses": [
            {
                "responseId": "r-1",
                "createTime": "2026-01-15T10:00:00Z",
                "lastSubmittedTime": "2026-01-15T10:05:00Z",
                "respondentEmail": "student@example.com",
                "answers": {
                    "q-1": {
                        "questionId": "q-1",
                        "textAnswers": {"answers": [{"value": "4"}]},
                    }
                },
                "totalScore": 5.0,
            },
            {"responseId": "r-2", "answers": {}},
        ],
    }

    parsed = FormResponsesList.model_validate(payload)

    assert parsed.total_responses == 2
    first = parsed.responses[0]
    assert first.respondent_email == "student@example.com"
    assert first.create_time is not None
    assert first.total_score == 5.0
    assert first.answer_values("q-1") == ["4"]
    assert first.answer_values("missing-question") == []
    assert parsed.responses[1].answer_values("q-1") == []
