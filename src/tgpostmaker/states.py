from aiogram.fsm.state import State, StatesGroup


class AutopostStates(StatesGroup):
    waiting_post = State()
    waiting_buttons_append = State()
    waiting_buttons_replace = State()
    waiting_schedule = State()

