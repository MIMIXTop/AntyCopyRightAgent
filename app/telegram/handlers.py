from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.types import Message as TgMessage
from app.agent.service import AgentService
from app.core.errors import ApplicationError


def create_router(agent: AgentService, error_presenter) -> Router:

    router = Router()

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
            await error_presenter.send(message.chat.id, error)
            return

        if answer:
            await message.answer(answer)

    return router
