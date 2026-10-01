import datetime
from app.core.logging import logger


def get_current_time() -> str:
    logger.info("get_current_time called")
    now = datetime.datetime.now()
    return now.strftime("%H:%M")