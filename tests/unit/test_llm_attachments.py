from types import SimpleNamespace

from app.agent.llm import OpenAIAdapter


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
