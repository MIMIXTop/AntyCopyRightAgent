from aiogram import Router, F
from aiogram.types import CallbackQuery

from app.agent.conversation import conversation_key
from app.agent.models import DeliveryContext, GROUP_CHAT_TYPES, Message
from app.api.classroom.service import ClassroomService
from app.api.forms.service import FormsService
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
    forms: FormsService | None = None,
    group_safe_mode: bool = True,
) -> Router:
    router = Router()

    def _chat_id(call: CallbackQuery, data: dict | None = None) -> int:
        if data and data.get("chat_id"):
            return data["chat_id"]
        if call.message is not None:
            return call.message.chat.id
        return call.from_user.id

    def _chat_type(call: CallbackQuery, data: dict | None = None) -> str:
        if data and data.get("chat_type"):
            return data["chat_type"]
        if call.message is not None:
            return call.message.chat.type
        return "private" if _chat_id(call, data) == call.from_user.id else "group"

    def _delivery(
        call: CallbackQuery,
        data: dict | None = None,
        *,
        ephemeral: bool = True,
    ) -> DeliveryContext:
        return DeliveryContext(
            chat_id=_chat_id(call, data),
            user_id=call.from_user.id,
            chat_type=_chat_type(call, data),
            ephemeral=ephemeral,
            callback_query_id=call.id,
        )

    def _conversation_key(call: CallbackQuery, data: dict | None = None):
        return conversation_key(
            _chat_type(call, data),
            _chat_id(call, data),
            call.from_user.id,
        )

    async def _reject_foreign_button(call: CallbackQuery) -> None:
        await call.answer("Эта кнопка не для вас", show_alert=True)

    def _group_action_blocked(data: dict | None) -> bool:
        """Group confirmations are disabled while the safe group mode is on."""
        return bool(
            group_safe_mode
            and data
            and data.get("chat_type") in GROUP_CHAT_TYPES
        )

    async def _reject_group_action(call: CallbackQuery) -> None:
        await call.answer(
            "Действия с курсами и Google-сервисами в группе отключены. "
            "Напишите боту в личные сообщения.",
            show_alert=True,
        )

    async def notify_agent(
        call: CallbackQuery,
        action: str,
        status: str,
        success: bool,
        details: str,
        data: dict | None = None,
    ):
        event = {
            "type": "action_result",
            "action": action,
            "status": status,
            "success": success,
            "details": details,
        }
        if agent is None:
            await history_store.append(
                _conversation_key(call, data),
                Message("system", json.dumps(event, ensure_ascii=False)),
            )
            return
        response = await agent.resume_after_action(
            chat_id=_chat_id(call, data),
            user_id=call.from_user.id,
            event=event,
            delivery=_delivery(call, data),
        )
        if response:
            await telegram.send_message(
                chat_id=_chat_id(call, data),
                text=response,
                delivery=_delivery(call, data),
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
        if not choice or choice["chat_id"] != _chat_id(call, choice):
            await call.answer("Выбор устарел", show_alert=True)
            return

        selected = choice["selected"]
        await call.answer()
        await telegram.edit_status(call,
            f"{choice['question']}\n\nВыбрано: {selected['label']}",
            chat_id=_chat_id(call, choice),
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
            data=choice,
        )

    @router.callback_query(F.data.startswith("course:create:confirm"))
    async def confirm_course_creation(call: CallbackQuery):
        pending_id = call.data.split(":")[-1]
        logger.info("Course creation confirmation callback: pending_id=%s", pending_id)

        data = classroom.get_pending_course(pending_id)

        if not data:
            await call.answer("Данные устарели", show_alert=True)
            return
        if _group_action_blocked(data):
            await _reject_group_action(call)
            return
        if data["telegram_id"] != call.from_user.id:
            await _reject_foreign_button(call)
            return

        await call.answer()
        await telegram.edit_status(call,
            f"⏳ Создаю курс «{data['name']}»...",
            chat_id=_chat_id(call, data),
        )

        try:
            result = await classroom.create_course(
                telegram_id=data["telegram_id"],
                course_name=data["name"],
                course_description=data["description"],
                course_section=data["section"],
            )

            await telegram.edit_status(call,
                f"✅ Курс «{data['name']}» успешно создан!",
                chat_id=_chat_id(call, data),
            )

            await history_store.append(
                _conversation_key(call, data),
                Message("system", f"Пользователь подтвердил создание курса '{data['name']}'. Курс успешно создан."),
            )
            await notify_agent(call, "create_course", "confirmed", True, f"Курс '{data['name']}' успешно создан.", data=data)

        except ApplicationError as e:
            await telegram.edit_status(call, "❌ Ошибка при создании курса.", chat_id=_chat_id(call, data))
            await history_store.append(
                _conversation_key(call, data),
                Message("system", f"Пользователь подтвердил создание, но произошла ошибка: {e}")
            )
            await notify_agent(call, "create_course", "confirmed", False, str(e), data=data)
        finally:
            classroom.remove_pending_course(pending_id)


    @router.callback_query(F.data.startswith("course:create:cancel:"))
    async def cancel_course_creation(call: CallbackQuery):
        pending_id = call.data.split(":")[-1]
        logger.info("Course creation cancellation callback: pending_id=%s", pending_id)
        data = classroom.get_pending_course(pending_id)

        if not data:
            await call.answer("Данные устарели", show_alert=True)
            return
        if data["telegram_id"] != call.from_user.id:
            await _reject_foreign_button(call)
            return

        await call.answer()
        await telegram.edit_status(call,
            f"❌ Создание курса «{data['name']}» отменено.",
            chat_id=_chat_id(call, data),
        )
        await history_store.append(
            _conversation_key(call, data),
            Message("system", f"Пользователь ОТМЕНИЛ создание курса '{data['name']}'.")
        )
        await notify_agent(call, "create_course", "cancelled", False, f"Создание курса '{data['name']}' отменено.", data=data)
        classroom.remove_pending_course(pending_id)

    @router.callback_query(F.data.startswith("course:announcement:create:confirm:"))
    async def confirm_course_announcement_creation(call: CallbackQuery):
        pending_id = call.data.split(":")[-1]
        logger.info("Course creation confirm callback: pending_id=%s", pending_id)
        pending = classroom.get_pending_announcement(pending_id)
        if pending and _group_action_blocked(pending):
            await _reject_group_action(call)
            return
        data = classroom.claim_pending_announcement(pending_id, call.from_user.id)

        if not data:
            await call.answer("Данные устарели", show_alert=True)
            return

        await call.answer()
        await telegram.edit_status(call, f"⏳ Создаю анонса...", chat_id=_chat_id(call, data))

        materials = []
        telegram_attachments = data.get("telegram_attachments", [])
        logger.info(
            "Announcement confirmation attachments: pending_id=%s count=%s",
            pending_id,
            len(telegram_attachments),
        )

        try:
            if telegram_attachments:
                course = await classroom.get_concrete_course(data["telegram_id"], data["course_id"])
                folder_id = course.teacher_folder.id if course.teacher_folder else None

                for attachment in telegram_attachments:
                    logger.info(
                        "Uploading announcement attachment: pending_id=%s file_id=%s file_name=%s kind=%s",
                        pending_id,
                        attachment.file_id,
                        attachment.file_name,
                        attachment.kind,
                    )
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
                logger.info(
                    "Announcement attachments uploaded: pending_id=%s count=%s",
                    pending_id,
                    len(materials),
                )

            result = await classroom.create_announcement(
                telegram_id=data["telegram_id"],
                course_id=data["course_id"],
                text=data["text"],
                state=data["state"],
                materials=data.get("materials", []) + materials,
            )

            await telegram.edit_status(call, "✅ Анонс успешно создан", chat_id=_chat_id(call, data))
            await history_store.append(
                _conversation_key(call, data),
                Message("system", f"Пользователь подтвердил создание анонса курса '{data['course_id']}'. Анонс успешно создан.")
            )
            await notify_agent(call, "create_announcement", "confirmed", True, "Анонс успешно создан.", data=data)

        except ApplicationError as e:
            await telegram.edit_status(call, "❌ Ошибка при создании анонса.", chat_id=_chat_id(call, data))
            await history_store.append(
                _conversation_key(call, data),
                Message("system", f"Пользователь подтвердил создание, но произошла ошибка: {e}")
            )
            await notify_agent(call, "create_announcement", "confirmed", False, str(e), data=data)

        classroom.remove_pending_announcement(pending_id)

    @router.callback_query(F.data.startswith("course:announcement:create:cancel:"))
    async def cancel_announcement_creation(call: CallbackQuery):
        pending_id = call.data.split(":")[-1]
        logger.info("Course creation cancellation callback: pending_id=%s", pending_id)
        data = classroom.get_pending_announcement(pending_id)

        if not data:
            await call.answer("Данные устарели", show_alert=True)
            return
        if data["telegram_id"] != call.from_user.id:
            await _reject_foreign_button(call)
            return

        await call.answer()
        await telegram.edit_status(call, f"❌ Создание анонса отменено.", chat_id=_chat_id(call, data))
        await history_store.append(
            _conversation_key(call, data),
            Message(
                "system", f"Пользователь ОТМЕНИЛ создание анонса для курса '{data['course_id']}'." )
        )
        await notify_agent(call, "create_announcement", "cancelled", False, "Создание анонса отменено.", data=data)
        classroom.remove_pending_announcement(pending_id)

    @router.callback_query(F.data.startswith("course:work:create:cancel:"))
    async def cancel_work_creation(call: CallbackQuery):
        pending_id = call.data.split(":")[-1]
        data = classroom.get_pending_assignment(pending_id)
        if not data:
            await call.answer("Данные устарели", show_alert=True)
            return
        if data["telegram_id"] != call.from_user.id:
            await _reject_foreign_button(call)
            return
        await history_store.append(
            _conversation_key(call, data),
            Message(
                "system", f"Пользователь ОТМЕНИЛ создание работы для курса '{data['course_id']}'.")
        )
        await notify_agent(call, "create_assignment", "cancelled", False, "Создание задания отменено.", data=data)
        await telegram.edit_status(call, "❌ Создание задания отменено.", chat_id=_chat_id(call, data))
        await call.answer()
        classroom.remove_pending_assignment(pending_id)

    @router.callback_query(F.data.startswith("course:work:create:confirm:"))
    async def confirm_work_creation(call: CallbackQuery):
        pending_id = call.data.split(":")[-1]
        data = classroom.get_pending_assignment(pending_id)
        if not data:
            await call.answer("Ошибка: действие устарело.", show_alert=True)
            return
        if _group_action_blocked(data):
            await _reject_group_action(call)
            return
        if data["telegram_id"] != call.from_user.id:
            await _reject_foreign_button(call)
            return

        await call.answer()
        await telegram.edit_status(call, "⏳ Загружаю материалы и публикую задание...", chat_id=_chat_id(call, data))
        materials = []

        try:
            for link_url in data.get("links", []):
                if link_url.startswith("http"):
                    materials.append({"link": {"url": link_url}})

            tg_file_ids = data.get("telegram_file_ids", [])
            if tg_file_ids:
                course = await classroom.get_concrete_course(data["telegram_id"], data["course_id"])
                folder_id = course.teacher_folder.id if course.teacher_folder else None

                for fid in tg_file_ids:
                    logger.info(
                        "Uploading assignment attachment: pending_id=%s file_id=%s",
                        pending_id,
                        fid,
                    )
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
            await telegram.edit_status(call,
                f"✅ Задание *«{data['title']}»* успешно опубликовано!",
                chat_id=_chat_id(call, data),
            )

            await history_store.append(
                _conversation_key(call, data),
                Message("system", f"Задание '{data['title']}' успешно создано в курсе {data['course_id']}.")
            )
            await notify_agent(call, "create_assignment", "confirmed", True, f"Задание '{data['title']}' успешно создано.", data=data)
        except Exception as e:
            logger.error(
                "Assignment creation failed: pending_id=%s error=%s",
                pending_id,
                e,
            )
            await telegram.edit_status(call, "❌ Ошибка при создании задания.", chat_id=_chat_id(call, data))
            await notify_agent(call, "create_assignment", "confirmed", False, str(e), data=data)
        finally:
            classroom.remove_pending_assignment(pending_id)

    @router.callback_query(F.data.startswith("course:material:create:confirm:"))
    async def confirm_material_creation(call: CallbackQuery):
        pending_id = call.data.split(":")[-1]
        data = classroom.get_pending_material(pending_id)
        if not data or data["telegram_id"] != call.from_user.id:
            await call.answer("Данные устарели", show_alert=True)
            return
        if _group_action_blocked(data):
            await _reject_group_action(call)
            return

        await call.answer()
        await telegram.edit_status(call, "⏳ Загружаю материалы и создаю материал курса...", chat_id=_chat_id(call, data))
        materials = list(data.get("materials", []))
        try:
            attachments = data.get("telegram_attachments", [])
            if attachments:
                course = await classroom.get_concrete_course(data["telegram_id"], data["course_id"])
                folder_id = course.teacher_folder.id if course.teacher_folder else None
                for attachment in attachments:
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
            await telegram.edit_status(call, "✅ Материал курса успешно создан.", chat_id=_chat_id(call, data))
            await history_store.append(
                _conversation_key(call, data),
                Message("system", f"Материал '{data['title']}' успешно создан."),
            )
            await notify_agent(call, "create_material", "confirmed", True, f"Материал '{data['title']}' успешно создан.", data=data)
        except ApplicationError as error:
            logger.error("Material creation failed: %s", error)
            await telegram.edit_status(call, "❌ Не удалось создать материал курса.", chat_id=_chat_id(call, data))
            await notify_agent(call, "create_material", "confirmed", False, str(error), data=data)
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
        await telegram.edit_status(call, "❌ Создание материала отменено.", chat_id=_chat_id(call, data))
        await notify_agent(call, "create_material", "cancelled", False, "Создание материала отменено.", data=data)
        classroom.remove_pending_material(pending_id)

    @router.callback_query(F.data.startswith("course:topic:creat:confirm:"))
    async def confirm_topic_creation(call: CallbackQuery):
        pending_id = call.data.split(":")[-1]
        data = classroom.get_pending_topic(pending_id)
        if not data or data["telegram_id"] != call.from_user.id:
            await call.answer("Данные устарели", show_alert=True)
            return
        if _group_action_blocked(data):
            await _reject_group_action(call)
            return

        await call.answer()
        try:
            await classroom.create_topic(
                telegram_id=data["telegram_id"],
                course_id=data["course_id"],
                topic_name=data["topic_name"],
            )
            await telegram.edit_status(call,
                f"✅ Раздел «{data['topic_name']}» успешно создан.",
                chat_id=_chat_id(call, data),
            )
            await history_store.append(
                _conversation_key(call, data),
                Message("system", f"Раздел '{data['topic_name']}' успешно создан."),
            )
            await notify_agent(call, "create_topic", "confirmed", True, f"Раздел '{data['topic_name']}' успешно создан.", data=data)
        except ApplicationError as error:
            logger.error("Topic creation failed: %s", error)
            await telegram.edit_status(call, "❌ Не удалось создать раздел.", chat_id=_chat_id(call, data))
            await history_store.append(
                _conversation_key(call, data),
                Message("system", f"Создание раздела не выполнено: {error}"),
            )
            await notify_agent(call, "create_topic", "confirmed", False, str(error), data=data)
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
        await telegram.edit_status(call, "❌ Создание раздела отменено.", chat_id=_chat_id(call, data))
        await notify_agent(call, "create_topic", "cancelled", False, "Создание раздела отменено.", data=data)
        classroom.remove_pending_topic(pending_id)

    async def apply_update(call: CallbackQuery, pending_id: str, resource: str):
        data = classroom.get_pending_update(pending_id)
        if not data or data["resource"] != resource or data["telegram_id"] != call.from_user.id:
            await call.answer("Данные устарели", show_alert=True)
            return
        if _group_action_blocked(data):
            await _reject_group_action(call)
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
                materials_payload = data.get("materials")
                attachments = data.get("telegram_attachments") or []

                if materials_payload is not None or attachments:
                    # Resources are merged with the material's current list so
                    # adding new files never wipes previously attached links.
                    current_list = await classroom.get_course_materials_list(
                        data["telegram_id"], data["course_id"]
                    )
                    current = next(
                        (
                            item for item in current_list
                            if item.id == data["material_id"]
                        ),
                        None,
                    )
                    merged: list[dict] = []
                    if current is not None:
                        merged = [
                            item.model_dump(mode="json", by_alias=True, exclude_none=True)
                            for item in current.materials
                        ]
                    merged.extend(materials_payload or [])

                    if attachments:
                        course = await classroom.get_concrete_course(
                            data["telegram_id"], data["course_id"]
                        )
                        folder_id = course.teacher_folder.id if course.teacher_folder else None
                        for attachment in attachments:
                            file_name, file_bytes = await telegram.get_file_content(attachment.file_id)
                            drive_file = await classroom.upload_to_drive(
                                telegram_id=data["telegram_id"],
                                file_name=attachment.file_name or file_name,
                                content=file_bytes,
                                mime_type=attachment.mime_type or "application/octet-stream",
                                parent_folder_id=folder_id,
                            )
                            merged.append({
                                "driveFile": {
                                    "driveFile": {"id": drive_file["id"]},
                                    "shareMode": "VIEW",
                                }
                            })
                    materials_payload = merged

                await classroom.update_course_material(
                    telegram_id=data["telegram_id"],
                    course_id=data["course_id"],
                    material_id=data["material_id"],
                    title=data["title"],
                    description=data["description"],
                    materials=materials_payload,
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

            await telegram.edit_status(call, message, chat_id=_chat_id(call, data))
            await history_store.append(
                _conversation_key(call, data),
                Message("system", message),
            )
            await notify_agent(call, f"update_{resource}", "confirmed", True, message, data=data)
        except ApplicationError as error:
            await telegram.edit_status(call, "❌ Не удалось изменить объект.", chat_id=_chat_id(call, data))
            await history_store.append(
                _conversation_key(call, data),
                Message("system", f"Изменение не выполнено: {error}"),
            )
            await notify_agent(call, f"update_{resource}", "confirmed", False, str(error), data=data)
        finally:
            classroom.remove_pending_update(pending_id)

    async def cancel_update(call: CallbackQuery, pending_id: str, resource: str):
        data = classroom.get_pending_update(pending_id)
        if not data or data["resource"] != resource or data["telegram_id"] != call.from_user.id:
            await call.answer("Данные устарели", show_alert=True)
            return
        await call.answer()
        await telegram.edit_status(call, "❌ Изменение отменено.", chat_id=_chat_id(call, data))
        await history_store.append(
            _conversation_key(call, data),
            Message("system", "Пользователь отменил изменение."),
        )
        await notify_agent(call, f"update_{resource}", "cancelled", False, "Изменение отменено.", data=data)
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

    if forms is not None:

        @router.callback_query(F.data.startswith("form:create:confirm:"))
        async def confirm_form_creation(call: CallbackQuery):
            pending_id = call.data.split(":")[-1]
            logger.info("Form creation confirmation callback: pending_id=%s", pending_id)
            data = forms.get_pending_form(pending_id)
            if not data or data["telegram_id"] != call.from_user.id:
                await call.answer("Данные устарели", show_alert=True)
                return
            if _group_action_blocked(data):
                await _reject_group_action(call)
                return

            await call.answer()
            await telegram.edit_status(call, "⏳ Создаю форму...", chat_id=_chat_id(call, data))
            try:
                logger.info(
                    "Creating confirmed Google Form: pending_id=%s telegram_id=%s "
                    "title=%r is_quiz=%s questions=%s",
                    pending_id,
                    data["telegram_id"],
                    data["title"],
                    data["is_quiz"],
                    len(data["questions"]),
                )
                form = await forms.create_form_with_questions(
                    telegram_id=data["telegram_id"],
                    title=data["title"],
                    description=data["description"],
                    is_quiz=data["is_quiz"],
                    questions=data["questions"],
                )
                responder_uri = form.responder_uri

                await telegram.edit_status(call, f"✅ Форма *«{data['title']}»* успешно создана!", chat_id=_chat_id(call, data))
                if responder_uri:
                    await telegram.send_form_link(
                        chat_id=_chat_id(call, data),
                        title=data["title"],
                        responder_uri=responder_uri,
                        delivery=_delivery(call, data),
                    )

                await history_store.append(
                    _conversation_key(call, data),
                    Message(
                        "system",
                        f"Пользователь подтвердил создание формы '{data['title']}'. "
                        f"Форма создана: form_id={form.form_id}, ссылка={responder_uri}. "
                        f"Сообщи преподавателю результат и предложи опубликовать её или прикрепить к курсу.",
                    ),
                )
                await notify_agent(
                    call,
                    "create_form",
                    "confirmed",
                    True,
                    json.dumps(
                        {
                            "form_id": form.form_id,
                            "title": data["title"],
                            "responder_uri": responder_uri,
                            "is_quiz": data["is_quiz"],
                            "questions_added": len(data["questions"]),
                        },
                        ensure_ascii=False,
                    ),
                    data=data,
                )
            except ApplicationError as error:
                logger.error("Form creation failed: %s", error)
                await telegram.edit_status(call, "❌ Не удалось создать форму.", chat_id=_chat_id(call, data))
                await history_store.append(
                    _conversation_key(call, data),
                    Message("system", f"Создание формы не выполнено: {error}"),
                )
                await notify_agent(call, "create_form", "confirmed", False, str(error), data=data)
            except Exception:
                logger.exception(
                    "Unexpected Google Form creation failure: pending_id=%s",
                    pending_id,
                )
                await telegram.edit_status(call,
                    "❌ Не удалось создать форму из-за внутренней ошибки.",
                    chat_id=_chat_id(call, data),
                )
                await notify_agent(
                    call,
                    "create_form",
                    "confirmed",
                    False,
                    "Внутренняя ошибка при создании Google Forms.",
                    data=data,
                )
            finally:
                forms.remove_pending_form(pending_id)

        @router.callback_query(F.data.startswith("form:create:cancel:"))
        async def cancel_form_creation(call: CallbackQuery):
            pending_id = call.data.split(":")[-1]
            data = forms.get_pending_form(pending_id)
            if not data or data["telegram_id"] != call.from_user.id:
                await call.answer("Данные устарели", show_alert=True)
                return
            await call.answer()
            await telegram.edit_status(call, f"❌ Создание формы *«{data['title']}»* отменено.", chat_id=_chat_id(call, data))
            await history_store.append(
                _conversation_key(call, data),
                Message("system", f"Пользователь ОТМЕНИЛ создание формы '{data['title']}'."),
            )
            await notify_agent(
                call,
                "create_form",
                "cancelled",
                False,
                f"Создание формы '{data['title']}' отменено.",
                data=data,
            )
            forms.remove_pending_form(pending_id)

        @router.callback_query(F.data.startswith("form:question:confirm:"))
        async def confirm_form_question(call: CallbackQuery):
            pending_id = call.data.split(":")[-1]
            logger.info("Form question confirmation callback: pending_id=%s", pending_id)
            data = forms.get_pending_question(pending_id)
            if not data or data["telegram_id"] != call.from_user.id:
                await call.answer("Данные устарели", show_alert=True)
                return
            if _group_action_blocked(data):
                await _reject_group_action(call)
                return

            await call.answer()
            await telegram.edit_status(call, "⏳ Добавляю вопрос...", chat_id=_chat_id(call, data))
            try:
                await forms.add_question(
                    telegram_id=data["telegram_id"],
                    form_id=data["form_id"],
                    question_spec=data["question"],
                )
                await telegram.edit_status(call, "✅ Вопрос успешно добавлен.", chat_id=_chat_id(call, data))
                await history_store.append(
                    _conversation_key(call, data),
                    Message(
                        "system",
                        f"Пользователь подтвердил добавление вопроса '{data['question']['title']}' "
                        f"в форму '{data['form_title']}' (form_id={data['form_id']}).",
                    ),
                )
                await notify_agent(
                    call,
                    "add_form_question",
                    "confirmed",
                    True,
                    json.dumps(
                        {
                            "form_id": data["form_id"],
                            "question_title": data["question"]["title"],
                        },
                        ensure_ascii=False,
                    ),
                    data=data,
                )
            except ApplicationError as error:
                logger.error("Form question addition failed: %s", error)
                await telegram.edit_status(call, "❌ Не удалось добавить вопрос.", chat_id=_chat_id(call, data))
                await notify_agent(call, "add_form_question", "confirmed", False, str(error), data=data)
            finally:
                forms.remove_pending_question(pending_id)

        @router.callback_query(F.data.startswith("form:question:cancel:"))
        async def cancel_form_question(call: CallbackQuery):
            pending_id = call.data.split(":")[-1]
            data = forms.get_pending_question(pending_id)
            if not data or data["telegram_id"] != call.from_user.id:
                await call.answer("Данные устарели", show_alert=True)
                return
            await call.answer()
            await telegram.edit_status(call, "❌ Добавление вопроса отменено.", chat_id=_chat_id(call, data))
            await notify_agent(call, "add_form_question", "cancelled", False, "Добавление вопроса отменено.", data=data)
            forms.remove_pending_question(pending_id)

        @router.callback_query(F.data.startswith("form:publish:confirm:"))
        async def confirm_form_publish(call: CallbackQuery):
            pending_id = call.data.split(":")[-1]
            logger.info("Form publish confirmation callback: pending_id=%s", pending_id)
            data = forms.get_pending_publish(pending_id)
            if not data or data["telegram_id"] != call.from_user.id:
                await call.answer("Данные устарели", show_alert=True)
                return
            if _group_action_blocked(data):
                await _reject_group_action(call)
                return

            await call.answer()
            await telegram.edit_status(call, "⏳ Публикую форму...", chat_id=_chat_id(call, data))
            try:
                await forms.publish_form(
                    telegram_id=data["telegram_id"],
                    form_id=data["form_id"],
                )
                responder_uri = None
                try:
                    form = await forms.get_form(data["telegram_id"], data["form_id"])
                    responder_uri = form.responder_uri
                except ApplicationError:
                    logger.warning("Failed to refresh form after publish: form_id=%s", data["form_id"])

                await telegram.edit_status(call, f"✅ Форма *«{data['form_title']}»* опубликована!", chat_id=_chat_id(call, data))
                if responder_uri:
                    await telegram.send_form_link(
                        chat_id=_chat_id(call, data),
                        title=data["form_title"],
                        responder_uri=responder_uri,
                        delivery=_delivery(call, data),
                    )

                await history_store.append(
                    _conversation_key(call, data),
                    Message(
                        "system",
                        f"Пользователь подтвердил публикацию формы '{data['form_title']}' "
                        f"(form_id={data['form_id']}). Ссылка: {responder_uri}.",
                    ),
                )
                await notify_agent(
                    call,
                    "publish_form",
                    "confirmed",
                    True,
                    json.dumps(
                        {
                            "form_id": data["form_id"],
                            "title": data["form_title"],
                            "responder_uri": responder_uri,
                        },
                        ensure_ascii=False,
                    ),
                    data=data,
                )
            except ApplicationError as error:
                logger.error("Form publish failed: %s", error)
                await telegram.edit_status(call, "❌ Не удалось опубликовать форму.", chat_id=_chat_id(call, data))
                await notify_agent(call, "publish_form", "confirmed", False, str(error), data=data)
            finally:
                forms.remove_pending_publish(pending_id)

        @router.callback_query(F.data.startswith("form:publish:cancel:"))
        async def cancel_form_publish(call: CallbackQuery):
            pending_id = call.data.split(":")[-1]
            data = forms.get_pending_publish(pending_id)
            if not data or data["telegram_id"] != call.from_user.id:
                await call.answer("Данные устарели", show_alert=True)
                return
            await call.answer()
            await telegram.edit_status(call, "❌ Публикация формы отменена.", chat_id=_chat_id(call, data))
            await notify_agent(call, "publish_form", "cancelled", False, "Публикация формы отменена.", data=data)
            forms.remove_pending_publish(pending_id)

    return router
