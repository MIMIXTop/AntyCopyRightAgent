from aiogram import Router
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.types import Message as TgMessage
from app.agent.service import AgentService
from app.core.errors import ApplicationError
from app.telegram.keyboards import get_auth_keyboard


def create_router(agent: AgentService, error_presenter) -> Router:

    router = Router()

    @router.message(Command("auth"))
    async def auth(message: TgMessage):
        await message.answer(
            "Для доступа к вашим курсам и работам в Google Classroom необходимо авторизоваться:\n\n"
            "Нажмите кнопку ниже, разрешите доступ в Google, после чего возвращайтесь в чат.",
            reply_markup=get_auth_keyboard(message.from_user.id)
        )

    @router.message()
    async def handle_message(message: TgMessage) -> None:
        if message.from_user is None or message.text is None:
            return

        try:
            answer = await agent.handle(
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                text=message.text,
            )
        except ApplicationError as error:
            await error_presenter.send_message(error, message.chat.id)
            return

        if answer:
            await message.answer(answer)
    return router
