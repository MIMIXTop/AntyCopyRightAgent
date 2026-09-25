import datetime


def get_current_time() -> str:
    now = datetime.datetime.now()
    return now.strftime("%H:%M")