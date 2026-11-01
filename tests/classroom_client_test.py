import httpx
from anyio import run

from app.api.classroom.client import ClassroomClient


def test_get_courses_reads_courses_envelope():
    run(_test_get_courses_reads_courses_envelope)


async def _test_get_courses_reads_courses_envelope():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "courses": [
                    {
                        "id": "858000257751",
                        "name": "First Test",
                        "ownerId": "teacher-1",
                    }
                ]
            },
            request=request,
        )

    client = ClassroomClient(
        httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://test",
        )
    )
    try:
        courses = await client.get_course(5322868393)
    finally:
        await client.http.aclose()

    assert len(courses) == 1
    assert courses[0].id == "858000257751"
    assert courses[0].name == "First Test"


def test_course_work_aliases_google_classroom_fields():
    from app.api.classroom.models import CourseWork

    assignment = CourseWork.model_validate(
        {
            "courseId": "858000257751",
            "id": "858001133322",
            "title": "Анализ работ",
            "description": "Сдайте работу",
        }
    )

    assert assignment.course_id == "858000257751"
    assert assignment.name == "Анализ работ"
