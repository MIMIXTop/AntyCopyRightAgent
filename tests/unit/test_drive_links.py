import httpx
import pytest

from app.api.drive.client import DriveClient, parse_drive_url


@pytest.mark.parametrize(
    "url, file_id, export_mime_type, file_name",
    [
        (
            "https://drive.google.com/file/d/1AbC_d-1/view?usp=drive_web",
            "1AbC_d-1",
            None,
            "drive-file",
        ),
        (
            "https://drive.google.com/open?id=1AbC_d-1",
            "1AbC_d-1",
            None,
            "drive-file",
        ),
        (
            "https://drive.usercontent.google.com/download?id=1AbC_d-1&export=download",
            "1AbC_d-1",
            None,
            "drive-file",
        ),
        (
            "https://docs.google.com/presentation/d/1AbC_d-1/edit#slide=id.p",
            "1AbC_d-1",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "presentation.pptx",
        ),
        (
            "https://docs.google.com/document/d/1AbC_d-1/edit",
            "1AbC_d-1",
            "application/pdf",
            "document.pdf",
        ),
    ],
)
def test_parse_drive_url(url, file_id, export_mime_type, file_name):
    ref = parse_drive_url(url)

    assert ref is not None
    assert ref.file_id == file_id
    assert ref.export_mime_type == export_mime_type
    assert ref.file_name == file_name


@pytest.mark.parametrize(
    "url",
    [
        "https://example.test/file.pdf",
        "https://drive.google.com/drive/folders/abc",
        "https://drive.google.com/drive/my-drive",
        "",
        None,
    ],
)
def test_parse_drive_url_ignores_other_links(url):
    assert parse_drive_url(url) is None


@pytest.mark.asyncio
async def test_download_file_uses_media_endpoint():
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=b"%PDF-1.7", request=request)

    client = DriveClient(
        httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    try:
        data = await client.download_file(42, "file-1")
    finally:
        await client._http.aclose()

    assert data == b"%PDF-1.7"
    assert requests[0].url.path == "/api/drive/files/file-1"
    assert requests[0].url.params["alt"] == "media"
    assert requests[0].url.params["telegram_id"] == "42"


@pytest.mark.asyncio
async def test_download_file_exports_google_docs_editors():
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=b"PK\x03\x04", request=request)

    client = DriveClient(
        httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    try:
        data = await client.download_file(
            42,
            "presentation-1",
            export_mime_type=(
                "application/vnd.openxmlformats-officedocument."
                "presentationml.presentation"
            ),
        )
    finally:
        await client._http.aclose()

    assert data == b"PK\x03\x04"
    assert requests[0].url.path == "/api/drive/files/presentation-1/export"
    assert (
        requests[0].url.params["mimeType"]
        == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )
