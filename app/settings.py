import os
from dotenv import load_dotenv

class Settings:
    def __init__(self, env_path: str = ".env"):
        load_dotenv(dotenv_path=env_path)
        self.BOT_TOKEN = os.getenv("BOT_TOKEN")

config = Settings()