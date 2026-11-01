import httpx
import pytest

from app.api.classroom.client import ClassroomClient


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"topic": []}, {"topics": []}])
async def test_get_topics_accepts_empty_classroom_topic_responses(payload):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    client = ClassroomClient(
        httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    try:
        topics = await client.get_topics_in_course(42, "course-1")
    finally:
        await client.http.aclose()

    assert topics == []
