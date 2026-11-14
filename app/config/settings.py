from pathlib import Path
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = BASE_DIR / ".env"


class Settings(BaseSettings):
    BOT_TOKEN: SecretStr
    OPEN_AI_KEY: SecretStr
    CPP_SERVER_URL: str
    PUBLIC_SERVER_URL: str = "http://localhost:8080"
    LLM_MODEL: str
    HTTP_TIMEOUT_SECONDS: float = 15.0
    LLM_BASE_URL: str
    VOICE_BASE_URL: str
    VOICE_TOKEN: SecretStr
    VOICE_LLM_MODEL: str
    SPEECH_BASE_URL: str
    SPEECH_TOKEN: SecretStr
    SPEECH_LLM_MODEL: str
    # Provider-specific voice id passed to the TTS endpoint. The configured
    # model only accepts its own ids; an unknown voice fails with HTTP 400.
    # qwen/qwen-audio-3.0-tts-flash: longanhuan_v3.6, loongjohn.
    SPEECH_VOICE: str = "longanhuan_v3.6"
    # Qwen TTS rejects any speed other than 1, so the parameter is only sent
    # when this is set explicitly (and differs from 1.0).
    SPEECH_SPEED: float | None = None
    # Group chat behaviour. Ephemeral messages are visible only to the member
    # who addressed the bot; the bot must be a group admin to send them outside
    # the 15-second callback window.
    GROUP_REPLIES_EPHEMERAL: bool = True
    GROUP_ACTIONS_EPHEMERAL: bool = True
    GROUP_ALLOW_REPLY_TO_BOT: bool = False
    # In groups the agent may only chat, answer questions, search the web and
    # share links/media. Course, Drive, Sheets and Forms tools stay private.
    GROUP_SAFE_MODE: bool = True

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

    @property
    def voice_api_key(self) -> str:
        return self.VOICE_TOKEN.get_secret_value().strip()

    @property
    def speech_api_key(self) -> str:
        return self.SPEECH_TOKEN.get_secret_value().strip()

    @property
    def public_server_url(self) -> str:
        return self.PUBLIC_SERVER_URL.rstrip("/")


settings = Settings()