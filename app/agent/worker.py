import json

from httpx import AsyncClient

from aiogram.enums import ChatAction
from aiogram import Dispatcher, Bot
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command

from openai import AsyncOpenAI

from app.promts.system_prompt import get_system_prompt
from app.utils.tools import get_model_tools
from app.logger_settings import logger
from app.handlers.get_current_time import get_current_time
from app.handlers.classroom import get_courses
from app.settings import settings


GROQ_API_KEY = settings.OPEN_AI_KEY.get_secret_value()
TELEGRAM_BOT_TOKEN = settings.bot_token_clean

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

client = AsyncOpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=GROQ_API_KEY,
)

@dp.message(Command("start"))
async def handle_start(message: Message):
    await message.answer("Привет! Напиши мне любой вопрос, и я отвечу.")

def get_auth_keyboard(telegram_id: int) -> InlineKeyboardMarkup:
    url = f"{settings.CPP_SERVER_URL}/api/auth/google/start?telegram_id={telegram_id}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Google Authorize", url=url)]
        ]
    )

@dp.message(Command("auth"))
async def handle_auth(message: Message):
    await message.answer(
        "Для доступа к вашим курсам и работам в Google Classroom необходимо авторизоваться:\n\n"
        "Нажмите кнопку ниже, разрешите доступ в Google, после чего возвращайтесь в чат.",
        reply_markup=get_auth_keyboard(message.from_user.id)
    )


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
    tool_names = [t["function"]["name"] for t in tools]
    logger.info(f"Загруженные инструменты: {tool_names}")

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



                elif tool_name == "get_courses":
                    result = await get_courses(telegram_id=message.from_user.id)

                    logger.info(f"Результат get_courses: {result}")

                    if isinstance(result, dict) and result.get("status") == "unauthorized":
                        auth_url = f"{settings.CPP_SERVER_URL}/api/auth/google/start?telegram_id={message.from_user.id}"
                        keyboard = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="🔗 Подключить Google", url=auth_url)]
                        ])

                        await message.answer(
                            "Для проверки курсов мне нужен доступ к вашему Google Classroom 👇",
                            reply_markup=keyboard
                        )

                        result = {"status": "stop", "reason": "user_needs_to_authorize"}
                        should_finish = True

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
                logger.info(f"Модель завершила генерацию текстом: {assistant_message.content!r}")
            return


async def send_telegram_message(chat_id: int, text: str):
    await bot.send_message(chat_id=chat_id, text=text)