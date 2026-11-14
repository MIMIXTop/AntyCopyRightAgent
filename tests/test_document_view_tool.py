import json

import pytest

from app.agent.document_view_service import DocumentContent
from app.agent.models import TelegramAttachment, ToolContext
from app.agent.tools import ToolRegistry
from app.core.errors import DocumentConversionError
from app.registers.document_view import register_document_views
from app.tools.loader import load_schema


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
