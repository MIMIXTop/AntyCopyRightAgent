from dataclasses import dataclass
import httpx
from aiogram import Bot, Dispatcher
from openai import AsyncOpenAI

from app.agent.history import InMemoryHistoryStore
from app.agent.llm import OpenAIAdapter
from app.agent.models import Message, ToolContext, ToolResult
from app.agent.service import AgentService
from app.agent.tools import ToolRegistry
from app.telegram.service import TelegramService
from app.tools.loader import load_schema
from app.classroom.client import ClassroomClient
from app.classroom.service import ClassroomService
from app.registers.classroom import register_classroom_tools
from app.registers.telegram import register_telegram_tools
from app.agent.prompt import load_system_prompt
from app.config.settings import Settings
from app.core.logging import configure_logging
from app.telegram.handlers import create_router


@dataclass
class Application:
    bot: Bot
    dispatcher: Dispatcher
    http_client: httpx.AsyncClient
    llm_client: AsyncOpenAI

    async def close(self) -> None:
        await self.llm_client.close()
        await self.http_client.aclose()
        await self.bot.session.close()



async def build_application(settings: Settings) -> Application:
    configure_logging()
    http_client = httpx.AsyncClient(
        base_url=settings.CPP_SERVER_URL.rstrip("/"),
        timeout=settings.HTTP_TIMEOUT_SECONDS,
    )
    llm_client = AsyncOpenAI(
        base_url=settings.LLM_BASE_URL.rstrip("/"),
        api_key=settings.openai_api_key,
    )
    bot = Bot(token=settings.bot_token_clean)

    classroom = ClassroomService(ClassroomClient(http_client))
    telegram = TelegramService(bot)
    registry = ToolRegistry()
    register_classroom_tools(registry, classroom)
    register_telegram_tools(registry ,telegram)

    async def current_time(context: ToolContext, arguments: dict):
        from app.handlers.get_current_time import get_current_time

        if arguments:
            from app.core.errors import ToolArgumentsError

            raise ToolArgumentsError("get_current_time", "no arguments expected")
        import json

        return ToolResult(context.call_id, json.dumps(get_current_time()))

    async def finish(context: ToolContext, arguments: dict):
        if arguments:
            from app.core.errors import ToolArgumentsError

            raise ToolArgumentsError("finish", "no arguments expected")
        return ToolResult(context.call_id, '{"status":"ok"}', terminal=True)

    registry.register("get_current_time", current_time, load_schema("get_current_time"))
    registry.register("finish", finish, load_schema("finish"))

    agent = AgentService(
        llm=OpenAIAdapter(llm_client, settings.LLM_MODEL),
        history=InMemoryHistoryStore(
            system_message=Message("system", load_system_prompt()),
        ),
        tools=registry,
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(create_router(agent, telegram))
    return Application(bot, dispatcher, http_client, llm_client)