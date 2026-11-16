from pathlib import Path
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = BASE_DIR / ".env"


class Settings(BaseSettings):
    BOT_TOKEN: SecretStr
    OPEN_AI_KEY: SecretStr
    CPP_SERVER_URL: str
    PUBLIC_SERVER_URL: str = "http://127.0.0.1:8080"
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
    # Document viewing. Text PDFs are read without machine learning; OCR only
    # runs for scans and pages without a text layer, so it is safe to keep on.
    DOCUMENT_OCR_ENABLED: bool = True
    # PP-OCR recogniser: "eslav" covers Russian/Ukrainian/Belarusian,
    # "cyrillic" the remaining Cyrillic languages.
    DOCUMENT_OCR_LANG: str = "eslav"
    # Table structure extraction is accurate but slow (~70 s for 72 slides).
    DOCUMENT_TABLE_STRUCTURE: bool = False
    DOCUMENT_MAX_PAGES: int = 100
    DOCUMENT_MAX_FILE_MB: int = 30
    DOCUMENT_MAX_CHARS: int = 50_000
    # Character budget for one document_view tool result. The model gets a
    # bounded preview instead of the whole extracted document.
    DOCUMENT_TOOL_MAX_CHARS: int = 4000
    # How long Telegram attachments stay available for confirmation turns
    # (buttons arrive without media, so the files must be remembered).
    ATTACHMENT_MEMORY_TTL_SECONDS: int = 1800
    # Live logs. The agent has no web panel: formatted records are pushed to
    # the server dashboard (`/dashboard`), which already streams logs over
    # WebSocket. The token must match AGENT_LOG_TOKEN on the server.
    REMOTE_LOG_ENABLED: bool = True
    LOG_REMOTE_URL: str = ""  # empty -> CPP_SERVER_URL + /dashboard/api/logs/ingest
    LOG_REMOTE_TOKEN: str = ""
    LOG_REMOTE_SERVICE: str = "telegram-agent"
    # Rotating file log, so ``tail -f`` keeps working when the bot runs
    # directly on the host (no ``docker logs``). Set LOG_FILE_ENABLED=false
    # to keep stdout only.
    LOG_FILE_ENABLED: bool = True
    LOG_FILE_PATH: str = str(BASE_DIR / "logs" / "kira.log")
    LOG_FILE_MAX_BYTES: int = 10 * 1024 * 1024
    LOG_FILE_BACKUPS: int = 5
    # Directory with pre-downloaded docling/rapidocr models. The Docker image
    # points it at /opt/docling-models; when unset docling downloads on demand.
    DOCUMENT_ARTIFACTS_PATH: str | None = None

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