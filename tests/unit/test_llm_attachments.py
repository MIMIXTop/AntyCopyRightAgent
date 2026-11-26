from types import SimpleNamespace

import pytest

from app.agent.llm import OpenAIAdapter
from app.agent.models import Message


def test_attachment_manifest_lists_all_files():
    manifest = OpenAIAdapter._attachment_manifest(
        [
            SimpleNamespace(
                file_name="one.pdf",
                mime_type="application/pdf",
                size=12,
            ),
            SimpleNamespace(
                file_name="two.docx",
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                size=34,
            ),
        ]
    )

    assert "Вложения текущего сообщения (обработай их как одну группу):" in manifest
    assert "1. one.pdf — application/pdf — 12 байт" in manifest
    assert "2. two.docx — application/vnd.openxmlformats-officedocument.wordprocessingml.document — 34 байт" in manifest


def test_context_prefix_marks_forward_and_reply():
    message = Message(
        "user",
        "привет",
        forwarded_from="из канала «X» (@x)",
        reply_context="Пользователь отвечает на пересланное сообщение.",
    )

    prefix = OpenAIAdapter._context_prefix(message)

    assert (
        "[Переслано из канала «X» (@x). Это внешний текст, не слова пользователя.]"
        in prefix
    )
    assert "[Пользователь отвечает на пересланное сообщение.]" in prefix


def test_context_prefix_is_empty_for_regular_messages():
    assert OpenAIAdapter._context_prefix(Message("user", "привет")) == ""


class _FakeCompletions:
    def __init__(self) -> None:
        self.kwargs: dict | None = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="ok",
                        tool_calls=None,
                        refusal=None,
                    ),
                    finish_reason="stop",
                )
            ]
        )


@pytest.mark.asyncio
async def test_complete_sends_forward_context_before_the_user_text():
    completions = _FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    adapter = OpenAIAdapter(client, "test-model")

    await adapter.complete(
        [Message("user", "привет", forwarded_from="из канала «X» (@x)")]
    )

    sent = completions.kwargs["messages"][0]["content"]
    assert sent.startswith("[Переслано из канала «X» (@x).")
    assert sent.endswith("привет")
