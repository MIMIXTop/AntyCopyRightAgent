import httpx
import pytest

from app.api.classroom.client import ClassroomClient


@pytest.mark.asyncio
async def test_empty_course_work_object_is_an_empty_list():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={}, request=request)
    )
    client = ClassroomClient(httpx.AsyncClient(transport=transport))

    assert await client.get_course_works(1, "course-1") == []
