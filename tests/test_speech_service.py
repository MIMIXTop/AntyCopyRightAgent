from types import SimpleNamespace

import httpx
import openai
import pytest

from app.agent.speech_service import SpeechService
from app.core.errors import LLMServiceError


class _FakeRawResponse:
    def __init__(self, content: bytes = b"mp3-bytes"):
        self.content = content


class _FakeSpeechEndpoint:
    def __init__(self, response=None, error: Exception | None = None):
        self.response = response or _FakeRawResponse()
        self.error = error
        self.calls: list[dict] = []
        self.with_raw_response = SimpleNamespace(create=self._create)

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class _FakeClient:
    def __init__(self, response=None, error=None):
        self.speech = _FakeSpeechEndpoint(response=response, error=error)
        self.audio = SimpleNamespace(speech=self.speech)


def make_service(
    *,
    voice: str = "longanhuan_v3.6",
    speed: float | None = None,
    response=None,
    error=None,
) -> tuple[SpeechService, _FakeClient]:
    service = SpeechService.__new__(SpeechService)
    service.model = "qwen/qwen-audio-3.0-tts-flash"
    service.base_url = "https://openrouter.ai/api/v1"
    service.voice = voice
    service.speed = speed
    service.base_instructions = "BASE PERSONA"
    client = _FakeClient(response=response, error=error)
    service.client = client
    return service, client


def make_bad_request(message: str = "boom detail") -> openai.BadRequestError:
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/audio/speech")
    response = httpx.Response(400, request=request)
    return openai.BadRequestError(
        "Error code: 400",
        response=response,
        body={"error": {"message": message, "code": 400}},
    )


def test_payload_uses_configured_voice_and_skips_speed():
    service, client = make_service(voice="loongjohn", speed=None)

    payload = service._build_payload("Привет", "BASE PERSONA")

    assert payload == {
        "model": "qwen/qwen-audio-3.0-tts-flash",
        "input": "Привет",
        "voice": "loongjohn",
        "response_format": "mp3",
        "instructions": "BASE PERSONA",
    }


def test_payload_sends_speed_only_when_not_default():
    service, _ = make_service(speed=1.0)
    assert "speed" not in service._build_payload("Привет", "BASE PERSONA")

    service, _ = make_service(speed=1.1)
    assert service._build_payload("Привет", "BASE PERSONA")["speed"] == 1.1


def test_payload_omits_empty_instructions():
    service, _ = make_service()

    assert "instructions" not in service._build_payload("Привет", "")


@pytest.mark.asyncio
async def test_get_speech_returns_provider_audio(monkeypatch):
    service, client = make_service(response=_FakeRawResponse(b"audio"))
    monkeypatch.setattr(
        "app.agent.speech_service._to_telegram_voice", lambda audio: b"ogg:" + audio
    )

    assert await service.get_speech("Привет") == b"ogg:audio"
    assert client.speech.calls[0]["voice"] == "longanhuan_v3.6"
    assert client.speech.calls[0]["instructions"] == "BASE PERSONA"


@pytest.mark.asyncio
async def test_get_speech_converts_mp3_payload_to_ogg(monkeypatch):
    service, _ = make_service(response=_FakeRawResponse(b"mp3-bytes"))
    converted: list[bytes] = []

    def fake_convert(audio: bytes) -> bytes:
        converted.append(audio)
        return b"ogg-bytes"

    monkeypatch.setattr("app.agent.speech_service._to_telegram_voice", fake_convert)

    assert await service.get_speech("Привет") == b"ogg-bytes"
    assert converted == [b"mp3-bytes"]


def test_to_telegram_voice_falls_back_when_ffmpeg_is_missing(monkeypatch):
    from app.agent import speech_service

    def missing(cmd, data):
        raise FileNotFoundError(2, "No such file or directory", "ffmpeg")

    monkeypatch.setattr(speech_service, "_ffmpeg", missing)

    assert speech_service._to_telegram_voice(b"mp3") == b"mp3"


def test_to_telegram_voice_falls_back_when_ffmpeg_fails(monkeypatch):
    import subprocess

    from app.agent import speech_service

    def broken(cmd, data):
        raise subprocess.CalledProcessError(
            1, cmd, stderr=b"Invalid data found when processing input"
        )

    monkeypatch.setattr(speech_service, "_ffmpeg", broken)

    assert speech_service._to_telegram_voice(b"mp3") == b"mp3"


@pytest.mark.asyncio
async def test_get_speech_surfaces_provider_reason_on_400():
    service, _ = make_service(error=make_bad_request("speed is not supported"))

    with pytest.raises(LLMServiceError) as excinfo:
        await service.get_speech("Привет")

    message = str(excinfo.value)
    assert "speed is not supported" in message
    assert "qwen/qwen-audio-3.0-tts-flash" in message
    assert "longanhuan_v3.6" in message


@pytest.mark.asyncio
async def test_get_speech_reports_empty_audio():
    service, _ = make_service(response=_FakeRawResponse(b""))

    with pytest.raises(LLMServiceError, match="empty audio"):
        await service.get_speech("Привет")
