import json

import httpx
import pytest

from app.api.forms.client import FormsClient
from app.core.errors import ForbiddenError, UpstreamServiceError


@pytest.mark.asyncio
async def test_forms_client_builds_requests_and_parses_models():
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if request.method == "POST" and path.endswith("/api/forms/v1/forms"):
            return httpx.Response(
                200,
                json={
                    "formId": "form-1",
                    "info": {"title": "Тест", "documentTitle": "Тест"},
                    "responderUri": "https://docs.google.com/forms/d/form-1/viewform",
                },
                request=request,
            )
        if path.endswith(":batchUpdate"):
            return httpx.Response(200, json={}, request=request)
        if path.endswith(":publish"):
            return httpx.Response(200, json={}, request=request)
        if path.endswith("/responses"):
            return httpx.Response(
                200,
                json={"responses": [], "totalResponses": 0},
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "formId": "form-1",
                "info": {"title": "Тест"},
                "settings": {"quizSettings": {"isQuiz": True}},
            },
            request=request,
        )

    client = FormsClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        form = await client.create_form(
            telegram_id=42,
            title="Тест",
            description="Вариант 1",
            document_title="Тест",
        )
        assert form.form_id == "form-1"
        assert form.responder_uri == "https://docs.google.com/forms/d/form-1/viewform"

        await client.batch_update(42, "form-1", [{"createItem": {"location": {"index": 0}}}])
        publish_result = await client.publish(42, "form-1")
        assert publish_result == {}
        responses = await client.get_responses(42, "form-1")
        assert responses.responses == []
        assert responses.total_responses == 0

        fetched = await client.get_form(42, "form-1")
        assert fetched.is_quiz is True
    finally:
        await client._http.aclose()

    create_request = requests[0]
    assert create_request.method == "POST"
    assert create_request.url.path == "/api/forms/v1/forms"
    assert create_request.url.params["telegram_id"] == "42"
    assert json.loads(create_request.content) == {
        "info": {"title": "Тест", "description": "Вариант 1", "documentTitle": "Тест"}
    }

    batch_request = requests[1]
    assert batch_request.url.path == "/api/forms/v1/forms/form-1:batchUpdate"
    assert json.loads(batch_request.content) == {
        "requests": [{"createItem": {"location": {"index": 0}}}]
    }

    publish_request = requests[2]
    assert publish_request.url.path == "/api/forms/v1/forms/form-1:publish"
    assert json.loads(publish_request.content) == {"updateMask": "publishState"}

    assert requests[3].url.path == "/api/forms/v1/forms/form-1/responses"
    assert requests[4].url.path == "/api/forms/v1/forms/form-1"


@pytest.mark.asyncio
async def test_forms_client_maps_forbidden_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"error": {"message": "quota exceeded"}},
            request=request,
        )

    client = FormsClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        with pytest.raises(ForbiddenError) as exc_info:
            await client.create_form(42, "Тест")
    finally:
        await client._http.aclose()

    assert "quota exceeded" in str(exc_info.value)


@pytest.mark.asyncio
async def test_forms_client_maps_upstream_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"}, request=request)

    client = FormsClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        with pytest.raises(UpstreamServiceError) as exc_info:
            await client.get_form(42, "form-1")
    finally:
        await client._http.aclose()

    assert exc_info.value.status_code == 500
