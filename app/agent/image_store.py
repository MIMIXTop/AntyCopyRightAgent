import io
import time
import uuid
from dataclasses import dataclass

import httpx
from PIL import Image

from app.core.errors import ApplicationError
from app.core.logging import logger


class ImageDownloadError(ApplicationError):
    """The remote image could not be downloaded or is not a valid image."""


class ImageNotFoundError(ApplicationError):
    """The requested image handle is missing, expired, or belongs to another chat."""


@dataclass
class StoredImage:
    image_id: str
    chat_id: int
    data: bytes
    mime_type: str
    filename: str
    width: int | None
    height: int | None
    source_url: str
    expires_at: float


class ImageStore:
    """Downloads images from the internet and keeps them for a short time.

    The raw bytes never enter the model context: ``download`` returns only an
    ``image_id`` plus metadata, and ``send_image`` uses the stored bytes later.
    """

    MAX_BYTES = 10 * 1024 * 1024
    TTL_SECONDS = 10 * 60
    MAX_ENTRIES = 64
    TIMEOUT_SECONDS = 20.0
    ALLOWED_SCHEMES = {"http", "https"}

    _EXTENSIONS = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
    }

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client
        self._owns_client = client is None
        self._images: dict[str, StoredImage] = {}

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.TIMEOUT_SECONDS,
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def download(self, url: str, chat_id: int) -> dict:
        """Download ``url`` and store the bytes, returning metadata for the model."""
        if not isinstance(url, str) or not url.strip():
            raise ImageDownloadError("image_url must be a non-empty string")
        url = url.strip()
        try:
            scheme = httpx.URL(url).scheme.lower()
        except Exception as error:
            raise ImageDownloadError(f"invalid image URL: {url!r}") from error
        if scheme not in self.ALLOWED_SCHEMES:
            raise ImageDownloadError("only http:// and https:// image URLs are supported")

        client = await self._get_client()
        try:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                content_type = (
                    (response.headers.get("content-type") or "")
                    .split(";")[0]
                    .strip()
                    .lower()
                )
                data = await self._read_limited(response)
        except httpx.HTTPError as error:
            logger.warning("Image download failed: url=%s error=%s", url, error)
            raise ImageDownloadError(f"image download failed: {url}") from error

        mime_type = self._sniff_mime(data)
        if mime_type is None:
            if not content_type.startswith("image/"):
                raise ImageDownloadError(
                    f"URL does not point to an image (content-type: {content_type or 'unknown'})"
                )
            mime_type = content_type

        try:
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
                if image.format:
                    mime_type = Image.MIME.get(image.format, mime_type)
        except Exception as error:
            raise ImageDownloadError("downloaded file is not a valid image") from error

        image_id = uuid.uuid4().hex
        self._store(
            StoredImage(
                image_id=image_id,
                chat_id=chat_id,
                data=data,
                mime_type=mime_type,
                filename=f"image{self._EXTENSIONS.get(mime_type, '.img')}",
                width=width,
                height=height,
                source_url=url,
                expires_at=time.monotonic() + self.TTL_SECONDS,
            )
        )
        logger.info(
            "Image stored: image_id=%s chat_id=%s mime=%s size=%s width=%s height=%s",
            image_id,
            chat_id,
            mime_type,
            len(data),
            width,
            height,
        )
        return {
            "status": "success",
            "image_id": image_id,
            "mime_type": mime_type,
            "width": width,
            "height": height,
            "size_bytes": len(data),
            "source_url": url,
            "expires_in_seconds": self.TTL_SECONDS,
        }

    def get(self, image_id: str, chat_id: int) -> StoredImage:
        """Return a stored image for this chat or raise ``ImageNotFoundError``."""
        if not isinstance(image_id, str) or not image_id.strip():
            raise ImageNotFoundError("image_id is required")
        key = image_id.strip()
        image = self._images.get(key)
        if image is not None and image.expires_at <= time.monotonic():
            self._images.pop(key, None)
            image = None
        if image is None or image.chat_id != chat_id:
            raise ImageNotFoundError("image not found or expired; download it again")
        return image

    async def _read_limited(self, response: httpx.Response) -> bytes:
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > self.MAX_BYTES:
                raise ImageDownloadError(
                    f"image exceeds the size limit of {self.MAX_BYTES} bytes"
                )
            chunks.append(chunk)
        return b"".join(chunks)

    @classmethod
    def _sniff_mime(cls, data: bytes) -> str | None:
        if data.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if data.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp"
        if data.startswith(b"BM"):
            return "image/bmp"
        return None

    def _store(self, image: StoredImage) -> None:
        self._images = {
            key: value
            for key, value in self._images.items()
            if value.expires_at > time.monotonic()
        }
        if len(self._images) >= self.MAX_ENTRIES:
            oldest = min(self._images, key=lambda key: self._images[key].expires_at)
            self._images.pop(oldest, None)
        self._images[image.image_id] = image
