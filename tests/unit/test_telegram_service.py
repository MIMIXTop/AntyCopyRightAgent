import pytest
from aiogram.exceptions import TelegramBadRequest

from app.api.telegram.service import TelegramService
from app.core.errors import ApplicationError, UnauthorizedError


class RejectingBot:
    """Telegram answers 'invalid file_id' for invented or expired ids."""

    async def get_file(self, file_id):
        raise TelegramBadRequest(
            method=None,
            message="Bad Request: invalid file_id",
        )

    async def download_file(self, file_path, destination=None):  # pragma: no cover
        raise AssertionError("must not be reached")


class RecordingBot:
    """Captures outgoing messages so tests can check Telegram limits."""

    def __init__(self):
        self.sent = []

    async def send_message(self, **kwargs):
        if len(kwargs["text"]) > 4096:
            raise TelegramBadRequest(
                method=None,
                message="Bad Request: message is too long",
            )
        self.sent.append(kwargs)


@pytest.mark.asyncio
async def test_get_file_content_turns_bad_file_id_into_application_error():
    service = TelegramService(bot=RejectingBot())

    with pytest.raises(ApplicationError) as exc_info:
        await service.get_file_content("file_1")

    assert "file_1" in str(exc_info.value)
    assert "invalid or expired" in str(exc_info.value)


def _long_question(index: int) -> dict:
    return {
        "title": f"Вопрос номер {index}: " + "очень длинное описание вопроса " * 6,
        "type": "radio",
        "options": [
            f"Вариант ответа {index}.{option} — развёрнутое пояснение " * 3
            for option in range(6)
        ],
        "correct_answers": [f"Вариант ответа {index}.0 — развёрнутое пояснение " * 3],
        "points": 2,
        "required": True,
    }


@pytest.mark.asyncio
async def test_request_form_creation_fits_many_questions_into_telegram_limit():
    bot = RecordingBot()
    service = TelegramService(bot=bot)

    # 15 verbose questions easily exceed 4096 characters when rendered fully.
    await service.request_form_creation(
        chat_id=1,
        pending_id="pending-1",
        title="Итоговый тест по Python",
        description="Проверка знаний за модуль. " * 10,
        is_quiz=True,
        questions=[_long_question(index) for index in range(1, 16)],
    )

    assert len(bot.sent) == 1
    message = bot.sent[0]
    assert len(message["text"]) <= TelegramService.TELEGRAM_TEXT_LIMIT
    # Hidden questions are announced instead of silently dropped.
    assert "не показано" in message["text"]
    assert "будут созданы при подтверждении" in message["text"]
    # The confirmation keyboard must still be attached.
    assert message["reply_markup"] is not None


@pytest.mark.asyncio
async def test_request_form_creation_shows_all_short_questions():
    bot = RecordingBot()
    service = TelegramService(bot=bot)

    await service.request_form_creation(
        chat_id=1,
        pending_id="pending-2",
        title="Мини-опрос",
        description="",
        is_quiz=False,
        questions=[
            {"title": "Вам понравилось?", "type": "radio", "options": ["Да", "Нет"]},
            {"title": "Что запомнилось?", "type": "short_text"},
        ],
    )

    text = bot.sent[0]["text"]
    assert "Вам понравилось?" in text
    assert "Что запомнилось?" in text
    assert "не показано" not in text


@pytest.mark.asyncio
async def test_request_form_question_stays_under_telegram_limit():
    bot = RecordingBot()
    service = TelegramService(bot=bot)

    huge_question = {
        "title": "Очень длинный вопрос " * 400,
        "type": "radio",
        "options": ["Вариант " * 100] * 8,
    }

    # RecordingBot raises TelegramBadRequest for messages over 4096 characters.
    await service.request_form_question(
        chat_id=1,
        pending_id="pending-3",
        form_title="Форма с огромным заголовком " * 50,
        question=huge_question,
    )

    assert len(bot.sent[0]["text"]) <= TelegramService.TELEGRAM_TEXT_LIMIT


@pytest.mark.asyncio
async def test_unauthorized_error_sends_the_auth_button_instead_of_raw_error():
    bot = RecordingBot()
    service = TelegramService(bot=bot)

    await service.send_error(chat_id=987654, error=UnauthorizedError())

    assert len(bot.sent) == 1
    message = bot.sent[0]
    assert "Google" in message["text"]
    assert "истёк" in message["text"]
    assert "UnauthorizedError" not in message["text"]
    button = message["reply_markup"].inline_keyboard[0][0]
    assert "987654" in button.url
    assert "/api/auth/google/start" in button.url
