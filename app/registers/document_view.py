import json
from pathlib import Path

from app.core.logging import logger
from app.tools.loader import load_schema
from app.core.errors import ToolArgumentsError
from app.agent.document_view_service import DocumentViewService
from app.agent.tools import ToolRegistry, ToolContext, ToolResult


def register_document_views(registry: ToolRegistry, doc_view_service: DocumentViewService):

    async def document_view(context: ToolContext, args: dict) -> ToolResult:
        logger.info("document_view tool called: args=%s", args)

        url = args.get("url")
        file_name = args.get("file_name")
        if url is not None and (not isinstance(url, str) or not url.strip()):
            raise ToolArgumentsError("document_view", "url must be a non-empty string")
        if file_name is not None and (
            not isinstance(file_name, str) or not file_name.strip()
        ):
            raise ToolArgumentsError(
                "document_view",
                "file_name must be a non-empty string",
            )

        if url:
            view = doc_view_service.convert_to_markdown(url)
        else:
            supported = {".pdf", ".pptx"}
            attachments = [
                attachment
                for attachment in context.attachments
                if attachment.data
                and Path(attachment.file_name or "").suffix.lower() in supported
            ]
            if file_name:
                attachments = [
                    attachment
                    for attachment in attachments
                    if attachment.file_name == file_name
                ]
            if not attachments:
                raise ToolArgumentsError(
                    "document_view",
                    "provide a PDF/PPTX url or attach a PDF/PPTX file",
                )
            attachment = attachments[0]
            view = doc_view_service.convert_bytes_to_markdown(
                attachment.data,
                attachment.file_name or "document",
            )

        return ToolResult(
            context.call_id,
            json.dumps({"status": "ok", "markdown": view}, ensure_ascii=False),
        )

    registry.register(
        "document_view",
        document_view,
        load_schema("document_view"),
    )