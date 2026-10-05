import json
from urllib.parse import urlparse

from app.core.errors import ToolArgumentsError
from app.agent.models import ToolContext, ToolResult
from app.classroom.service import ClassroomService
from app.telegram.service import TelegramService
from app.tools.loader import load_schema
from app.core.logging import logger


def _json_model(model) -> dict:
    return model.model_dump(mode="json")


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
                {"students": [_json_model(item) for item in students]},
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
                {"courses": [_json_model(item) for item in courses]},
            )
        )

    async def get_course_works(context: ToolContext, args: dict):
        telegram_id = context.user_id
        course_id = args.get("course_id")

        course_works = await classroom.get_assignments(telegram_id, course_id)
        return ToolResult(
            call_id=context.call_id,
            content=json.dumps(
                {"course_works": [_json_model(item) for item in course_works]},
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
                {"student_submissions": [_json_model(item) for item in student_submissions]},
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

    async def attach_web_image_tool(context: ToolContext, args: dict):
        course_id = args.get("course_id")
        image_url = args.get("image_url")
        file_name = args.get("file_name", "illustration.jpg")

        if not isinstance(course_id, str) or not course_id.strip():
            raise ToolArgumentsError("attach_web_image_to_course", "course_id is required")
        if not isinstance(image_url, str) or not image_url.strip():
            raise ToolArgumentsError("attach_web_image_to_course", "image_url is required")

        material_payload = await classroom.attach_web_image_as_drive_file(
            telegram_id=context.user_id,
            course_id=course_id,
            image_url=image_url,
            image_name=file_name
        )

        drive_file_id = material_payload["driveFile"]["driveFile"]["id"]

        return ToolResult(
            call_id=context.call_id,
            content=json.dumps(
                {
                    "status": "success",
                    "drive_file_id": drive_file_id,
                    "material": material_payload,
                    "message": "Image uploaded to course Drive folder as display image.",
                },
                ensure_ascii=False,
            ),
            terminal=False
        )

    async def get_announcements_tool(context: ToolContext, args: dict):
        telegram_id = context.user_id
        course_id = args.get("course_id")

        if not isinstance(course_id, str) or not course_id.strip():
            raise ToolArgumentsError("get_announcements", "course_id is required")

        announcements = await classroom.get_announcements(telegram_id, course_id)

        return ToolResult(
            call_id=context.call_id,
            content=json.dumps(
                {"announcements": [_json_model(item) for item in announcements]},
                ensure_ascii=False,
                default=str,
            ),
        )

    async def update_course_tool(context: ToolContext, args: dict) -> ToolResult:
        telegram_id = context.user_id
        course_id = args.get("course_id")
        name = args.get("name")
        description = args.get("description")
        section = args.get("section")
        course_state = args.get("course_state")

        if not isinstance(course_id, str) or not course_id.strip():
            raise ToolArgumentsError("update_course", "course_id is required and must be a non-empty string")

        if all(v is None for v in (name, description, section, course_state)):
            raise ToolArgumentsError("update_course", "At least one field to update must be provided")

        pending_id = classroom.hold_update(
            "course",
            telegram_id,
            course_id=course_id,
            name=name,
            description=description,
            section=section,
            course_state=course_state,
        )

        course = await classroom.get_concrete_course(telegram_id, course_id)
        await telegram.request_course_update(
            chat_id=context.chat_id,
            pending_id=pending_id,
            course_name=course.name,
            changes={
                "name": name,
                "description": description,
                "section": section,
                "course_state": course_state,
            },
        )
        return ToolResult(
            call_id=context.call_id,
            content=json.dumps({"status": "paused", "reason": "waiting_for_user_confirmation", "pending_id": pending_id}),
            terminal=True,
        )

    async def update_announcement_tool(context: ToolContext, args: dict) -> ToolResult:
        telegram_id = context.user_id
        course_id = args.get("course_id")
        announcement_id = args.get("announcement_id")
        text = args.get("text")
        state = args.get("state")

        if not isinstance(course_id, str) or not course_id.strip():
            raise ToolArgumentsError("update_announcement", "course_id is required and must be a non-empty string")
        if not isinstance(announcement_id, str) or not announcement_id.strip():
            raise ToolArgumentsError("update_announcement",
                                     "announcement_id is required and must be a non-empty string")

        if text is None and state is None:
            raise ToolArgumentsError("update_announcement", "Either 'text' or 'state' must be provided for update")

        pending_id = classroom.hold_update(
            "announcement",
            telegram_id,
            course_id=course_id,
            announcement_id=announcement_id,
            text=text,
            state=state,
        )

        await telegram.request_announcement_update(
            chat_id=context.chat_id,
            pending_id=pending_id,
            changes={"text": text, "state": state},
        )
        return ToolResult(
            call_id=context.call_id,
            content=json.dumps({"status": "paused", "reason": "waiting_for_user_confirmation", "pending_id": pending_id}),
            terminal=True,
        )

    async def update_assignment_tool(context: ToolContext, args: dict) -> ToolResult:
        telegram_id = context.user_id
        course_id = args.get("course_id")
        assignment_id = args.get("assignment_id")
        title = args.get("title")
        description = args.get("description")
        max_points = args.get("max_points")
        due_date = args.get("due_date")
        due_time = args.get("due_time")
        state = args.get("state")

        if not isinstance(course_id, str) or not course_id.strip():
            raise ToolArgumentsError("update_assignment", "course_id is required and must be a non-empty string")
        if not isinstance(assignment_id, str) or not assignment_id.strip():
            raise ToolArgumentsError("update_assignment", "assignment_id is required and must be a non-empty string")

        if all(v is None for v in (title, description, max_points, due_date, due_time, state)):
            raise ToolArgumentsError("update_assignment", "At least one field to update must be provided")

        pending_id = classroom.hold_update(
            "assignment",
            telegram_id,
            course_id=course_id,
            assignment_id=assignment_id,
            title=title,
            description=description,
            max_points=max_points,
            due_date=due_date,
            due_time=due_time,
            state=state,
        )

        await telegram.request_assignment_update(
            chat_id=context.chat_id,
            pending_id=pending_id,
            changes={
                "title": title, "description": description, "max_points": max_points,
                "due_date": due_date, "due_time": due_time, "state": state,
            },
        )
        return ToolResult(
            call_id=context.call_id,
            content=json.dumps({"status": "paused", "reason": "waiting_for_user_confirmation", "pending_id": pending_id}),
            terminal=True,
        )

    async def invite_link_tool(context: ToolContext, args: dict) -> ToolResult:
        url = args.get("url")
        text = args.get("text")

        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise ToolArgumentsError("invite_link", "url must be a valid HTTP(S) URL")

        if not isinstance(text, str) or not text.strip():
            raise ToolArgumentsError("invite_link", "text must be a non-empty string")

        await telegram.request_invite_link(
            chat_id=context.chat_id,
            url=url,
            text=text,
        )

        return ToolResult(
            call_id=context.call_id,
            content=json.dumps({"status": "delivered", "reason": "invite_link_sent"}),
            terminal=False,
        )

    registry.register(
        "invite_link",
        invite_link_tool,
        load_schema("invite_link")
    )
    registry.register(
        "update_course",
        update_course_tool,
        load_schema("update_course")
    )
    registry.register(
        "update_announcement",
        update_announcement_tool,
        load_schema("update_announcement")
    )
    registry.register(
        "update_assignment",
        update_assignment_tool,
        load_schema("update_assignment")
    )
    registry.register(
        "get_announcements",
        get_announcements_tool,
        load_schema("get_announcements")
    )
    registry.register(
        "attach_web_image_to_course",
        attach_web_image_tool,
        load_schema("attach_web_image_to_course")
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
