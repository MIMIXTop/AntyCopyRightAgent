from openai import AsyncOpenAI

from app.config.settings import settings
class VoiceService:

    def __init__(self):
        self.model = settings.VOICE_LLM_MODEL
        self.client = AsyncOpenAI(
            base_url=settings.VOICE_BASE_URL,
            api_key= settings.voice_api_key,
        )

    async def transcription_voice(self, voice: bytes) -> str:

        res = await self.client.audio.transcriptions.create(
            model=self.model,
            file=("voice.ogg", voice),
            language="ru"
        )
        return res.text

