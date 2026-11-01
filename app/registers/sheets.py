import json

from app.agent.models import ToolContext, ToolResult
from app.api.sheets.service import SheetsService
from app.core.errors import ToolArgumentsError
from app.tools.loader import load_schema


def register_sheets_tools(registry, sheets: SheetsService) -> None:
    async def get_values(context: ToolContext, args: dict) -> ToolResult:
        sheet_id = args.get("sheet_id")
        range_name = args.get("range")
        if not isinstance(sheet_id, str) or not sheet_id.strip():
            raise ToolArgumentsError("get_sheet_values", "sheet_id is required")
        if not isinstance(range_name, str) or not range_name.strip():
            raise ToolArgumentsError("get_sheet_values", "range is required")
        result = await sheets.get_values(context.user_id, sheet_id, range_name)
        return ToolResult(context.call_id, json.dumps(result, ensure_ascii=False))

    async def append_values(context: ToolContext, args: dict) -> ToolResult:
        return await _write_values(context, args, sheets.append_values, "append_sheet_values")

    async def update_values(context: ToolContext, args: dict) -> ToolResult:
        return await _write_values(context, args, sheets.update_values, "update_sheet_values")

    async def _write_values(context, args, operation, tool_name):
        sheet_id = args.get("sheet_id")
        range_name = args.get("range")
        values = args.get("values")
        if not isinstance(sheet_id, str) or not sheet_id.strip():
            raise ToolArgumentsError(tool_name, "sheet_id is required")
        if not isinstance(range_name, str) or not range_name.strip():
            raise ToolArgumentsError(tool_name, "range is required")
        if not isinstance(values, list) or not values or not all(isinstance(row, list) for row in values):
            raise ToolArgumentsError(tool_name, "values must be a non-empty array of arrays")
        result = await operation(context.user_id, sheet_id, range_name, values)
        return ToolResult(context.call_id, json.dumps(result, ensure_ascii=False))

    async def get_info(context: ToolContext, args: dict) -> ToolResult:
        sheet_id = args.get("sheet_id")
        if not isinstance(sheet_id, str) or not sheet_id.strip():
            raise ToolArgumentsError("get_sheet_info", "sheet_id is required")
        result = await sheets.get_info(context.user_id, sheet_id)
        return ToolResult(context.call_id, json.dumps(result, ensure_ascii=False))

    async def create_tab(context: ToolContext, args: dict) -> ToolResult:
        sheet_id = args.get("sheet_id")
        tab_name = args.get("tab_name")
        if not isinstance(sheet_id, str) or not sheet_id.strip():
            raise ToolArgumentsError("create_sheet_tab", "sheet_id is required")
        if not isinstance(tab_name, str) or not tab_name.strip():
            raise ToolArgumentsError("create_sheet_tab", "tab_name is required")
        result = await sheets.create_tab(context.user_id, sheet_id, tab_name)
        return ToolResult(context.call_id, json.dumps(result, ensure_ascii=False))

    async def update_tab(context: ToolContext, args: dict) -> ToolResult:
        sheet_id = args.get("sheet_id")
        tab_id = args.get("tab_id")
        tab_name = args.get("tab_name")
        if not isinstance(sheet_id, str) or not sheet_id.strip():
            raise ToolArgumentsError("update_sheet_tab", "sheet_id is required")
        if not isinstance(tab_id, str) or not tab_id.strip():
            raise ToolArgumentsError("update_sheet_tab", "tab_id is required")
        if not isinstance(tab_name, str) or not tab_name.strip():
            raise ToolArgumentsError("update_sheet_tab", "tab_name is required")
        result = await sheets.update_tab(context.user_id, sheet_id, tab_id, tab_name)
        return ToolResult(context.call_id, json.dumps(result, ensure_ascii=False))

    registry.register("get_sheet_values", get_values, load_schema("get_sheet_values"))
    registry.register("append_sheet_values", append_values, load_schema("append_sheet_values"))
    registry.register("update_sheet_values", update_values, load_schema("update_sheet_values"))
    registry.register("get_sheet_info", get_info, load_schema("get_sheet_info"))
    registry.register("create_sheet_tab", create_tab, load_schema("create_sheet_tab"))
    registry.register("update_sheet_tab", update_tab, load_schema("update_sheet_tab"))
