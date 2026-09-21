from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from app.config.settings import settings


def get_auth_keyboard(telegram_id: int) -> InlineKeyboardMarkup:
    url = f"{settings.CPP_SERVER_URL}/api/auth/google/start?telegram_id={telegram_id}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Google Authorize", url=url)]
        ]
    )