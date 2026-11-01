import json

from app.agent.models import ToolContext, ToolResult
from app.api.forms.service import CHOICE_TYPES, TEXT_TYPES, FormsService
from app.api.telegram.service import TelegramService
from app.core.errors import ToolArgumentsError
from app.core.logging import logger
from app.tools.loader import load_schema

QUESTION_TYPES = CHOICE_TYPES | TEXT_TYPES


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
        raw_questions = args.get("questions") or []

        if not isinstance(title, str) or not title.strip():
            raise ToolArgumentsError("create_form", "title is required and must be a non-empty string")
        if not isinstance(description, str):
            raise ToolArgumentsError("create_form", "description must be a string")
        if not isinstance(is_quiz, bool):
            raise ToolArgumentsError("create_form", "is_quiz must be a boolean")
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
            questions=questions,
        )

        await telegram.request_form_creation(
            chat_id=context.chat_id,
            pending_id=pending_id,
            title=title.strip(),
            description=description,
            is_quiz=is_quiz,
            questions=questions,
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
        )

        await telegram.request_form_question(
            chat_id=context.chat_id,
            pending_id=pending_id,
            form_title=form.info.title,
            question=question,
        )

        return _paused_result(context.call_id, pending_id)

    async def publish_form_tool(context: ToolContext, args: dict) -> ToolResult:
        form_id = _require_form_id("publish_form", args.get("form_id"))

        form = await forms.get_form(context.user_id, form_id)

        pending_id = forms.hold_publish(
            telegram_id=context.user_id,
            form_id=form_id,
            form_title=form.info.title,
        )

        await telegram.request_form_publish(
            chat_id=context.chat_id,
            pending_id=pending_id,
            form_title=form.info.title,
        )

        return _paused_result(context.call_id, pending_id)

    async def get_form_tool(context: ToolContext, args: dict) -> ToolResult:
        form_id = _require_form_id("get_form", args.get("form_id"))
        form = await forms.get_form(context.user_id, form_id)
        return ToolResult(
            call_id=context.call_id,
            content=json.dumps(
                {"form": form.model_dump(mode="json")},
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
