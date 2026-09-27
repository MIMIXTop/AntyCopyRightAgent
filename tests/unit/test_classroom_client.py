import pytest
import httpx

from app.classroom.client import ClassroomClient
from app.core.errors import UnauthorizedError, ExternalServiceUnavailableError


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


