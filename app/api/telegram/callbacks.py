from aiogram import Router, F
from aiogram.types import CallbackQuery

from app.agent.models import Message
from app.api.classroom.service import ClassroomService
from app.core.errors import ApplicationError
from app.core.logging import logger
from app.core.types import HistoryStore
from app.api.telegram.service import TelegramService
from app.agent.service import AgentService
import json


def create_callback_router(
    classroom: ClassroomService,
    history_store: HistoryStore,
    telegram: TelegramService,
    agent: AgentService | None = None,
) -> Router:
    router = Router()

    async def notify_agent(call: CallbackQuery, action: str, status: str, success: bool, details: str):
        event = {
            "type": "action_result",
            "action": action,
            "status": status,
            "success": success,
            "details": details,
        }
        if agent is None:
            await history_store.append(
                call.message.chat.id,
                Message("system", json.dumps(event, ensure_ascii=False)),
            )
            return
        response = await agent.resume_after_action(
            chat_id=call.message.chat.id,
            user_id=call.from_user.id,
            event=event,
        )
        if response:
            await telegram.send_message(
                chat_id=call.message.chat.id,
                text=response,
            )

    @router.callback_query(F.data.startswith("agent:choice:"))
    async def handle_agent_choice(call: CallbackQuery):
        _, _, choice_id, option_index_text = call.data.split(":", 3)
        try:
            option_index = int(option_index_text)
        except ValueError:
            await call.answer("Некорректный выбор", show_alert=True)
            return

        choice = telegram.claim_choice(choice_id, option_index, call.from_user.id)
        if not choice or choice["chat_id"] != call.message.chat.id:
            await call.answer("Выбор устарел", show_alert=True)
            return

        selected = choice["selected"]
        await call.answer()
        await call.message.edit_text(
            f"{choice['question']}\n\nВыбрано: {selected['label']}"
        )
        await notify_agent(
            call,
            "ask_choice",
            "selected",
            True,
            json.dumps(
                {
                    "choice_id": choice_id,
                    "label": selected["label"],
                    "value": selected["value"],
                },
                ensure_ascii=False,
            ),
        )

    @router.callback_query(F.data.startswith("course:create:confirm"))
    async def confirm_course_creation(call: CallbackQuery):
        pending_id = call.data.split(":")[-1]
        logger.info("Course creation confirmation callback: pending_id=%s", pending_id)

        data = classroom.get_pending_course(pending_id)

        if not data:
            await call.answer("Данные устарели", show_alert=True)
            return

        await call.message.edit_text(
            f"⏳ Создаю курс «{data['name']}»..."
        )

        try:
            result = await classroom.create_course(
                telegram_id=data["telegram_id"],
                course_name=data["name"],
                course_description=data["description"],
                course_section=data["section"],
            )

            await call.message.edit_text(
                f"✅ Курс «{data['name']}» успешно создан!"
            )

            await history_store.append(
                call.message.chat.id,
                Message("system", f"Пользователь подтвердил создание курса '{data['name']}'. Курс успешно создан."),
            )
            await notify_agent(call, "create_course", "confirmed", True, f"Курс '{data['name']}' успешно создан.")

        except ApplicationError as e:
            await call.message.edit_text("❌ Ошибка при создании курса.")
            await history_store.append(
                call.message.chat.id,
                Message("system", f"Пользователь подтвердил создание, но произошла ошибка: {e}")
            )
            await notify_agent(call, "create_course", "confirmed", False, str(e))
        finally:
            classroom.remove_pending_course(pending_id)
            await call.answer()


    @router.callback_query(F.data.startswith("course:create:cancel:"))
    async def cancel_course_creation(call: CallbackQuery):
        pending_id = call.data.split(":")[-1]
        logger.info("Course creation cancellation callback: pending_id=%s", pending_id)
        data = classroom.get_pending_course(pending_id)

        if data:
            await call.message.edit_text(
                f"❌ Создание курса «{data['name']}» отменено."
            )
            await history_store.append(
                call.message.chat.id,
                Message("system", f"Пользователь ОТМЕНИЛ создание курса '{data['name']}'.")
            )
            await notify_agent(call, "create_course", "cancelled", False, f"Создание курса '{data['name']}' отменено.")
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
            await notify_agent(call, "create_announcement", "confirmed", True, "Анонс успешно создан.")

        except ApplicationError as e:
            await call.message.edit_text("❌ Ошибка при создании анонса.")
            await history_store.append(
                call.message.chat.id,
                Message("system", f"Пользователь подтвердил создание, но произошла ошибка: {e}")
            )
            await notify_agent(call, "create_announcement", "confirmed", False, str(e))

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
            await notify_agent(call, "create_announcement", "cancelled", False, "Создание анонса отменено.")
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
        await notify_agent(call, "create_assignment", "cancelled", False, "Создание задания отменено.")
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
                materials=materials if materials else None,
                topic_id=data.get("topic_id"),
            )
            await call.message.edit_text(
                f"✅ Задание *«{data['title']}»* успешно опубликовано!"
            )

            await history_store.append(
                call.message.chat.id,
                Message("system", f"Задание '{data['title']}' успешно создано в курсе {data['course_id']}.")
            )
            await notify_agent(call, "create_assignment", "confirmed", True, f"Задание '{data['title']}' успешно создано.")
        except Exception as e:
            logger.error(f"Ошибка при создании задания: {e}")
            await call.message.edit_text("❌ Ошибка при создании задания.")
            await notify_agent(call, "create_assignment", "confirmed", False, str(e))

        classroom.remove_pending_assignment(pending_id)
        await call.answer()

    @router.callback_query(F.data.startswith("course:material:create:confirm:"))
    async def confirm_material_creation(call: CallbackQuery):
        pending_id = call.data.split(":")[-1]
        data = classroom.get_pending_material(pending_id)
        if not data or data["telegram_id"] != call.from_user.id:
            await call.answer("Данные устарели", show_alert=True)
            return

        await call.answer()
        await call.message.edit_text("⏳ Загружаю материалы и создаю материал курса...")
        materials = list(data.get("materials", []))
        try:
            course = await classroom.get_concrete_course(data["telegram_id"], data["course_id"])
            folder_id = course.teacher_folder.id if course.teacher_folder else None
            for attachment in data.get("telegram_attachments", []):
                file_name, file_bytes = await telegram.get_file_content(attachment.file_id)
                drive_file = await classroom.upload_to_drive(
                    telegram_id=data["telegram_id"],
                    file_name=attachment.file_name or file_name,
                    content=file_bytes,
                    mime_type=attachment.mime_type or "application/octet-stream",
                    parent_folder_id=folder_id,
                )
                materials.append({
                    "driveFile": {
                        "driveFile": {"id": drive_file["id"]},
                        "shareMode": "VIEW",
                    }
                })

            await classroom.create_course_material(
                telegram_id=data["telegram_id"],
                course_id=data["course_id"],
                title=data["title"],
                description=data["description"],
                materials=materials,
                topic_id=data.get("topic_id"),
            )
            await call.message.edit_text("✅ Материал курса успешно создан.")
            await history_store.append(
                call.message.chat.id,
                Message("system", f"Материал '{data['title']}' успешно создан."),
            )
            await notify_agent(call, "create_material", "confirmed", True, f"Материал '{data['title']}' успешно создан.")
        except ApplicationError as error:
            logger.error("Material creation failed: %s", error)
            await call.message.edit_text("❌ Не удалось создать материал курса.")
            await notify_agent(call, "create_material", "confirmed", False, str(error))
        finally:
            classroom.remove_pending_material(pending_id)

    @router.callback_query(F.data.startswith("course:material:create:cancel:"))
    async def cancel_material_creation(call: CallbackQuery):
        pending_id = call.data.split(":")[-1]
        data = classroom.get_pending_material(pending_id)
        if not data or data["telegram_id"] != call.from_user.id:
            await call.answer("Данные устарели", show_alert=True)
            return
        await call.answer()
        await call.message.edit_text("❌ Создание материала отменено.")
        await notify_agent(call, "create_material", "cancelled", False, "Создание материала отменено.")
        classroom.remove_pending_material(pending_id)

    @router.callback_query(F.data.startswith("course:topic:creat:confirm:"))
    async def confirm_topic_creation(call: CallbackQuery):
        pending_id = call.data.split(":")[-1]
        data = classroom.get_pending_topic(pending_id)
        if not data or data["telegram_id"] != call.from_user.id:
            await call.answer("Данные устарели", show_alert=True)
            return

        await call.answer()
        try:
            await classroom.create_topic(
                telegram_id=data["telegram_id"],
                course_id=data["course_id"],
                topic_name=data["topic_name"],
            )
            await call.message.edit_text(
                f"✅ Раздел «{data['topic_name']}» успешно создан."
            )
            await history_store.append(
                call.message.chat.id,
                Message("system", f"Раздел '{data['topic_name']}' успешно создан."),
            )
            await notify_agent(call, "create_topic", "confirmed", True, f"Раздел '{data['topic_name']}' успешно создан.")
        except ApplicationError as error:
            logger.error("Topic creation failed: %s", error)
            await call.message.edit_text("❌ Не удалось создать раздел.")
            await history_store.append(
                call.message.chat.id,
                Message("system", f"Создание раздела не выполнено: {error}"),
            )
            await notify_agent(call, "create_topic", "confirmed", False, str(error))
        finally:
            classroom.remove_pending_topic(pending_id)

    @router.callback_query(F.data.startswith("course:topic:creat:cancel:"))
    async def cancel_topic_creation(call: CallbackQuery):
        pending_id = call.data.split(":")[-1]
        data = classroom.get_pending_topic(pending_id)
        if not data or data["telegram_id"] != call.from_user.id:
            await call.answer("Данные устарели", show_alert=True)
            return
        await call.answer()
        await call.message.edit_text("❌ Создание раздела отменено.")
        await notify_agent(call, "create_topic", "cancelled", False, "Создание раздела отменено.")
        classroom.remove_pending_topic(pending_id)

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
            elif resource == "topic":
                await classroom.update_topic(
                    telegram_id=data["telegram_id"],
                    course_id=data["course_id"],
                    topic_id=data["topic_id"],
                    topic_name=data["topic_name"],
                )
                message = "✅ Раздел успешно изменён."
            elif resource == "material":
                await classroom.update_course_material(
                    telegram_id=data["telegram_id"],
                    course_id=data["course_id"],
                    material_id=data["material_id"],
                    title=data["title"],
                    description=data["description"],
                    materials=data.get("materials"),
                    topic_id=data.get("topic_id"),
                )
                message = "✅ Материал успешно изменён."
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
            await notify_agent(call, f"update_{resource}", "confirmed", True, message)
        except ApplicationError as error:
            await call.message.edit_text("❌ Не удалось изменить объект.")
            await history_store.append(
                call.message.chat.id,
                Message("system", f"Изменение не выполнено: {error}"),
            )
            await notify_agent(call, f"update_{resource}", "confirmed", False, str(error))
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
        await notify_agent(call, f"update_{resource}", "cancelled", False, "Изменение отменено.")
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

    @router.callback_query(F.data.startswith("course:topic:update:confirm:"))
    async def confirm_topic_update(call: CallbackQuery):
        await apply_update(call, call.data.split(":")[-1], "topic")

    @router.callback_query(F.data.startswith("course:topic:update:cancel:"))
    async def cancel_topic_update(call: CallbackQuery):
        await cancel_update(call, call.data.split(":")[-1], "topic")

    @router.callback_query(F.data.startswith("course:material:update:confirm:"))
    async def confirm_material_update(call: CallbackQuery):
        await apply_update(call, call.data.split(":")[-1], "material")

    @router.callback_query(F.data.startswith("course:material:update:cancel:"))
    async def cancel_material_update(call: CallbackQuery):
        await cancel_update(call, call.data.split(":")[-1], "material")

    return router
