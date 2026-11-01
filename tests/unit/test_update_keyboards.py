from app.api.telegram.keyboards import (
    get_update_announcement_keyboard,
    get_update_course_keyboard,
    get_update_work_keyboard,
)


def test_update_course_keyboard_has_confirmation_callbacks():
    keyboard = get_update_course_keyboard("pending-1")
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert callbacks == [
        "course:update:confirm:pending-1",
        "course:update:cancel:pending-1",
    ]


def test_update_announcement_keyboard_has_confirmation_callbacks():
    keyboard = get_update_announcement_keyboard("pending-1")
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert callbacks == [
        "announcement:update:confirm:pending-1",
        "announcement:update:cancel:pending-1",
    ]


def test_update_assignment_keyboard_has_confirmation_callbacks():
    keyboard = get_update_work_keyboard("pending-1")
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert callbacks == [
        "course:work:update:confirm:pending-1",
        "course:work:update:cancel:pending-1",
    ]
