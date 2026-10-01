import json

import pytest
import httpx

from app.classroom.client import ClassroomClient
from app.core.errors import (
    ExternalServiceUnavailableError,
    InvalidUpstreamResponseError,
    UnauthorizedError,
)


@pytest.mark.asyncio
async def test_client_raises_unauthorized_on_401():
    def mock_401_handler(request: httpx.Request):
        return httpx.Response(status_code=401)

    mock_http = httpx.AsyncClient(transport=httpx.MockTransport(mock_401_handler))
    client = ClassroomClient(mock_http)

    with pytest.raises(UnauthorizedError):
        await client.get_course(telegram_id=42)


@pytest.mark.asyncio
async def test_client_handles_timeout():
    def mock_timeout_handler(request: httpx.Request):
        raise httpx.TimeoutException("Timeout")

    mock_http = httpx.AsyncClient(transport=httpx.MockTransport(mock_timeout_handler))
    client = ClassroomClient(mock_http)

    with pytest.raises(ExternalServiceUnavailableError):
        await client.get_course(telegram_id=42)


@pytest.mark.asyncio
async def test_client_parses_successful_response():
    def mock_200_handler(request: httpx.Request):
        assert b"telegram_id=42" in request.url.query

        return httpx.Response(
            status_code=200,
            json={
                "courses": [
                    {"id": "1", "name": "Course 1", "courseState": "ACTIVE"}
                ]
            },
        )

    mock_http = httpx.AsyncClient(transport=httpx.MockTransport(mock_200_handler))
    client = ClassroomClient(mock_http)

    courses = await client.get_course(telegram_id=42)

    assert len(courses) == 1
    assert courses[0].id == "1"
    assert courses[0].name == "Course 1"


@pytest.mark.asyncio
async def test_client_creates_announcement_with_materials():
    requests = []

    def mock_handler(request: httpx.Request):
        requests.append(request)
        return httpx.Response(
            status_code=201,
            json={"id": "announcement-1", "text": "Read this"},
        )

    mock_http = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    client = ClassroomClient(mock_http)

    result = await client.create_announcement(
        telegram_id=42,
        course_id="course-1",
        text="Read this",
        state="PUBLISHED",
        materials=[
            {"link": {"url": "https://example.com"}},
            {"driveFile": {"driveFile": {"id": "drive-1"}, "shareMode": "VIEW"}},
        ],
    )

    assert result.status == 201
    assert requests[0].url.params["telegram_id"] == "42"
    assert json.loads(requests[0].content)["materials"][0]["link"]["url"] == "https://example.com"


@pytest.mark.asyncio
async def test_client_rejects_upload_response_without_file_id():
    def mock_handler(request: httpx.Request):
        return httpx.Response(status_code=200, json={"name": "missing-id"})

    mock_http = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    client = ClassroomClient(mock_http)

    with pytest.raises(InvalidUpstreamResponseError):
        await client.upload_to_drive(
            telegram_id=42,
            file_name="notes.txt",
            content=b"notes",
            mime_type="text/plain",
        )
