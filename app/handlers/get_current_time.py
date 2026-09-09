import datetime


def get_current_time() -> dict:
    now = datetime.datetime.now()
    return {
        'time': now.strftime('%H:%M:%S'),
        'date': now.strftime('%Y-%m-%d'),
        'weekday': now.strftime('%A'),
    }