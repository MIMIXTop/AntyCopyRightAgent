import json
from urllib.parse import urlparse

from app.core.errors import ToolArgumentsError
from app.agent.models import ToolContext, ToolResult
from app.classroom.service import ClassroomService
from app.telegram.service import TelegramService
from app.tools.loader import load_schema
from app.core.logging import logger


def register_classroom_tools(registry, classroom: ClassroomService, telegram: TelegramService) -> None:
    logger.info("Registering Classroom tools")
    async def get_students(context: ToolContext, args: dict):
        telegram_id = context.user_id

        if not isinstance(telegram_id, int):
            raise ToolArgumentsError(
                "get_students_list",
                "active Telegram user ID is required"
            )

        course_id = args.get("course_id")
        if not isinstance(course_id, str) or not course_id.strip():
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

    async def get_course_works(context: ToolContext, args: dict):
        telegram_id = context.user_id
        course_id = args.get("course_id")

        course_works = await classroom.get_assignments(telegram_id, course_id)
        return ToolResult(
            call_id=context.call_id,
            content=json.dumps(
                {"course_works": [item.model_dump() for item in course_works]},
            )
        )

    async def get_submissions(context: ToolContext, args: dict):
        telegram_id = context.user_id
        course_id = args.get("course_id")
        course_work_id = args.get("assignments_id")

        student_submissions = await classroom.get_submissions_status(telegram_id, course_id, course_work_id)

        return ToolResult(
            call_id=context.call_id,
            content=json.dumps(
                {"student_submissions": [item.model_dump() for item in student_submissions]},
            )
        )

    async def create_course(context: ToolContext, args: dict):
        telegram_id = context.user_id
        name = args.get("name")
        description = args.get("description", "")
        section = args.get("section")

        if not isinstance(name, str) or not name.strip():
            raise ToolArgumentsError(
                "create_course",
                "name is required and must be a non-empty string",
            )
        if not isinstance(description, str):
            raise ToolArgumentsError(
                "create_course",
                "description must be a string",
            )
        if section is not None and not isinstance(section, str):
            raise ToolArgumentsError(
                "create_course",
                "section must be a string",
            )

        result = await classroom.create_course(
            telegram_id=telegram_id,
            course_name=name,
            course_description=description,
            course_section=section
        )
        return ToolResult(
            call_id=context.call_id,
            content=json.dumps(
                {
                    "status": result.status,
                    "body": result.body,
                },
                ensure_ascii=False,
                default=str
            )
        )

    async def create_course_tool(context: ToolContext, args: dict):
        logger.info("create_course tool called: user_id=%s arguments=%s", context.user_id, args)
        name = args.get("name")
        description = args.get("description", "")
        section = args.get("section")

        if not isinstance(name, str) or not name.strip():
            raise ToolArgumentsError("create_course", "name is required and must be a non-empty string")
        if not isinstance(description, str):
            raise ToolArgumentsError("create_course", "description must be a string")
        if section is not None and not isinstance(section, str):
            raise ToolArgumentsError("create_course", "section must be a string")

        pending_id = classroom.hold_course_creation(
            telegram_id=context.user_id,
            course_name=name,
            course_description=description,
            course_section=section
        )

        await telegram.request_course_confirmation(
            chat_id=context.user_id,
            pending_id=pending_id,
            course_name=name
        )

        return ToolResult(
            call_id=context.call_id,
            content='{"status": "paused", "reason": "waiting_for_user_confirmation"}',
            terminal=True
        )

    async def create_course_announcement_tool(context: ToolContext, args: dict):
        course_id = args.get("course_id")
        text = args.get("text")
        state = args.get("state", "PUBLISHED")
        links = args.get("links", [])
        drive_file_ids = args.get("drive_file_ids", [])
        telegram_attachments = context.attachments

        if not isinstance(course_id, str) or not course_id.strip():
            raise ToolArgumentsError(
                "create_announcement",
                "course_id is required and must be a non-empty string",
            )
        if not isinstance(text, str) or not text.strip():
            raise ToolArgumentsError(
                "create_announcement",
                "text is required and must be a non-empty string",
            )
        if state not in {"PUBLISHED", "DRAFT"}:
            raise ToolArgumentsError("create_announcement", "state must be PUBLISHED or DRAFT")
        if not isinstance(links, list) or not all(isinstance(link, str) for link in links):
            raise ToolArgumentsError("create_announcement", "links must be a list of strings")
        if not all(urlparse(link).scheme in {"http", "https"} and urlparse(link).netloc for link in links):
            raise ToolArgumentsError("create_announcement", "links must contain valid HTTP(S) URLs")
        if not isinstance(drive_file_ids, list) or not all(
            isinstance(file_id, str) and file_id.strip() for file_id in drive_file_ids
        ):
            raise ToolArgumentsError("create_announcement", "drive_file_ids must be a list of non-empty strings")

        materials_payload = []

        for link in links:
            materials_payload.append({"link": {"url": link}})

        for file_id in drive_file_ids:
            if isinstance(file_id, str) and file_id.strip():
                materials_payload.append({
                    "driveFile": {
                        "driveFile": {"id": file_id.strip()},
                        "shareMode": "VIEW"
                    }
                })

        pending_id = classroom.hold_course_announcement(
            telegram_id=context.user_id,
            course_id=course_id,
            text=text,
            state=state,
            materials=materials_payload if materials_payload else None,
            telegram_attachments=telegram_attachments
        )


        course = await classroom.get_concrete_course(context.user_id, course_id)
        await telegram.request_course_announcement(chat_id=context.user_id, pending_id=pending_id, announcement_text=text, course_name=course.name)

        return ToolResult(
            call_id=context.call_id,
            content='{"status": "paused", "reason": "waiting_for_user_confirmation"}',
            terminal=True
        )

    async def create_course_work_tool(context: ToolContext, args: dict):
        course_id = args.get("course_id")
        title = args.get("title")
        description = args.get("description")
        max_points = args.get("max_points")
        due_date = args.get("due_date")
        due_time = args.get("due_time")
        links = args.get("links", [])
        telegram_file_ids = args.get("telegram_file_ids", [])

        if not isinstance(course_id, str) or not course_id.strip():
            raise ToolArgumentsError("create_assignment", "course_id is required")
        if not isinstance(title, str) or not title.strip():
            raise ToolArgumentsError("create_assignment", "title is required")

        pending_id = classroom.hold_course_work(
            telegram_id=context.user_id,
            course_id=course_id,
            title=title,
            description=description,
            max_points=max_points,
            due_date=due_date,
            due_time=due_time,
            links=links,
            telegram_file_ids=telegram_file_ids
        )

        course = await classroom.get_concrete_course(context.user_id, course_id)

        await telegram.request_course_work(
            chat_id=context.user_id,
            pending_id=pending_id,
            title=title,
            course_name=course.name,
            due_date=due_date
        )

        return ToolResult(
            call_id=context.call_id,
            content='{"status": "paused", "reason": "waiting_for_user_confirmation"}',
            terminal=True
        )

    registry.register(
        "create_assignment",
        create_course_work_tool,
        load_schema("create_assignment")
    )
    registry.register(
        "create_announcement",
        create_course_announcement_tool,
        load_schema("create_announcement")
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
    registry.register(
        "get_assignments",
        get_course_works,
        load_schema("get_assignments")
    )
    registry.register(
        "get_submissions_status",
        get_submissions,
        load_schema("get_submissions_status")
    )
    registry.register(
        "create_course",
        create_course_tool,
        load_schema("create_course")
    )
