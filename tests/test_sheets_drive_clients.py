import json

import httpx
import pytest

from app.api.drive.client import DriveClient
from app.api.sheets.client import SheetsClient


@pytest.mark.asyncio
async def test_sheets_client_builds_read_write_and_tab_requests():
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET" and request.url.path.endswith("/values/Sheet1!A1:B2"):
            return httpx.Response(200, json={"values": [["name", "score"]]}, request=request)
        return httpx.Response(200, json={"ok": True}, request=request)

    client = SheetsClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        assert await client.get_sheet_value(42, "sheet-1", "Sheet1!A1:B2") == {
            "values": [["name", "score"]]
        }
        await client.post_sheet_value(42, "sheet-1", "Sheet1!A:C", [["a", 1]])
        await client.put_sheet_value(42, "sheet-1", "Sheet1!A1", [["b"]])
        await client.get_sheet_info(42, "sheet-1")
        await client.create_sheet_tab(42, "sheet-1", "Results")
        await client.update_sheet_tab(42, "sheet-1", "123", "Renamed")
    finally:
        await client._http.aclose()

    assert [request.method for request in requests] == ["GET", "POST", "PUT", "GET", "POST", "POST"]
    assert json.loads(requests[1].content) == {"values": [["a", 1]]}
    assert json.loads(requests[4].content)["requests"][0]["addSheet"]["properties"]["title"] == "Results"
    assert json.loads(requests[5].content)["requests"][0]["updateSheetProperties"]["properties"] == {
        "sheetId": 123,
        "title": "Renamed",
    }


@pytest.mark.asyncio
async def test_sheets_client_keeps_special_tab_name_unquoted():
    request_urls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        request_urls.append(str(request.url))
        return httpx.Response(200, json={"ok": True}, request=request)

    client = SheetsClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        await client.post_sheet_value(42, "sheet-1", "23-ИТ-2!A1", [["value"]])
    finally:
        await client._http.aclose()

    assert "23-%D0%98%D0%A2-2!A1:append" in request_urls[0]
    assert "%27" not in request_urls[0]
    assert "%3Aappend" not in request_urls[0]


@pytest.mark.asyncio
async def test_drive_client_uploads_multipart_and_creates_spreadsheet():
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "drive-file-1"}, request=request)

    client = DriveClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        spreadsheet = await client.create_spreadsheet_in_folder(42, "folder-1", "Grades")
        uploaded = await client.upload_to_drive(
            42, "notes.txt", b"hello", "text/plain", "folder-1"
        )
    finally:
        await client._http.aclose()

    assert spreadsheet["id"] == "drive-file-1"
    assert uploaded["id"] == "drive-file-1"
    assert requests[0].url.path.endswith("/api/drive/files")
    assert json.loads(requests[0].content)["parents"] == ["folder-1"]
    assert b'"name": "notes.txt"' in requests[1].content
    assert b"hello" in requests[1].content
