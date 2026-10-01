from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from app.config.settings import settings


def get_auth_keyboard(telegram_id: int) -> InlineKeyboardMarkup:
    url = f"{settings.CPP_SERVER_URL}/api/auth/google/start?telegram_id={telegram_id}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Google Authorize", url=url)]
        ]
    )

def get_course_confirm_keyboard(pending_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="Подтвердить",
                callback_data=f"course:create:confirm:{pending_id}",
            ),
            InlineKeyboardButton(
                text="Отменить",
                callback_data=f"course:create:cancel:{pending_id}",
            )
        ]]
    )

def get_course_announcement_keyboard(pending_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="Подтвердить",
                callback_data=f"course:announcement:create:confirm:{pending_id}",
            ),
            InlineKeyboardButton(
                text="Отменить",
                callback_data=f"course:announcement:create:cancel:{pending_id}",
            )
        ]]
    )