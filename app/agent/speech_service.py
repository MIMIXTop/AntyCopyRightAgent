import asyncio
import subprocess

import openai
from openai import AsyncOpenAI

from app.agent.prompt import load_speech_prompt
from app.config.settings import settings
from app.core.errors import LLMServiceError
from app.core.logging import logger

# Defensive budget for `instructions`: the endpoint rejects oversized payloads,
# but the exact limit depends on the provider behind the model.
MAX_INSTRUCTION_CHARS = 500
# Schema/handler cap for the per-phrase addition; the service still truncates
# defensively against whatever room the base persona actually leaves.
MAX_EXTRA_CHARS = 150
PHRASE_MARKER = "\n\nFor this phrase: "
DEFAULT_VOICE = "longanhuan_v3.6"
VOICE_BITRATE = "32k"
VOICE_SAMPLE_RATE = 48000


def _ffmpeg(cmd: list[str], data: bytes) -> bytes:
    proc = subprocess.run(cmd, input=data, capture_output=True, check=True)
    return proc.stdout


def _to_telegram_voice(audio: bytes) -> bytes:
    try:
        return _ffmpeg(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-i", "pipe:0",
                "-vn", "-ac", "1", "-ar", str(VOICE_SAMPLE_RATE),
                "-c:a", "libopus", "-b:a", VOICE_BITRATE,
                "-f", "ogg", "pipe:1",
            ],
            audio,
        )
    except FileNotFoundError:
        logger.warning(
            "ffmpeg is not installed; sending the provider audio without OGG conversion"
        )
        return audio
    except subprocess.CalledProcessError as error:
        stderr = (error.stderr or b"").decode(errors="replace").strip()
        logger.warning(
            "ffmpeg conversion failed (%s); sending the provider audio as is",
            stderr[:300] or f"exit code {error.returncode}",
        )
        return audio


def _voice_duration(audio: bytes) -> int:
    out = _ffmpeg(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1",
            "pipe:0",
        ],
        audio,
    )
    return max(1, int(float(out.decode().strip())))


def _provider_reason(error: openai.APIError) -> str:
    """Extract the human-readable reason from a provider error response."""
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        detail = body.get("error")
        if isinstance(detail, dict):
            message = detail.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        message = body.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    message = getattr(error, "message", None) or str(error)
    return message.strip() or "unknown provider error"


class SpeechService:
    def __init__(self) -> None:
        self.model = settings.SPEECH_LLM_MODEL
        self.base_url = settings.SPEECH_BASE_URL.rstrip("/")
        self.voice = settings.SPEECH_VOICE.strip() or DEFAULT_VOICE
        self.speed = settings.SPEECH_SPEED
        self.client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=settings.speech_api_key,
        )
        self.base_instructions = load_speech_prompt().strip()

    def _build_instructions(self, extra: str | None = None) -> str:
        base = self.base_instructions
        extra = (extra or "").strip()
        if not extra:
            return base[:MAX_INSTRUCTION_CHARS]

        allowed = MAX_INSTRUCTION_CHARS - len(base) - len(PHRASE_MARKER)
        if allowed <= 0:
            logger.warning(
                "Base speech instructions leave no room (%s chars), dropping per-phrase addition",
                len(base),
            )
            return base[:MAX_INSTRUCTION_CHARS]

        combined = f"{base}{PHRASE_MARKER}{extra[:allowed]}"
        logger.info(
            "Speech instructions combined: base_len=%s extra_len=%s total_len=%s",
            len(base),
            len(extra),
            len(combined),
        )
        return combined

    def _build_payload(self, text: str, instructions: str) -> dict:
        payload: dict = {
            "model": self.model,
            "input": text,
            "voice": self.voice,
            "response_format": "mp3",
        }
        if instructions:
            payload["instructions"] = instructions
        # Qwen TTS answers 400 to `speed` values other than 1 ("does not support
        # the speed parameter"), so only send it when explicitly configured.
        if self.speed is not None and self.speed != 1.0:
            payload["speed"] = self.speed
        return payload

    async def get_speech(self, text: str, instructions: str | None = None) -> bytes:
        prompt = self._build_instructions(instructions)
        payload = self._build_payload(text, prompt)
        try:
            speech = await self.client.audio.speech.with_raw_response.create(**payload)
        except openai.AuthenticationError as error:
            raise LLMServiceError(
                "Speech provider rejected SPEECH_TOKEN (401). "
                "Replace it with an active token for the configured provider."
            ) from error
        except openai.BadRequestError as error:
            reason = _provider_reason(error)
            logger.warning(
                "Speech payload rejected: model=%s voice=%s reason=%s",
                self.model,
                self.voice,
                reason,
            )
            raise LLMServiceError(
                f"Speech provider rejected the request for model {self.model!r} "
                f"(voice={self.voice!r}): {reason}"
            ) from error
        except openai.OpenAIError as error:
            raise LLMServiceError(
                f"Speech provider request failed for model {self.model!r}: "
                f"{_provider_reason(error)}"
            ) from error
        if not speech.content:
            raise LLMServiceError("Speech provider returned an empty audio response.")
        if payload["response_format"] == "mp3":
            return await asyncio.to_thread(_to_telegram_voice, speech.content)
        return speech.content
