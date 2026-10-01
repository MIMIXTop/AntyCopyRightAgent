import json
from app.tools.loader import load_schema
from app.core.errors import ToolArgumentsError
from app.telegram.service import TelegramService
from app.agent.tools import ToolRegistry, ToolContext, ToolResult
from app.core.logging import logger


def register_telegram_tools(registry: ToolRegistry, telegram: TelegramService):
    logger.info("Registering Telegram tools")

    async def send(context: ToolContext, args: dict):
        logger.info("send_message tool called: chat_id=%s arguments=%s", context.chat_id, args)
        text = args.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ToolArgumentsError("send_message", "text is required")

        await telegram.send_message(text=text, chat_id=context.chat_id)
        return ToolResult(context.call_id, '{"status":"delivered"}')

    registry.register("send_message", send, load_schema("send_message"))