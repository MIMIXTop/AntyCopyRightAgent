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


    return router
