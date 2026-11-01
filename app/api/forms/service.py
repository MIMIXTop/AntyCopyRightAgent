import uuid

from app.api.forms.client import FormsClient
from app.api.forms.models import (
    Answer,
    ChoiceOption,
    ChoiceQuestion,
    ChoiceQuestionType,
    CorrectAnswers,
    Form,
    FormItemModel,
    FormResponsesList,
    Grading,
    Question,
    QuestionItem,
    TextQuestion,
    build_enable_quiz_request,
)
from app.core.errors import ValidationError
from app.core.logging import logger

CHOICE_TYPES = {"radio", "checkbox", "dropdown"}
TEXT_TYPES = {"short_text", "long_text"}

_QUESTION_TYPE_TO_API = {
    "radio": ChoiceQuestionType.RADIO,
    "checkbox": ChoiceQuestionType.CHECKBOX,
    "dropdown": ChoiceQuestionType.DROPDOWN,
}

# The Forms API accepts at most 50 requests per batchUpdate call.
_BATCH_LIMIT = 50


def build_question_item(spec: dict) -> FormItemModel:
    """Convert a normalized question spec into a Forms API item."""
    question_type = spec["type"]
    required = bool(spec.get("required", False))
    correct_answers = list(spec.get("correct_answers") or [])
    points = spec.get("points")

    grading = None
    if correct_answers:
        grading = Grading(
            point_values=int(points or 1),
            correct_answers=CorrectAnswers(
                answers=[Answer(value=value) for value in correct_answers]
            ),
        )

    if question_type in TEXT_TYPES:
        question = Question(
            required=required,
            grading=grading,
            text_question=TextQuestion(paragraph=question_type == "long_text"),
        )
    else:
        question = Question(
            required=required,
            grading=grading,
            choice_question=ChoiceQuestion(
                type=_QUESTION_TYPE_TO_API[question_type],
                options=[
                    ChoiceOption(value=value)
                    for value in spec.get("options") or []
                ],
            ),
        )

    return FormItemModel(
        title=spec["title"],
        question_item=QuestionItem(question=question),
    )


def _chunked(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


class FormsService:
    def __init__(self, client: FormsClient):
        self._client = client
        self._pending_forms: dict[str, dict] = {}
        self._pending_questions: dict[str, dict] = {}
        self._pending_publishes: dict[str, dict] = {}
        logger.info("FormsService initialized")

    # ---------- pending stores (confirmation flow) ----------

    def hold_form_creation(
            self,
            telegram_id: int,
            title: str,
            description: str,
            is_quiz: bool,
            questions: list[dict],
    ) -> str:
        pending_id = str(uuid.uuid4())[:8]
        self._pending_forms[pending_id] = {
            "telegram_id": telegram_id,
            "title": title,
            "description": description,
            "is_quiz": is_quiz,
            "questions": questions,
        }
        return pending_id

    def get_pending_form(self, pending_id: str) -> dict | None:
        return self._pending_forms.get(pending_id)

    def remove_pending_form(self, pending_id: str) -> None:
        self._pending_forms.pop(pending_id, None)

    def hold_question_addition(
            self,
            telegram_id: int,
            form_id: str,
            form_title: str,
            question: dict,
    ) -> str:
        pending_id = str(uuid.uuid4())[:8]
        self._pending_questions[pending_id] = {
            "telegram_id": telegram_id,
            "form_id": form_id,
            "form_title": form_title,
            "question": question,
        }
        return pending_id

    def get_pending_question(self, pending_id: str) -> dict | None:
        return self._pending_questions.get(pending_id)

    def remove_pending_question(self, pending_id: str) -> None:
        self._pending_questions.pop(pending_id, None)

    def hold_publish(self, telegram_id: int, form_id: str, form_title: str) -> str:
        pending_id = str(uuid.uuid4())[:8]
        self._pending_publishes[pending_id] = {
            "telegram_id": telegram_id,
            "form_id": form_id,
            "form_title": form_title,
        }
        return pending_id

    def get_pending_publish(self, pending_id: str) -> dict | None:
        return self._pending_publishes.get(pending_id)

    def remove_pending_publish(self, pending_id: str) -> None:
        self._pending_publishes.pop(pending_id, None)

    # ---------- API operations ----------

    async def create_form_with_questions(
            self,
            telegram_id: int,
            title: str,
            description: str = "",
            is_quiz: bool = False,
            questions: list[dict] | None = None,
    ) -> Form:
        logger.info(
            "FormsService.create_form_with_questions called: telegram_id=%s title=%r is_quiz=%s questions=%s",
            telegram_id,
            title,
            is_quiz,
            len(questions or []),
        )
        form = await self._client.create_form(
            telegram_id=telegram_id,
            title=title,
            description=description,
            document_title=title,
        )

        if is_quiz:
            await self._client.batch_update(
                telegram_id=telegram_id,
                form_id=form.form_id,
                requests=[build_enable_quiz_request()],
            )

        if questions:
            requests = [
                build_question_item(spec).to_create_item_request(index)
                for index, spec in enumerate(questions)
            ]
            for chunk in _chunked(requests, _BATCH_LIMIT):
                await self._client.batch_update(
                    telegram_id=telegram_id,
                    form_id=form.form_id,
                    requests=chunk,
                )

        return form

    async def add_question(
            self,
            telegram_id: int,
            form_id: str,
            question_spec: dict,
    ) -> dict:
        logger.info(
            "FormsService.add_question called: telegram_id=%s form_id=%s title=%r",
            telegram_id,
            form_id,
            question_spec.get("title"),
        )
        form = await self._client.get_form(telegram_id, form_id)
        index = len(form.items)
        request = build_question_item(question_spec).to_create_item_request(index)
        return await self._client.batch_update(
            telegram_id=telegram_id,
            form_id=form_id,
            requests=[request],
        )

    async def publish_form(self, telegram_id: int, form_id: str) -> dict:
        logger.info(
            "FormsService.publish_form called: telegram_id=%s form_id=%s",
            telegram_id,
            form_id,
        )
        return await self._client.publish(telegram_id=telegram_id, form_id=form_id)

    async def get_form(self, telegram_id: int, form_id: str) -> Form:
        return await self._client.get_form(telegram_id, form_id)

    async def get_responses(self, telegram_id: int, form_id: str) -> FormResponsesList:
        return await self._client.get_responses(telegram_id, form_id)
