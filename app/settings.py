import os
from pathlib import Path
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"


class Settings(BaseSettings):
    BOT_TOKEN: SecretStr
    OPEN_AI_KEY: SecretStr
    CPP_SERVER_URL: str

    model_config = SettingsConfigDict(
        env_file=ENV_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def bot_token_clean(self) -> str:
        return self.BOT_TOKEN.get_secret_value().strip()

    @property
    def openai_key_clean(self) -> str:
        return self.OPEN_AI_KEY.get_secret_value().strip()


settings = Settings()

raw_token = settings.BOT_TOKEN.get_secret_value()
cleaned_token = settings.bot_token_clean

print("=" * 50)
print(f"DEBUG: Сырая длина токена = {len(raw_token)}")
print(f"DEBUG: Очищенная длина токена = {len(cleaned_token)}")
print(f"DEBUG: Начало = {cleaned_token[:5]!r} | Конец = {cleaned_token[-5:]!r}")
print(f"DEBUG: Есть пробелы внутри токена? {' ' in cleaned_token}")
print("=" * 50)