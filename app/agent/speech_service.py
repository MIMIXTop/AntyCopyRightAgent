from openai import AsyncOpenAI

from app.agent.prompt import load_speech_prompt
from app.config.settings import settings
from app.core.logging import logger

# The TTS endpoint rejects requests with a 400 when `instructions` exceed
# 500 characters, so the whole payload (base persona + per-phrase addition)
# must fit into that budget.
MAX_INSTRUCTION_CHARS = 500
# Schema/handler cap for the per-phrase addition; the service still truncates
# defensively against whatever room the base persona actually leaves.
MAX_EXTRA_CHARS = 150
PHRASE_MARKER = "\n\nFor this phrase: "


class SpeechService:
    def __init__(self) -> None:
        self.model = settings.SPEECH_LLM_MODEL
        self.client = AsyncOpenAI(
            base_url=settings.SPEECH_BASE_URL,
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

    async def get_speech(self, text: str, instructions: str | None = None) -> bytes:
        prompt = self._build_instructions(instructions)
        speech = await self.client.audio.speech.with_raw_response.create(
            model=self.model,
            input=text,
            voice="Serena",
            instructions=prompt,
            response_format="mp3",
            speed=1.1
        )
        return speech.content
