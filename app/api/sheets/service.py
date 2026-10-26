from app.api.sheets.client import SheetsClient
from app.core.errors import ValidationError


class SheetsService:
    def __init__(self, client: SheetsClient):
        self._client = client

    @staticmethod
    def _validate_id(value: str, name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"{name} is required")

    async def get_values(self, telegram_id: int, sheet_id: str, range_name: str):
        self._validate_id(sheet_id, "Sheet ID")
        self._validate_id(range_name, "Range")
        return await self._client.get_sheet_value(telegram_id, sheet_id, range_name)

    async def append_values(self, telegram_id: int, sheet_id: str, range_name: str, values: list[list]):
        self._validate_id(sheet_id, "Sheet ID")
        self._validate_id(range_name, "Range")
        if not isinstance(values, list) or not values:
            raise ValidationError("Values must be a non-empty list")
        return await self._client.post_sheet_value(telegram_id, sheet_id, range_name, values)

    async def update_values(self, telegram_id: int, sheet_id: str, range_name: str, values: list[list]):
        self._validate_id(sheet_id, "Sheet ID")
        self._validate_id(range_name, "Range")
        if not isinstance(values, list) or not values:
            raise ValidationError("Values must be a non-empty list")
        return await self._client.put_sheet_value(telegram_id, sheet_id, range_name, values)

    async def get_info(self, telegram_id: int, sheet_id: str):
        self._validate_id(sheet_id, "Sheet ID")
        return await self._client.get_sheet_info(telegram_id, sheet_id)

    async def create_tab(self, telegram_id: int, sheet_id: str, tab_name: str):
        self._validate_id(sheet_id, "Sheet ID")
        self._validate_id(tab_name, "Tab name")
        return await self._client.create_sheet_tab(telegram_id, sheet_id, tab_name)