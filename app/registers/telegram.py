from app.tools.loader import load_schema
from app.core.errors import ToolArgumentsError
from app.agent.speech_service import SpeechService
from app.api.telegram.service import TelegramService
from app.agent.tools import ToolRegistry, ToolContext, ToolResult
from app.core.logging import logger


def register_telegram_tools(registry: ToolRegistry, telegram: TelegramService, speech_service: SpeechService):
    logger.info("Registering Telegram tools")

    async def send(context: ToolContext, args: dict):
        logger.info("send_message tool called: chat_id=%s arguments=%s", context.chat_id, args)
        text = args.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ToolArgumentsError("send_message", "text is required")

        await telegram.send_message(text=text, chat_id=context.chat_id)
        return ToolResult(context.call_id, '{"status":"delivered"}')

    async def speech(context: ToolContext, args: dict):
        logger.info("Speech tool called: chat_id=%s arguments=%s", context.chat_id, args)
        text = args.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ToolArgumentsError("speech", "text is required")
        voice = await speech_service.get_speech(text)
        await telegram.send_speech(speech=voice, chat_id=context.chat_id)
        return ToolResult(context.call_id, '{"status":"delivered"}')

    async def ask_choice(context: ToolContext, args: dict):
        question = args.get("question")
        options = args.get("options")
        if not isinstance(question, str) or not question.strip():
            raise ToolArgumentsError("ask_choice", "question is required")
        if (
            not isinstance(options, list)
            or not 1 <= len(options) <= 20
            or not all(
                isinstance(option, dict)
                and isinstance(option.get("label"), str)
                and option["label"].strip()
                and isinstance(option.get("value"), str)
                and option["value"].strip()
                for option in options
            )
        ):
            raise ToolArgumentsError(
                "ask_choice",
                "options must contain 1 to 20 objects with non-empty label and value strings",
            )
        choice_id = await telegram.request_choice(
            chat_id=context.chat_id,
            user_id=context.user_id,
            question=question,
            options=options,
        )
        return ToolResult(
            context.call_id,
            '{"status":"waiting_for_choice","choice_id":"' + choice_id + '"}',
            terminal=True,
        )

    registry.register("send_message", send, load_schema("send_message"))
    registry.register("speech", speech, load_schema("speech"))
    registry.register("ask_choice", ask_choice, load_schema("ask_choice"))
