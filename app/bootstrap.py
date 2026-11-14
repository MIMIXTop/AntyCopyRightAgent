from dataclasses import dataclass
import httpx
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats
from openai import AsyncOpenAI

from app.agent.history import InMemoryHistoryStore
from app.agent.image_store import ImageStore
from app.agent.llm import OpenAIAdapter
from app.agent.models import Message, ToolContext, ToolResult
from app.agent.service import AgentService
from app.agent.speech_service import SpeechService
from app.agent.tools import ToolRegistry
from app.api.telegram.service import TelegramService
from app.tools.loader import load_schema
from app.api.classroom.client import ClassroomClient
from app.api.classroom.service import ClassroomService
from app.api.drive.client import DriveClient
from app.api.forms.client import FormsClient
from app.api.forms.service import FormsService
from app.api.sheets.client import SheetsClient
from app.api.sheets.service import SheetsService
from app.handlers.web_search import WebSearchService
from app.registers.classroom import register_classroom_tools
from app.registers.forms import register_forms_tools
from app.registers.image_tools import register_image_tools
from app.registers.telegram import register_telegram_tools
from app.registers.web_search import register_web_search
from app.registers.sheets import register_sheets_tools
from app.registers.drive import register_drive_tools
from app.registers.document_view import register_document_views
from app.agent.document_view_service import DocumentViewService
from app.agent.prompt import load_system_prompt
from app.config.settings import Settings
from app.core.logging import configure_logging
from app.api.telegram.handlers import create_router
from app.api.telegram.callbacks import create_callback_router
from app.core.logging import logger
from app.agent.voice_service import VoiceService


@dataclass
class Application:
    bot: Bot
    dispatcher: Dispatcher
    http_client: httpx.AsyncClient
    llm_client: AsyncOpenAI
    image_store: ImageStore

    async def close(self) -> None:
        await self.llm_client.close()
        await self.http_client.aclose()
        await self.image_store.close()
        await self.bot.session.close()


async def build_application(settings: Settings) -> Application:
    logger.info("Application bootstrap started: cpp_server=%s llm_model=%s", settings.CPP_SERVER_URL,
                settings.LLM_MODEL)
    configure_logging()
    http_client = httpx.AsyncClient(
        base_url=settings.CPP_SERVER_URL.rstrip("/"),
        timeout=settings.HTTP_TIMEOUT_SECONDS,
    )

    async def resolve_role(telegram_id: int) -> str:
        response = await http_client.get(
            "/api/auth/telegram-role",
            params={"telegram_id": telegram_id},
        )
        if response.status_code == 404:
            return "teacher"
        response.raise_for_status()
        payload = response.json()
        role = payload.get("role")
        return role if isinstance(role, str) and role in {"teacher", "admin"} else "teacher"
    llm_client = AsyncOpenAI(
        base_url=settings.LLM_BASE_URL.rstrip("/"),
        api_key=settings.openai_api_key,
    )
    bot = Bot(
        token=settings.bot_token_clean,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    # The username is needed to recognise @mentions in group chats and to
    # register group commands as /command@username.
    try:
        me = await bot.me()
        bot_username = me.username
        logger.info(
            "Telegram bot identity resolved: id=%s username=%s",
            me.id,
            bot_username,
        )
    except Exception as error:
        # A temporary Telegram outage must not keep the whole bot from starting;
        # private chats still work, group mentions stay disabled until restart.
        logger.warning("Unable to resolve bot identity: %s", error)
        bot_username = None

    web_service = WebSearchService(10)

    voice_service = VoiceService()
    speech_service = SpeechService()
    drive = DriveClient(http_client)
    classroom = ClassroomService(
        ClassroomClient(http_client),
        drive_client=drive,
    )
    sheets = SheetsService(SheetsClient(http_client))
    forms = FormsService(FormsClient(http_client))
    telegram = TelegramService(
        bot,
        group_actions_ephemeral=settings.GROUP_ACTIONS_EPHEMERAL,
    )
    image_store = ImageStore()
    registry = ToolRegistry()
    register_classroom_tools(registry, classroom, telegram)
    register_telegram_tools(registry, telegram, speech_service)
    register_web_search(registry, web_service)
    register_image_tools(registry, telegram, image_store)
    register_sheets_tools(registry, sheets)
    register_drive_tools(registry, drive)
    register_forms_tools(registry, forms, telegram)
    register_document_views(registry, DocumentViewService())

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

    storage = InMemoryHistoryStore(
        system_message=Message("system", load_system_prompt()),
    )

    agent = AgentService(
        llm=OpenAIAdapter(llm_client, settings.LLM_MODEL),
        history=storage,
        tools=registry,
        role_resolver=resolve_role,
        group_safe_mode=settings.GROUP_SAFE_MODE,
    )
    # /ask is declared ephemeral: in groups Telegram shows it in the command
    # menu and the follow-up exchange stays private to the caller.
    try:
        await bot.set_my_commands(
            [
                BotCommand(
                    command="ask",
                    description="Приватно спросить агента в группе",
                    is_ephemeral=True,
                ),
                BotCommand(command="auth", description="Авторизовать Google Classroom"),
                BotCommand(command="reset", description="Очистить контекст диалога"),
            ],
            scope=BotCommandScopeAllGroupChats(),
        )
    except Exception as error:
        # Command metadata is cosmetic; never block startup because of it.
        logger.warning("Unable to publish group commands: %s", error)
    dispatcher = Dispatcher()
    dispatcher.include_router(
        create_router(
            agent,
            bot,
            voice_service,
            telegram,
            bot_username=bot_username,
            group_replies_ephemeral=settings.GROUP_REPLIES_EPHEMERAL,
            group_allow_reply_to_bot=settings.GROUP_ALLOW_REPLY_TO_BOT,
        )
    )
    dispatcher.include_router(
        create_callback_router(
            classroom=classroom,
            history_store=storage,
            telegram=telegram,
            agent=agent,
            forms=forms,
            group_safe_mode=settings.GROUP_SAFE_MODE,
        )
    )
    logger.info("Application bootstrap completed")
    return Application(bot, dispatcher, http_client, llm_client, image_store)
