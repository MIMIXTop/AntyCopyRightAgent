import json

from aiogram.enums import ChatAction

from app.handlers.get_current_time import get_current_time
from app.settings import settings
from aiogram import Dispatcher, Bot
from aiogram.types import Message
from aiogram.filters import Command
from openai import AsyncOpenAI
from app.promts.system_prompt import get_system_prompt
from app.utils.tools import get_model_tools
from app.logger_settings import logger


GROQ_API_KEY = settings.OPEN_AI_KEY.get_secret_value()
TELEGRAM_BOT_TOKEN = settings.BOT_TOKEN.get_secret_value()

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

client = AsyncOpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=GROQ_API_KEY,
)

@dp.message(Command("start"))
async def handle_start(message: Message):
    await message.answer("Привет! Напиши мне любой вопрос, и я отвечу.")

@dp.message()
async def handle_message(message: Message):
    if not message.text:
        return

    user_id = message.from_user.id
    username = message.from_user.username or "unknown"
    logger.info(f"Новое сообщение от @{username} (ID: {user_id}): {message.text!r}")

    content = message.text
    agent_prompt =  [
        {"role": "system", "content": get_system_prompt()},
        {"role": "user", "content": content},
    ]

    tools = get_model_tools()

    max_iter = 10
    iter = 0

    while iter < max_iter:
        iter += 1
        logger.info(f"Итерация агента: {iter}/{max_iter}")

        try:
            response = await client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=agent_prompt,
                tools=tools,
                tool_choice="auto",
            )
        except Exception as e:
            logger.error(f"Ошибка при запросе к LLM API: {e}", exc_info=True)
            await message.answer("Ой, у меня что-то пошло не так со связью... Попробуй еще раз чуть позже!")
            return

        assistant_message = response.choices[0].message
        agent_prompt.append(assistant_message)

        if assistant_message.content:
            logger.debug(f"Внутренние мысли Киры:\n{assistant_message.content}")

        should_finish = False

        if assistant_message.tool_calls:
            for tool_call in assistant_message.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments or "{}")

                logger.info(f"Вызов инструмента: [{tool_name}] с аргументами: {tool_args}")
                if tool_name == "get_current_time":
                    result = get_current_time()
                    logger.info(f"Результат get_current_time: {result}")

                elif tool_name == "send_message":
                    text_to_send = tool_args.get("text", "")
                    if text_to_send:
                        await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
                        await send_telegram_message(chat_id=message.chat.id, text=text_to_send)
                        logger.info(f"Сообщение отправлено в Telegram: {text_to_send!r}")
                    result = {"status": "delivered"}

                elif tool_name == "finish":
                    should_finish = True
                    logger.info("Агент завершил ход (инструмент finish)")
                    result = {"status": "ok"}

                else:
                    logger.warning(f"Неизвестный инструмент: {tool_name}")
                    result = {"error": f"Unknown tool: {tool_name}"}

                agent_prompt.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, ensure_ascii=False)
                })

            if should_finish:
                logger.info(f"Ход успешно завершён за {iter} итераций.")
                return
        else:
            if assistant_message.content:
                logger.debug(f"Модель завершила генерацию текстом: {assistant_message.content!r}")
            return


async def send_telegram_message(chat_id: int, text: str):
    await bot.send_message(chat_id=chat_id, text=text)