from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from app.config.settings import settings


def get_auth_keyboard(telegram_id: int) -> InlineKeyboardMarkup:
    url = f"{settings.CPP_SERVER_URL}/api/auth/google/start?telegram_id={telegram_id}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Google Authorize", url=url)]
        ]
    )

def get_course_confirm_keyboard(pending_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="Confirm",
                callback_data=f"course:create:confirm:{pending_id}",
            ),
            InlineKeyboardButton(
                text="Cancel",
                callback_data=f"course:create:cancel:{pending_id}",
            )
        ]]
    )