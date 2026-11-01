import json

from app.agent.models import ToolContext, ToolResult
from app.api.drive.client import DriveClient
from app.core.errors import ToolArgumentsError
from app.tools.loader import load_schema


def register_drive_tools(registry, drive: DriveClient) -> None:
    async def create_spreadsheet(context: ToolContext, args: dict) -> ToolResult:
        folder_id = args.get("folder_id")
        file_name = args.get("file_name")
        if not isinstance(folder_id, str) or not folder_id.strip():
            raise ToolArgumentsError("create_spreadsheet", "folder_id is required")
        if not isinstance(file_name, str) or not file_name.strip():
            raise ToolArgumentsError("create_spreadsheet", "file_name is required")
        result = await drive.create_spreadsheet_in_folder(
            telegram_id=context.user_id,
            folder_id=folder_id,
            file_name=file_name,
        )
        return ToolResult(context.call_id, json.dumps(result, ensure_ascii=False))

    registry.register(
        "create_spreadsheet",
        create_spreadsheet,
        load_schema("create_spreadsheet"),
    )
