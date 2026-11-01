import json

import pytest

from app.agent.models import TelegramAttachment, ToolContext
from app.agent.tools import ToolRegistry
from app.registers.document_view import register_document_views
from app.tools.loader import load_schema


class FakeDocumentViewService:
    def __init__(self):
        self.calls = []

    def convert_to_markdown(self, url):
        self.calls.append(("url", url))
        return "# From URL"

    def convert_bytes_to_markdown(self, data, file_name):
        self.calls.append(("attachment", data, file_name))
        return "# From attachment"


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

    assert json.loads(result.content) == {"status": "ok", "markdown": "# From attachment"}
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


def test_document_view_schema_is_loaded():
    parameters = load_schema("document_view")["function"]["parameters"]
    assert set(parameters["properties"]) == {"url", "file_name"}
    assert parameters.get("required", []) == []
