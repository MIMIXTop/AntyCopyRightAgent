from pathlib import Path
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"


class Settings(BaseSettings):
    BOT_TOKEN: SecretStr
    OPEN_AI_KEY: SecretStr

    @field_validator("BOT_TOKEN", "OPEN_AI_KEY", mode="bound")
    @classmethod
    def strip_whitespace(cls, value):
        if isinstance(value, str):
            return value.strip()
        return value

    model_config = SettingsConfigDict(
        env_file=ENV_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
    )



settings = Settings()

def _debug_inspect_secrets():
    bot_raw = settings.BOT_TOKEN.get_secret_value()
    openai_raw = settings.OPEN_AI_KEY.get_secret_value()

    print("\n" + "=" * 50)
    print("🔎 [SETTINGS DEBUG]")
    print(
        f"• BOT_TOKEN: длина={len(bot_raw)} | "
        f"начало={bot_raw[:4]!r} | конец={bot_raw[-4:]!r} | "
        f"содержит пробелы={any(c.isspace() for c in bot_raw)}"
    )
    print(
        f"• OPEN_AI_KEY: длина={len(openai_raw)} | "
        f"начало={openai_raw[:4]!r} | конец={openai_raw[-4:]!r} | "
        f"содержит пробелы={any(c.isspace() for c in openai_raw)}"
    )
    print("=" * 50 + "\n")

_debug_inspect_secrets()