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

def get_course_work_keyboard(pending_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="Подтвердить",
                callback_data=f"course:work:create:confirm:{pending_id}",
            ),
            InlineKeyboardButton(
                text="Отменить",
                callback_data=f"course:work:create:cancel:{pending_id}",
            )
        ]]
    )

def get_update_course_keyboard(pending_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="Подтвердить",
                callback_data=f"course:update:confirm:{pending_id}",
            ),
            InlineKeyboardButton(
                text="Отменить",
                callback_data=f"course:update:cancel:{pending_id}",
            )
        ]]
    )

def get_update_announcement_keyboard(pending_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="Подтвердить",
                callback_data=f"announcement:update:confirm:{pending_id}",
            ),
            InlineKeyboardButton(
                text="Отменить",
                callback_data=f"announcement:update:cancel:{pending_id}",
            )
        ]]
    )

def get_update_work_keyboard(pending_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="Подтвердить",
                callback_data=f"course:work:update:confirm:{pending_id}",
            ),
            InlineKeyboardButton(
                text="Отменить",
                callback_data=f"course:work:update:cancel:{pending_id}",
            )
        ]]
    )

def get_invite_url_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="Подключится к классу",
                url=url
            )
        ]]
    )