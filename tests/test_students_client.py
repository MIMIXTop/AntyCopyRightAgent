import httpx
import pytest

from app.api.classroom.client import ClassroomClient
from app.api.classroom.models import Student


@pytest.mark.asyncio
async def test_get_students_accepts_user_id_payload():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "students": [{
                    "courseId": "course-1",
                    "userId": "user-1",
                    "profile": {
                        "id": "user-1",
                        "name": {"fullName": "Student"},
                    },
                }],
            },
            request=request,
        )
    )
    client = ClassroomClient(httpx.AsyncClient(transport=transport))

    students = await client.get_student_in_course(1, "course-1")

    assert len(students) == 1
    assert isinstance(students[0], Student)
    assert students[0].id == "user-1"
