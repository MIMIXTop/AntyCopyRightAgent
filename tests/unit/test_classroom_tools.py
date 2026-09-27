import json

import httpx
import pytest
from anyio import run

from app.agent.models import ToolContext
from app.agent.tools import ToolRegistry
from app.classroom.models import ResultRequest
from app.classroom.service import ClassroomService
from app.core.errors import ToolArgumentsError
from app.registers.classroom import register_classroom_tools


class FakeClassroomService(ClassroomService):
    def __init__(self):
        super().__init__(
            client=None
        )
        self.received = None


    async def create_course(
            self,
            telegram_id,
            course_name,
            course_description="",
            course_section=None,
    ):
        self.received = {
            "telegram_id": telegram_id,
            "course_name": course_name,
            "course_description": course_description,
            "section": course_section,
        }

        return ResultRequest(
            status=201,
            body={"id": "new-course", "name": course_name}
        )


@pytest.mark.asyncio
async def test_create_course_maps_name_and_return_json():
    service = FakeClassroomService()
    registry = ToolRegistry()
    register_classroom_tools(registry, service)

    result = await registry.call(
        "create_course",
        ToolContext(chat_id=1, user_id=42, call_id="call-1"),
        {
            "name": "test",
            "description": "Description",
        }
    )

    assert service.received == {
        "telegram_id": 42,
        "course_name": "test",
        "course_description": "Description",
        "section": None,
    }
    payload = json.loads(result.content)
    assert payload["status"] == 201

@pytest.mark.asyncio
async def test_create_course_empty_name():
    async def scenario():
        service = FakeClassroomService()
        registry = ToolRegistry()
        register_classroom_tools(registry, service)

        with pytest.raises(ToolArgumentsError) as exc_inf:
            await registry.call(
                "create_course",
                ToolContext(chat_id=1, user_id=42, call_id="call-1"),
                {
                    "description": "Description",
                }
            )

            assert "name is required" in str(exc_inf.value)

            assert service.received is None

