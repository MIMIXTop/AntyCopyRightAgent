from openai import AsyncOpenAI

from app.config.settings import settings


class SpeechService:
    def __init__(self) -> None:
        self.model = settings.SPEECH_LLM_MODEL
        self.client = AsyncOpenAI(
            base_url=settings.SPEECH_BASE_URL,
            api_key=settings.speech_api_key,
        )

    async def get_speech(self, text: str) -> bytes:
        speech = await self.client.audio.speech.with_raw_response.create(
            model=self.model,
            input=text,
            voice="coral",
            instructions="Speak in a cheerful and positive tone.",
            response_format="mp3",
        )
        return speech.content