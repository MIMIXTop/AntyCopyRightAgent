from aiogram import Router, F
from aiogram.dispatcher import router
from aiogram.types import CallbackQuery

from app.agent.models import Message
from app.classroom.service import ClassroomService
from app.core.errors import ApplicationError
from app.core.logging import logger
from app.core.types import HistoryStore
from app.telegram.service import TelegramService


def create_callback_router(classroom: ClassroomService, history_store: HistoryStore, telegram: TelegramService) -> Router:
    router = Router()

    @router.callback_query(F.data.startswith("course:create:confirm"))
    async def confirm_course_creation(call: CallbackQuery):
        pending_id = call.data.split(":")[-1]
        logger.info("Course creation confirmation callback: pending_id=%s", pending_id)

        data = classroom.get_pending_course(pending_id)

        if not data:
            await call.answer("Данные устарели", show_alert=True)
            return

        await call.message.edit_text(f"⏳ Создаю курс «{data['name']}»...")

        try:
            result = await classroom.create_course(
                telegram_id=data["telegram_id"],
                course_name=data["name"],
                course_description=data["description"],
                course_section=data["section"],
            )

            await call.message.edit_text(f"✅ Курс «{data['name']}» успешно создан!")

            await history_store.append(
                call.message.chat.id,
                Message("system", f"Пользователь подтвердил создание курса '{data['name']}'. Курс успешно создан."),
            )

        except ApplicationError as e:
            await call.message.edit_text("❌ Ошибка при создании курса.")
            await history_store.append(
                call.message.chat.id,
                Message("system", f"Пользователь подтвердил создание, но произошла ошибка: {e}")
            )

        classroom.remove_pending_course(pending_id)


    @router.callback_query(F.data.startswith("course:create:cancel:"))
    async def cancel_course_creation(call: CallbackQuery):
        pending_id = call.data.split(":")[-1]
        logger.info("Course creation cancellation callback: pending_id=%s", pending_id)
        data = classroom.get_pending_course(pending_id)

        if data:
            await call.message.edit_text(f"❌ Создание курса «{data['name']}» отменено.")
            await history_store.append(
                call.message.chat.id,
                Message("system", f"Пользователь ОТМЕНИЛ создание курса '{data['name']}'.")
            )
            classroom.remove_pending_course(pending_id)

    @router.callback_query(F.data.startswith("course:announcement:create:confirm:"))
    async def confirm_course_announcement_creation(call: CallbackQuery):
        pending_id = call.data.split(":")[-1]
        logger.info("Course creation confirm callback: pending_id=%s", pending_id)
        data = classroom.claim_pending_announcement(pending_id, call.from_user.id)

        if not data:
            await call.answer("Данные устарели", show_alert=True)
            return

        await call.answer()
        await call.message.edit_text(f"⏳ Создаю анонса...")

        materials = []
        telegram_attachments = data.get("telegram_attachments", [])

        try:
            if telegram_attachments:
                course = await classroom.get_concrete_course(data["telegram_id"], data["course_id"])
                folder_id = course.teacher_folder.id if course.teacher_folder else None

                for attachment in telegram_attachments:
                    file_name, file_bytes = await telegram.get_file_content(attachment.file_id)

                    drive_file = await classroom.upload_to_drive(
                        telegram_id=data["telegram_id"],
                        file_name=attachment.file_name or file_name,
                        content=file_bytes,
                        mime_type=attachment.mime_type or "application/octet-stream",
                        parent_folder_id=folder_id
                    )

                    materials.append({
                        "driveFile": {
                            "driveFile": {"id": drive_file["id"]},
                            "shareMode": "VIEW"
                        }
                    })

            result = await classroom.create_announcement(
                telegram_id=data["telegram_id"],
                course_id=data["course_id"],
                text=data["text"],
                state=data["state"],
                materials=data.get("materials", []) + materials,
            )

            await call.message.edit_text("✅ Анонс успешно создан")
            await history_store.append(
                call.message.chat.id,
                Message("system", f"Пользователь подтвердил создание анонса курса '{data['course_id']}'. Анонс успешно создан.")
            )

        except ApplicationError as e:
            await call.message.edit_text("❌ Ошибка при создании анонса.")
            await history_store.append(
                call.message.chat.id,
                Message("system", f"Пользователь подтвердил создание, но произошла ошибка: {e}")
            )

        classroom.remove_pending_announcement(pending_id)

    @router.callback_query(F.data.startswith("course:announcement:create:cancel:"))
    async def cancel_announcement_creation(call: CallbackQuery):
        pending_id = call.data.split(":")[-1]
        logger.info("Course creation cancellation callback: pending_id=%s", pending_id)
        data = classroom.get_pending_announcement(pending_id)

        if data:
            await call.answer()
            await call.message.edit_text(f"❌ Создание анонса отменено.")
            await history_store.append(
                call.message.chat.id,
                Message(
                    "system", f"Пользователь ОТМЕНИЛ создание анонса для курса '{data['course_id']}'." )
            )
            classroom.remove_pending_announcement(pending_id)

    @router.callback_query(F.data.startswith("course:work:create:cancel:"))
    async def cancel_work_creation(call: CallbackQuery):
        pending_id = call.data.split(":")[-1]
        data = classroom.get_pending_assignment(pending_id)
        await history_store.append(
            call.message.chat.id,
            Message(
                "system", f"Пользователь ОТМЕНИЛ создание работы для курса '{data['course_id']}'.")
        )
        await call.message.edit_text("❌ Создание задания отменено.")
        await call.answer()
        classroom.remove_pending_assignment(pending_id)

    @router.callback_query(F.data.startswith("course:work:create:confirm:"))
    async def confirm_work_creation(call: CallbackQuery):
        pending_id = call.data.split(":")[-1]
        data = classroom.get_pending_assignment(pending_id)
        if not data:
            await call.answer("Ошибка: действие устарело.", show_alert=True)
            return

        await call.message.edit_text("⏳ Загружаю материалы и публикую задание...")
        materials = []

        for link_url in data.get("links", []):
            if link_url.startswith("http"):
                materials.append({"link": {"url": link_url}})

        tg_file_ids = data.get("telegram_file_ids", [])
        if tg_file_ids:
            course = await classroom.get_concrete_course(data["telegram_id"], data["course_id"])
            folder_id = course.teacher_folder.id if course.teacher_folder else None

            for fid in tg_file_ids:
                fname, fbytes = await telegram.get_file_content(fid)
                drive_file = await classroom.upload_to_drive(
                    telegram_id=data["telegram_id"],
                    file_name=fname,
                    content=fbytes,
                    mime_type="application/octet-stream",
                    parent_folder_id=folder_id
                )
                materials.append({
                    "driveFile": {
                        "driveFile": {"id": drive_file["id"]},
                        "shareMode": "VIEW"
                    }
                })

        try:
            res = await classroom.create_assignment(
                telegram_id=data["telegram_id"],
                course_id=data["course_id"],
                title=data["title"],
                description=data["description"],
                max_points=data["max_points"],
                due_date=data["due_date"],
                due_time=data["due_time"],
                materials=materials if materials else None
            )
            await call.message.edit_text(f"✅ Задание <b>«{data['title']}»</b> успешно опубликовано!", parse_mode="HTML")

            await history_store.append(
                call.message.chat.id,
                Message("system", f"Задание '{data['title']}' успешно создано в курсе {data['course_id']}.")
            )
        except Exception as e:
            logger.error(f"Ошибка при создании задания: {e}")
            await call.message.edit_text("❌ Ошибка при создании задания.")

        classroom.remove_pending_assignment(pending_id)
        await call.answer()

    async def apply_update(call: CallbackQuery, pending_id: str, resource: str):
        data = classroom.get_pending_update(pending_id)
        if not data or data["resource"] != resource or data["telegram_id"] != call.from_user.id:
            await call.answer("Данные устарели", show_alert=True)
            return

        await call.answer()
        try:
            if resource == "course":
                await classroom.update_course(
                    telegram_id=data["telegram_id"],
                    course_id=data["course_id"],
                    name=data["name"],
                    description=data["description"],
                    section=data["section"],
                    course_state=data["course_state"],
                )
                message = "✅ Курс успешно изменён."
            elif resource == "announcement":
                await classroom.update_announcement(
                    telegram_id=data["telegram_id"],
                    course_id=data["course_id"],
                    announcement_id=data["announcement_id"],
                    text=data["text"],
                    state=data["state"],
                )
                message = "✅ Анонс успешно изменён."
            else:
                await classroom.update_assignment(
                    telegram_id=data["telegram_id"],
                    course_id=data["course_id"],
                    assignment_id=data["assignment_id"],
                    title=data["title"],
                    description=data["description"],
                    max_points=data["max_points"],
                    due_date=data["due_date"],
                    due_time=data["due_time"],
                    state=data["state"],
                )
                message = "✅ Задание успешно изменено."

            await call.message.edit_text(message)
            await history_store.append(
                call.message.chat.id,
                Message("system", message),
            )
        except ApplicationError as error:
            await call.message.edit_text("❌ Не удалось изменить объект.")
            await history_store.append(
                call.message.chat.id,
                Message("system", f"Изменение не выполнено: {error}"),
            )
        finally:
            classroom.remove_pending_update(pending_id)

    async def cancel_update(call: CallbackQuery, pending_id: str, resource: str):
        data = classroom.get_pending_update(pending_id)
        if not data or data["resource"] != resource or data["telegram_id"] != call.from_user.id:
            await call.answer("Данные устарели", show_alert=True)
            return
        await call.answer()
        await call.message.edit_text("❌ Изменение отменено.")
        await history_store.append(
            call.message.chat.id,
            Message("system", "Пользователь отменил изменение."),
        )
        classroom.remove_pending_update(pending_id)

    @router.callback_query(F.data.startswith("course:update:confirm:"))
    async def confirm_course_update(call: CallbackQuery):
        await apply_update(call, call.data.split(":")[-1], "course")

    @router.callback_query(F.data.startswith("course:update:cancel:"))
    async def cancel_course_update(call: CallbackQuery):
        await cancel_update(call, call.data.split(":")[-1], "course")

    @router.callback_query(F.data.startswith("announcement:update:confirm:"))
    async def confirm_announcement_update(call: CallbackQuery):
        await apply_update(call, call.data.split(":")[-1], "announcement")

    @router.callback_query(F.data.startswith("announcement:update:cancel:"))
    async def cancel_announcement_update(call: CallbackQuery):
        await cancel_update(call, call.data.split(":")[-1], "announcement")

    @router.callback_query(F.data.startswith("course:work:update:confirm:"))
    async def confirm_assignment_update(call: CallbackQuery):
        await apply_update(call, call.data.split(":")[-1], "assignment")

    @router.callback_query(F.data.startswith("course:work:update:cancel:"))
    async def cancel_assignment_update(call: CallbackQuery):
        await cancel_update(call, call.data.split(":")[-1], "assignment")

    return router
