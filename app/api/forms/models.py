from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FormModel(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
    )


class ChoiceQuestionType(str, Enum):
    RADIO = "RADIO"
    CHECKBOX = "CHECKBOX"
    DROP_DOWN = "DROP_DOWN"


class EmailCollectionType(str, Enum):
    EMAIL_COLLECTION_TYPE_UNSPECIFIED = "EMAIL_COLLECTION_TYPE_UNSPECIFIED"
    DO_NOT_COLLECT = "DO_NOT_COLLECT"
    VERIFIED = "VERIFIED"
    RESPONDER_INPUT = "RESPONDER_INPUT"


class FormInfoModel(FormModel):
    title: str = ""
    description: str = ""
    document_title: str = Field(default="", alias="documentTitle")


class QuizSettings(FormModel):
    is_quiz: bool = Field(default=False, alias="isQuiz")


class FormSettings(FormModel):
    language_code: str | None = Field(default=None, alias="languageCode")
    email_collection_type: EmailCollectionType | None = Field(
        default=None, alias="emailCollectionType"
    )
    quiz_settings: QuizSettings | None = Field(default=None, alias="quizSettings")
    requires_login: bool | None = Field(default=None, alias="requiresLogin")
    limit_one_response_per_user: bool | None = Field(
        default=None, alias="limitOneResponsePerUser"
    )
    shuffling_questions: bool | None = Field(default=None, alias="shufflingQuestions")


class PublishState(FormModel):
    is_published: bool = Field(default=False, alias="isPublished")
    # Google omits isAcceptingResponses for a form that is published but closed.
    is_accepting_responses: bool = Field(default=False, alias="isAcceptingResponses")
    is_quiz_published: bool = Field(default=False, alias="isQuizPublished")


class PublishSettings(FormModel):
    publish_state: PublishState | None = Field(default=None, alias="publishState")


class Answer(FormModel):
    value: str


class CorrectAnswers(FormModel):
    answers: list[Answer] = Field(default_factory=list)


class Grading(FormModel):
    # Google calls this field pointValue (singular) and it is a single int.
    point_value: int = Field(default=0, alias="pointValue")
    correct_answers: CorrectAnswers | None = Field(default=None, alias="correctAnswers")


class TextQuestion(FormModel):
    paragraph: bool = False


class ChoiceOption(FormModel):
    value: str
    is_other: bool | None = Field(default=None, alias="isOther")


class ChoiceQuestion(FormModel):
    type: ChoiceQuestionType = ChoiceQuestionType.RADIO
    options: list[ChoiceOption] = Field(default_factory=list)
    shuffle: bool | None = None


class Question(FormModel):
    question_id: str | None = Field(default=None, alias="questionId")
    required: bool = False
    grading: Grading | None = None
    text_question: TextQuestion | None = Field(default=None, alias="textQuestion")
    choice_question: ChoiceQuestion | None = Field(default=None, alias="choiceQuestion")

    @model_validator(mode="after")
    def _require_single_question_kind(self):
        kinds = (self.text_question, self.choice_question)
        if sum(kind is not None for kind in kinds) != 1:
            raise ValueError(
                "question must contain exactly one of textQuestion or choiceQuestion"
            )
        return self


class Image(FormModel):
    source_uri: str | None = Field(default=None, alias="sourceUri")
    width: int | None = None
    height: int | None = None
    alt_text: str | None = Field(default=None, alias="altText")


class QuestionItem(FormModel):
    question: Question | None = None
    image: Image | None = None


class FormItemModel(FormModel):
    item_id: str | None = Field(default=None, alias="itemId")
    title: str = ""
    description: str = ""
    question_item: QuestionItem | None = Field(default=None, alias="questionItem")

    @property
    def question(self) -> Question | None:
        return self.question_item.question if self.question_item else None

    def to_create_item_request(self, index: int) -> dict[str, Any]:
        """Build a single batchUpdate request that inserts this item at `index`."""
        item_payload = self.model_dump(mode="json", by_alias=True, exclude_none=True)
        item_payload.pop("itemId", None)
        if not item_payload.get("description"):
            item_payload.pop("description", None)
        question_payload = item_payload.get("questionItem", {}).get("question")
        if isinstance(question_payload, dict):
            question_payload.pop("questionId", None)
        return {
            "createItem": {
                "item": item_payload,
                "location": {"index": index},
            }
        }


class Form(FormModel):
    form_id: str = Field(alias="formId")
    info: FormInfoModel = Field(default_factory=FormInfoModel)
    settings: FormSettings | None = None
    publish_settings: PublishSettings | None = Field(
        default=None, alias="publishSettings"
    )
    revision_id: str | None = Field(default=None, alias="revisionId")
    responder_uri: str | None = Field(default=None, alias="responderUri")
    items: list[FormItemModel] = Field(default_factory=list)

    @property
    def is_quiz(self) -> bool:
        if self.settings is None or self.settings.quiz_settings is None:
            return False
        return self.settings.quiz_settings.is_quiz

    @property
    def publish_state(self) -> PublishState | None:
        """Published state regardless of where Google nests it."""
        if self.publish_settings is not None:
            return self.publish_settings.publish_state
        return None

    @property
    def is_published(self) -> bool:
        state = self.publish_state
        return bool(state and state.is_published)

    @property
    def is_accepting_responses(self) -> bool:
        state = self.publish_state
        return bool(state and state.is_published and state.is_accepting_responses)

    @property
    def edit_uri(self) -> str | None:
        if not self.form_id:
            return None
        return f"https://docs.google.com/forms/d/{self.form_id}/edit"

    @property
    def student_uri(self) -> str | None:
        """Responder link, but only when it actually works for students."""
        return self.responder_uri if self.is_accepting_responses else None


class TextAnswers(FormModel):
    answers: list[Answer] = Field(default_factory=list)


class ResponseAnswer(FormModel):
    question_id: str | None = Field(default=None, alias="questionId")
    text_answers: TextAnswers | None = Field(default=None, alias="textAnswers")


class FormResponse(FormModel):
    response_id: str | None = Field(default=None, alias="responseId")
    create_time: datetime | None = Field(default=None, alias="createTime")
    last_submitted_time: datetime | None = Field(default=None, alias="lastSubmittedTime")
    respondent_email: str | None = Field(default=None, alias="respondentEmail")
    answers: dict[str, ResponseAnswer] = Field(default_factory=dict)
    total_score: float | None = Field(default=None, alias="totalScore")

    def answer_values(self, question_id: str) -> list[str]:
        answer = self.answers.get(question_id)
        if answer is None or answer.text_answers is None:
            return []
        return [item.value for item in answer.text_answers.answers]


class FormResponsesList(FormModel):
    responses: list[FormResponse] = Field(default_factory=list)
    total_responses: int | None = Field(default=None, alias="totalResponses")


def build_update_form_info_request(
        *,
        title: str = "",
        description: str = "",
        document_title: str = "",
) -> dict[str, Any]:
    """batchUpdate request that edits form info fields.

    ``forms.create`` only copies ``title`` and ``documentTitle``; the
    description has to be applied afterwards. The update mask names the fields
    relative to ``info`` (the root is implied by the API).
    """
    info: dict[str, str] = {}
    fields: list[str] = []
    for field, value in (
        ("title", title),
        ("description", description),
        ("documentTitle", document_title),
    ):
        if value:
            info[field] = value
            fields.append(field)
    if not fields:
        raise ValueError("at least one form info field is required")
    return {
        "updateFormInfo": {
            "info": info,
            "updateMask": ",".join(fields),
        }
    }


def build_enable_quiz_request() -> dict[str, Any]:
    """batchUpdate request that switches the form into quiz mode."""
    return {
        "updateSettings": {
            "settings": {"quizSettings": {"isQuiz": True}},
            "updateMask": "quizSettings",
        }
    }


def build_publish_request(
        *,
        is_published: bool = True,
        is_accepting_responses: bool = True,
        update_mask: str = "publishState",
) -> dict[str, Any]:
    """Body for the :setPublishSettings endpoint.

    Google Forms has no ``:publish`` method; publication is a publish-settings
    update. A form is only usable by students when both ``isPublished`` and
    ``isAcceptingResponses`` are true.
    """
    return {
        "publishSettings": {
            "publishState": {
                "isPublished": is_published,
                "isAcceptingResponses": is_accepting_responses,
            }
        },
        "updateMask": update_mask,
    }
