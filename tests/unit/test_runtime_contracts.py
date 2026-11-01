import json

import pytest

from app.agent.models import TelegramAttachment, ToolContext, ToolResult
from app.agent.tools import ToolRegistry
from app.core.errors import ToolNotFoundError
from app.tools.loader import load_schema


def test_announcement_schema_exposes_only_public_material_arguments():
    schema = load_schema("create_announcement")["function"]["parameters"]
    assert set(schema["properties"]) == {
        "course_id",
        "text",
        "links",
        "drive_file_ids",
        "state",
    }
    assert "telegram_file_ids" not in schema["properties"]
    assert schema["additionalProperties"] is False


@pytest.mark.asyncio
async def test_tool_registry_registers_schemas_and_rejects_unknown_tools():
    registry = ToolRegistry()

    async def handler(context, arguments):
        return ToolResult(context.call_id, json.dumps(arguments))

    registry.register("echo", handler, {"name": "echo"})
    assert registry.schemas() == [{"name": "echo"}]
    result = await registry.call("echo", ToolContext(1, 2, "call"), {"x": 1})
    assert json.loads(result.content) == {"x": 1}

    with pytest.raises(ToolNotFoundError):
        await registry.call("missing", ToolContext(1, 2, "call"), {})


def test_telegram_attachment_keeps_metadata_without_binary_payload():
    attachment = TelegramAttachment(
        file_id="file-1",
        file_name="report.pdf",
        mime_type="application/pdf",
        size=100,
    )
    assert attachment.file_id == "file-1"
    assert attachment.data is None
    assert attachment.base64_data is None

