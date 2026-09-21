import json

from app.core.errors import ToolArgumentsError
from app.agent.models import ToolContext, ToolResult
from app.classroom.service import ClassroomService
from app.tools.loader import load_schema


def register_classroom_tools(registry, classroom: ClassroomService) -> None:
    async def get_students(context: ToolContext, args: dict):
        telegram_id = context.user_id

        if not isinstance(telegram_id, int):
            raise ToolArgumentsError(
                "get_students_list",
                "active Telegram user ID is required"
            )

        course_id = args.get("course_id")
        if not isinstance(course_id, int):
            raise ToolArgumentsError(
                "get_students_list",
                "active Course ID is required"
            )
        students = await classroom.get_students(telegram_id, course_id)
        return ToolResult(
            call_id=context.call_id,
            content=json.dumps(
                {"students": [item.model_dump() for item in students]},
                ensure_ascii=False
            )
        )

    async def get_courses(context: ToolContext, args: dict):
        telegram_id = context.user_id

        if not isinstance(telegram_id, int):
            raise ToolArgumentsError(
                "get_students_list",
                "active Telegram user ID is required"
            )

        courses = await classroom.get_structure(telegram_id)
        return ToolResult(
            call_id=context.call_id,
            content=json.dumps(
                {"courses": [item.model_dump() for item in courses]},
            )
        )


    registry.register(
        "get_students_list",
        get_students,
        load_schema("get_students_list")
    )
    registry.register(
        "get_courses",
        get_courses,
        load_schema("get_courses")
    )


