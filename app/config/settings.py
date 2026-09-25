from pathlib import Path
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = BASE_DIR / ".env"


class Settings(BaseSettings):
    BOT_TOKEN: SecretStr
    OPEN_AI_KEY: SecretStr
    CPP_SERVER_URL: str
    LLM_MODEL: str
    HTTP_TIMEOUT_SECONDS: float = 15.0
    LLM_BASE_URL: str

    model_config = SettingsConfigDict(
        env_file=ENV_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def bot_token_clean(self) -> str:
        return self.BOT_TOKEN.get_secret_value().strip()

    @property
    def openai_api_key(self) -> str:
        return self.OPEN_AI_KEY.get_secret_value().strip()


settings = Settings()