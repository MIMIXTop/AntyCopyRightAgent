import json

import pytest

from app.agent.document_view_service import DocumentContent
from app.agent.models import TelegramAttachment, ToolContext
from app.agent.tools import ToolRegistry
from app.core.errors import DocumentConversionError
from app.registers.document_view import register_document_views
from app.tools.loader import load_schema


class FakeDriveClient:
    def __init__(self, data=b"%PDF-1.7"):
        self.data = data
        self.calls = []

    async def download_file(self, telegram_id, file_id, *, export_mime_type=None):
        self.calls.append((telegram_id, file_id, export_mime_type))
        return self.data


class FakeDocumentViewService:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    async def convert_to_markdown(self, url):
        self.calls.append(("url", url))
        if self.error is not None:
            raise self.error
        return DocumentContent(markdown="# From URL", pages=2, engine="docling")

    async def convert_bytes_to_markdown(self, data, file_name):
        self.calls.append(("attachment", data, file_name))
        if self.error is not None:
            raise self.error
        return DocumentContent(markdown="# From attachment", pages=1, engine="pypdfium2")


@pytest.mark.asyncio
async def test_document_view_reads_attached_pdf():
    service = FakeDocumentViewService()
    registry = ToolRegistry()
    register_document_views(registry, service)

    result = await registry.call(
        "document_view",
        ToolContext(
            chat_id=1,
            user_id=2,
            call_id="call-1",
            attachments=[
                TelegramAttachment(
                    file_id="file-1",
                    file_name="report.pdf",
                    mime_type="application/pdf",
                    data=b"pdf",
                )
            ],
        ),
        {},
    )

    assert json.loads(result.content) == {
        "status": "ok",
        "engine": "pypdfium2",
        "pages": 1,
        "truncated": False,
        "total_chars": len("# From attachment"),
        "output_truncated": False,
        "markdown": "# From attachment",
    }
    assert service.calls == [("attachment", b"pdf", "report.pdf")]


@pytest.mark.asyncio
async def test_document_view_uses_explicit_url():
    service = FakeDocumentViewService()
    registry = ToolRegistry()
    register_document_views(registry, service)

    result = await registry.call(
        "document_view",
        ToolContext(1, 2, "call-1"),
        {"url": "https://example.test/file.pptx"},
    )

    assert json.loads(result.content)["markdown"] == "# From URL"
    assert service.calls == [("url", "https://example.test/file.pptx")]


@pytest.mark.asyncio
async def test_document_view_downloads_drive_link_through_account():
    service = FakeDocumentViewService()
    drive = FakeDriveClient(b"%PDF-1.7")
    registry = ToolRegistry()
    register_document_views(registry, service, drive=drive)

    result = await registry.call(
        "document_view",
        ToolContext(1, 2, "call-1"),
        {
            "url": (
                "https://drive.usercontent.google.com/download"
                "?id=file-9&export=download"
            ),
            "file_name": "Лекция 1.pptx",
        },
    )

    assert json.loads(result.content)["markdown"] == "# From attachment"
    assert drive.calls == [(2, "file-9", None)]
    assert service.calls == [("attachment", b"%PDF-1.7", "Лекция 1.pptx")]


@pytest.mark.asyncio
async def test_document_view_exports_google_slides_to_pptx():
    service = FakeDocumentViewService()
    drive = FakeDriveClient(b"PK\x03\x04presentation")
    registry = ToolRegistry()
    register_document_views(registry, service, drive=drive)

    await registry.call(
        "document_view",
        ToolContext(1, 2, "call-1"),
        {"url": "https://docs.google.com/presentation/d/pres-1/edit"},
    )

    assert drive.calls == [
        (
            2,
            "pres-1",
            "application/vnd.openxmlformats-officedocument."
            "presentationml.presentation",
        )
    ]
    assert service.calls == [
        ("attachment", b"PK\x03\x04presentation", "presentation.pptx")
    ]


@pytest.mark.asyncio
async def test_document_view_propagates_conversion_error():
    service = FakeDocumentViewService(
        error=DocumentConversionError("The PDF is a scan and OCR is disabled.")
    )
    registry = ToolRegistry()
    register_document_views(registry, service)

    with pytest.raises(DocumentConversionError, match="OCR is disabled"):
        await registry.call(
            "document_view",
            ToolContext(
                chat_id=1,
                user_id=2,
                call_id="call-1",
                attachments=[
                    TelegramAttachment(
                        file_id="file-1",
                        file_name="scan.pdf",
                        data=b"pdf",
                    )
                ],
            ),
            {},
        )


def test_document_view_schema_is_loaded():
    parameters = load_schema("document_view")["function"]["parameters"]
    assert set(parameters["properties"]) == {"url", "file_name"}
    assert parameters.get("required", []) == []


@pytest.mark.asyncio
async def test_document_view_returns_a_bounded_preview():
    class LongDocumentService(FakeDocumentViewService):
        async def convert_to_markdown(self, url):
            return DocumentContent(
                markdown="x" * 10_000,
                pages=20,
                engine="pypdfium2",
            )

    registry = ToolRegistry()
    register_document_views(
        registry,
        LongDocumentService(),
        max_output_chars=500,
    )

    result = await registry.call(
        "document_view",
        ToolContext(1, 2, "call-1"),
        {"url": "https://example.test/long.pdf"},
    )

    payload = json.loads(result.content)
    assert payload["total_chars"] == 10_000
    assert payload["output_truncated"] is True
    assert payload["markdown"].startswith("x" * 500)
    assert "preview truncated" in payload["markdown"]
    assert len(payload["markdown"]) < 700
