import json
from collections import Counter

from app.agent.models import ToolContext, ToolResult
from app.api.forms.service import CHOICE_TYPES, TEXT_TYPES, FormsService
from app.api.telegram.service import TelegramService
from app.core.errors import ToolArgumentsError
from app.core.logging import logger
from app.tools.loader import load_schema

QUESTION_TYPES = CHOICE_TYPES | TEXT_TYPES
# The model gets a compact form summary by default: dumping every item of a
# 70-question test wastes context and provokes long recaps in the chat.
QUESTION_PREVIEW_LIMIT = 5
TITLE_LIMIT = 160


def _trim(value: str | None, limit: int = TITLE_LIMIT) -> str:
    text = (value or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _question_kind(question) -> str:
    if question is None:
        return "UNKNOWN"
    if question.choice_question is not None:
        return question.choice_question.type.value
    if question.text_question is not None:
        return "PARAGRAPH" if question.text_question.paragraph else "SHORT_TEXT"
    return "UNKNOWN"


def _form_summary(form, *, include_items: bool = False) -> dict:
    """Compact, factual form view instead of a full item dump."""
    types: Counter[str] = Counter()
    total_points = 0
    questions = []
    for item in form.items:
        question = item.question
        kind = _question_kind(question)
        types[kind] += 1
        points = question.grading.point_value if question and question.grading else 0
        total_points += points
        questions.append(
            {
                "item_id": item.item_id,
                "question_id": question.question_id if question else None,
                "title": _trim(item.title),
                "type": kind,
                "required": bool(question and question.required),
                "points": points,
                "options_count": len(question.choice_question.options)
                if question and question.choice_question
                else 0,
            }
        )

    summary = {
        "form_id": form.form_id,
        "title": form.info.title,
        "description": _trim(form.info.description, 300),
        "is_quiz": form.is_quiz,
        "email_collection_type": (
            form.settings.email_collection_type.value
            if form.settings and form.settings.email_collection_type
            else None
        ),
        "questions_total": len(questions),
        "question_types": dict(types),
        "total_points": total_points,
    }
    if include_items:
        summary["questions"] = questions[:100]
        summary["questions_omitted"] = max(0, len(questions) - 100)
    else:
        summary["questions_preview"] = [
            {"title": item["title"], "type": item["type"]}
            for item in questions[:QUESTION_PREVIEW_LIMIT]
        ]
        summary["questions_omitted"] = max(
            0, len(questions) - QUESTION_PREVIEW_LIMIT
        )
    return summary


def _require_form_id(tool_name: str, value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolArgumentsError(tool_name, "form_id is required and must be a non-empty string")
    return value.strip()


def _parse_question_spec(tool_name: str, raw) -> dict:
    """Validate one question spec and return a normalized dict."""
    if not isinstance(raw, dict):
        raise ToolArgumentsError(tool_name, "each question must be an object")

    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ToolArgumentsError(tool_name, "question title is required and must be a non-empty string")

    question_type = raw.get("type")
    if not isinstance(question_type, str) or question_type not in QUESTION_TYPES:
        raise ToolArgumentsError(
            tool_name,
            "question type must be one of: radio, checkbox, dropdown, short_text, long_text",
        )

    options = raw.get("options") or []
    if not isinstance(options, list) or not all(
            isinstance(option, str) and option.strip() for option in options
    ):
        raise ToolArgumentsError(tool_name, "options must be a list of non-empty strings")

    correct_answers = raw.get("correct_answers") or []
    if not isinstance(correct_answers, list) or not all(
            isinstance(answer, str) and answer.strip() for answer in correct_answers
    ):
        raise ToolArgumentsError(tool_name, "correct_answers must be a list of non-empty strings")

    if question_type in CHOICE_TYPES:
        if not options:
            raise ToolArgumentsError(
                tool_name,
                f"options are required for the {question_type} question type",
            )
        unknown = [answer for answer in correct_answers if answer not in options]
        if unknown:
            raise ToolArgumentsError(
                tool_name,
                "each correct answer must exactly match one of the options",
            )
    elif options:
        raise ToolArgumentsError(
            tool_name,
            f"options are not allowed for the {question_type} question type",
        )

    points = raw.get("points")
    if points is not None:
        if not isinstance(points, int) or isinstance(points, bool) or points < 1:
            raise ToolArgumentsError(tool_name, "points must be an integer >= 1")
    if correct_answers and points is None:
        points = 1

    required = raw.get("required", False)
    if not isinstance(required, bool):
        raise ToolArgumentsError(tool_name, "required must be a boolean")

    return {
        "title": title.strip(),
        "type": question_type,
        "options": [option.strip() for option in options],
        "correct_answers": [answer.strip() for answer in correct_answers],
        "points": points,
        "required": required,
    }


def _paused_result(call_id: str, pending_id: str) -> ToolResult:
    return ToolResult(
        call_id=call_id,
        content=json.dumps(
            {
                "status": "paused",
                "reason": "waiting_for_user_confirmation",
                "pending_id": pending_id,
            },
            ensure_ascii=False,
        ),
        terminal=True,
    )


def register_forms_tools(
        registry,
        forms: FormsService,
        telegram: TelegramService,
) -> None:
    logger.info("Registering Google Forms tools")

    async def create_form_tool(context: ToolContext, args: dict) -> ToolResult:
        title = args.get("title")
        description = args.get("description", "")
        is_quiz = args.get("is_quiz", False)
        publish = args.get("publish", False)
        raw_questions = args.get("questions") or []

        if not isinstance(title, str) or not title.strip():
            raise ToolArgumentsError("create_form", "title is required and must be a non-empty string")
        if not isinstance(description, str):
            raise ToolArgumentsError("create_form", "description must be a string")
        if not isinstance(is_quiz, bool):
            raise ToolArgumentsError("create_form", "is_quiz must be a boolean")
        if not isinstance(publish, bool):
            raise ToolArgumentsError("create_form", "publish must be a boolean")
        if not isinstance(raw_questions, list):
            raise ToolArgumentsError("create_form", "questions must be a list")

        questions = [
            _parse_question_spec("create_form", raw_question)
            for raw_question in raw_questions
        ]

        pending_id = forms.hold_form_creation(
            telegram_id=context.user_id,
            title=title.strip(),
            description=description,
            is_quiz=is_quiz,
            publish=publish,
            questions=questions,
            chat_id=context.chat_id,
            chat_type=context.chat_type,
        )

        await telegram.request_form_creation(
            chat_id=context.chat_id,
            pending_id=pending_id,
            title=title.strip(),
            description=description,
            is_quiz=is_quiz,
            publish=publish,
            questions=questions,
            delivery=context.delivery,
        )

        return _paused_result(context.call_id, pending_id)

    async def add_form_question_tool(context: ToolContext, args: dict) -> ToolResult:
        form_id = _require_form_id("add_form_question", args.get("form_id"))
        question = _parse_question_spec("add_form_question", args)

        form = await forms.get_form(context.user_id, form_id)

        pending_id = forms.hold_question_addition(
            telegram_id=context.user_id,
            form_id=form_id,
            form_title=form.info.title,
            question=question,
            chat_id=context.chat_id,
            chat_type=context.chat_type,
        )

        await telegram.request_form_question(
            chat_id=context.chat_id,
            pending_id=pending_id,
            form_title=form.info.title,
            question=question,
            delivery=context.delivery,
        )

        return _paused_result(context.call_id, pending_id)

    async def publish_form_tool(context: ToolContext, args: dict) -> ToolResult:
        form_id = _require_form_id("publish_form", args.get("form_id"))

        form = await forms.get_form(context.user_id, form_id)

        pending_id = forms.hold_publish(
            telegram_id=context.user_id,
            form_id=form_id,
            form_title=form.info.title,
            chat_id=context.chat_id,
            chat_type=context.chat_type,
        )

        await telegram.request_form_publish(
            chat_id=context.chat_id,
            pending_id=pending_id,
            form_title=form.info.title,
            delivery=context.delivery,
        )

        return _paused_result(context.call_id, pending_id)

    async def get_form_tool(context: ToolContext, args: dict) -> ToolResult:
        form_id = _require_form_id("get_form", args.get("form_id"))
        include_items = args.get("include_items", False)
        if not isinstance(include_items, bool):
            raise ToolArgumentsError("get_form", "include_items must be a boolean")
        form = await forms.get_form(context.user_id, form_id)
        return ToolResult(
            call_id=context.call_id,
            content=json.dumps(
                {
                    "form": _form_summary(form, include_items=include_items),
                    "publish": {
                        "is_published": form.is_published,
                        "is_accepting_responses": form.is_accepting_responses,
                        "student_link_usable": form.student_uri is not None,
                        "responder_uri": form.responder_uri,
                        "edit_uri": form.edit_uri,
                    },
                },
                ensure_ascii=False,
            ),
        )

    async def get_form_responses_tool(context: ToolContext, args: dict) -> ToolResult:
        form_id = _require_form_id("get_form_responses", args.get("form_id"))
        responses = await forms.get_responses(context.user_id, form_id)
        return ToolResult(
            call_id=context.call_id,
            content=json.dumps(
                responses.model_dump(mode="json"),
                ensure_ascii=False,
                default=str,
            ),
        )

    registry.register("create_form", create_form_tool, load_schema("create_form"))
    registry.register("add_form_question", add_form_question_tool, load_schema("add_form_question"))
    registry.register("publish_form", publish_form_tool, load_schema("publish_form"))
    registry.register("get_form", get_form_tool, load_schema("get_form"))
    registry.register("get_form_responses", get_form_responses_tool, load_schema("get_form_responses"))
