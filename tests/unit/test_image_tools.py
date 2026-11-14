import io
import json
import time

import httpx
import pytest
from PIL import Image

from app.agent.image_store import (
    ImageDownloadError,
    ImageNotFoundError,
    ImageStore,
    StoredImage,
)
from app.agent.models import ToolContext
from app.agent.tools import ToolRegistry
from app.api.telegram.service import TelegramService
from app.core.errors import ToolArgumentsError
from app.registers.image_tools import register_image_tools
from app.tools.loader import load_schema


def _png_bytes(width: int = 4, height: int = 3) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color="red").save(buffer, format="PNG")
    return buffer.getvalue()


def _image_response(payload: bytes, content_type: str = "image/png") -> httpx.Response:
    return httpx.Response(200, content=payload, headers={"content-type": content_type})


class FakeBot:
    def __init__(self):
        self.photos = []

    async def send_photo(self, **kwargs):
        self.photos.append(kwargs)


class FakeTelegramService(TelegramService):
    def __init__(self):
        super().__init__(bot=FakeBot())


def _store(handler) -> ImageStore:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return ImageStore(client=client)


def _registry(store: ImageStore, telegram: TelegramService) -> ToolRegistry:
    registry = ToolRegistry()
    register_image_tools(registry, telegram, store)
    return registry


@pytest.mark.asyncio
async def test_download_image_returns_metadata_and_stores_bytes():
    payload = _png_bytes()
    store = _store(lambda request: _image_response(payload))
    registry = _registry(store, FakeTelegramService())

    result = await registry.call(
        "download_image",
        ToolContext(chat_id=1, user_id=2, call_id="call-1"),
        {"image_url": "https://example.test/cat.png"},
    )

    data = json.loads(result.content)
    assert data["status"] == "success"
    assert data["mime_type"] == "image/png"
    assert data["width"] == 4
    assert data["height"] == 3
    assert data["size_bytes"] == len(payload)
    assert data["source_url"] == "https://example.test/cat.png"
    assert "data" not in data
    assert store.get(data["image_id"], chat_id=1).data == payload


@pytest.mark.asyncio
async def test_download_image_rejects_non_image_response():
    store = _store(
        lambda request: _image_response(b"<html>not an image</html>", "text/html")
    )
    registry = _registry(store, FakeTelegramService())

    with pytest.raises(ImageDownloadError):
        await registry.call(
            "download_image",
            ToolContext(1, 2, "call-1"),
            {"image_url": "https://example.test/page"},
        )


@pytest.mark.asyncio
async def test_download_image_rejects_non_http_scheme():
    store = _store(lambda request: _image_response(_png_bytes()))
    registry = _registry(store, FakeTelegramService())

    with pytest.raises(ImageDownloadError):
        await registry.call(
            "download_image",
            ToolContext(1, 2, "call-1"),
            {"image_url": "ftp://example.test/cat.png"},
        )


@pytest.mark.asyncio
async def test_download_image_rejects_oversized_response():
    store = _store(lambda request: _image_response(b"\x89PNG\r\n\x1a\n" + b"x" * 200))
    store.MAX_BYTES = 50
    registry = _registry(store, FakeTelegramService())

    with pytest.raises(ImageDownloadError, match="size limit"):
        await registry.call(
            "download_image",
            ToolContext(1, 2, "call-1"),
            {"image_url": "https://example.test/huge.png"},
        )


@pytest.mark.asyncio
async def test_download_image_requires_url():
    registry = _registry(
        _store(lambda request: _image_response(_png_bytes())),
        FakeTelegramService(),
    )

    with pytest.raises(ToolArgumentsError):
        await registry.call("download_image", ToolContext(1, 2, "call-1"), {})


@pytest.mark.asyncio
async def test_send_image_delivers_photo_with_caption():
    payload = _png_bytes()
    telegram = FakeTelegramService()
    store = _store(lambda request: _image_response(payload))
    registry = _registry(store, telegram)

    downloaded = json.loads(
        (
            await registry.call(
                "download_image",
                ToolContext(5, 6, "call-1"),
                {"image_url": "https://example.test/cat.png"},
            )
        ).content
    )
    result = await registry.call(
        "send_image",
        ToolContext(5, 6, "call-2"),
        {"image_id": downloaded["image_id"], "caption": "Вот кот"},
    )

    assert json.loads(result.content) == {"status": "delivered"}
    assert len(telegram._bot.photos) == 1
    sent = telegram._bot.photos[0]
    assert sent["chat_id"] == 5
    assert sent["caption"] == "Вот кот"
    assert sent["photo"].data == payload
    assert sent["photo"].filename.endswith(".png")


@pytest.mark.asyncio
async def test_send_image_accepts_missing_image_id():
    telegram = FakeTelegramService()
    registry = _registry(
        _store(lambda request: _image_response(_png_bytes())),
        telegram,
    )

    with pytest.raises(ToolArgumentsError):
        await registry.call("send_image", ToolContext(1, 2, "call-1"), {})
    assert telegram._bot.photos == []


@pytest.mark.asyncio
async def test_send_image_rejects_unknown_image_id():
    telegram = FakeTelegramService()
    registry = _registry(
        _store(lambda request: _image_response(_png_bytes())),
        telegram,
    )

    with pytest.raises(ImageNotFoundError):
        await registry.call(
            "send_image",
            ToolContext(1, 2, "call-1"),
            {"image_id": "does-not-exist"},
        )
    assert telegram._bot.photos == []


@pytest.mark.asyncio
async def test_send_image_rejects_expired_image_id():
    telegram = FakeTelegramService()
    store = _store(lambda request: _image_response(_png_bytes()))
    store._images["expired"] = StoredImage(
        image_id="expired",
        chat_id=1,
        data=b"png",
        mime_type="image/png",
        filename="image.png",
        width=1,
        height=1,
        source_url="https://example.test/old.png",
        expires_at=time.monotonic() - 1,
    )
    registry = _registry(store, telegram)

    with pytest.raises(ImageNotFoundError):
        await registry.call(
            "send_image",
            ToolContext(1, 2, "call-1"),
            {"image_id": "expired"},
        )
    assert telegram._bot.photos == []


@pytest.mark.asyncio
async def test_send_image_rejects_image_from_another_chat():
    telegram = FakeTelegramService()
    store = _store(lambda request: _image_response(_png_bytes()))
    registry = _registry(store, telegram)

    downloaded = json.loads(
        (
            await registry.call(
                "download_image",
                ToolContext(1, 2, "call-1"),
                {"image_url": "https://example.test/cat.png"},
            )
        ).content
    )

    with pytest.raises(ImageNotFoundError):
        await registry.call(
            "send_image",
            ToolContext(99, 100, "call-2"),
            {"image_id": downloaded["image_id"]},
        )
    assert telegram._bot.photos == []


@pytest.mark.asyncio
async def test_send_image_rejects_oversized_caption():
    telegram = FakeTelegramService()
    store = _store(lambda request: _image_response(_png_bytes()))
    registry = _registry(store, telegram)

    downloaded = json.loads(
        (
            await registry.call(
                "download_image",
                ToolContext(1, 2, "call-1"),
                {"image_url": "https://example.test/cat.png"},
            )
        ).content
    )

    with pytest.raises(ToolArgumentsError, match="caption"):
        await registry.call(
            "send_image",
            ToolContext(1, 2, "call-2"),
            {"image_id": downloaded["image_id"], "caption": "x" * 1025},
        )
    assert telegram._bot.photos == []


def test_download_image_schema_is_loaded():
    parameters = load_schema("download_image")["function"]["parameters"]
    assert set(parameters["properties"]) == {"image_url"}
    assert parameters["required"] == ["image_url"]


def test_send_image_schema_is_loaded():
    parameters = load_schema("send_image")["function"]["parameters"]
    assert set(parameters["properties"]) == {"image_id", "caption"}
    assert parameters["required"] == ["image_id"]
