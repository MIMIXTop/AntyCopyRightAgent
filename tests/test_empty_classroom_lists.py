import httpx
import pytest

from app.api.classroom.client import ClassroomClient


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("get_course", (1,)),
        ("get_student_in_course", (1, "course-1")),
        ("get_course_works", (1, "course-1")),
        ("get_submissions", (1, "course-1", "work-1")),
        ("get_course_materials", (1, "course-1")),
        ("get_announcements", (1, "course-1")),
    ],
)
async def test_empty_classroom_list_response_is_empty(method, args):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={}, request=request)
    )
    client = ClassroomClient(httpx.AsyncClient(transport=transport))

    assert await getattr(client, method)(*args) == []
