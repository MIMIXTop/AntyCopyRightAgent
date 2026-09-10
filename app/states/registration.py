from aiogram.fsm.state import StatesGroup, State


class Reg(StatesGroup):
    username = State()
    token = State()