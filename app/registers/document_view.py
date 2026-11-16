import json
from pathlib import Path

from app.api.drive.client import DriveClient, parse_drive_url
from app.core.errors import ToolArgumentsError
from app.core.logging import logger
from app.tools.loader import load_schema
from app.agent.document_view_service import DocumentViewService
from app.agent.tools import ToolRegistry, ToolContext, ToolResult


SUPPORTED_SUFFIXES = {".pdf", ".pptx"}


def _document_name(file_name, data: bytes, fallback: str) -> str:
    """Pick a name the converter can use to infer the format."""
    if isinstance(file_name, str) and Path(file_name).suffix.lower() in SUPPORTED_SUFFIXES:
        return file_name
    # Google Docs editors are exported to a known format, so the fallback name
    # is authoritative even though the bytes are a zip container.
    if Path(fallback).suffix.lower() in SUPPORTED_SUFFIXES:
        return fallback
    head = data[:8]
    if head.startswith(b"%PDF-"):
        return "document.pdf"
    if head.startswith(b"PK\x03\x04"):
        # Office Open XML (PPTX/DOCX/XLSX) is a zip container.
        return "document.pptx"
    return fallback


def register_document_views(
        registry: ToolRegistry,
        doc_view_service: DocumentViewService,
        drive: DriveClient | None = None,
        max_output_chars: int = 4000,
):

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
            drive_ref = parse_drive_url(url)
            if drive_ref is not None and drive is not None:
                logger.info(
                    "document_view downloading Google Drive file: id=%s export=%s",
                    drive_ref.file_id,
                    drive_ref.export_mime_type,
                )
                data = await drive.download_file(
                    context.user_id,
                    drive_ref.file_id,
                    export_mime_type=drive_ref.export_mime_type,
                )
                view = await doc_view_service.convert_bytes_to_markdown(
                    data,
                    _document_name(file_name, data, drive_ref.file_name),
                )
            else:
                view = await doc_view_service.convert_to_markdown(url)
        else:
            supported = SUPPORTED_SUFFIXES
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
            view = await doc_view_service.convert_bytes_to_markdown(
                attachment.data,
                attachment.file_name or "document",
            )

        markdown = view.markdown
        total_chars = len(markdown)
        output_truncated = max_output_chars > 0 and total_chars > max_output_chars
        if output_truncated:
            markdown = (
                markdown[:max_output_chars]
                + "\n\n[document preview truncated for the assistant: "
                + f"showing the first {max_output_chars} of {total_chars} characters]"
            )

        return ToolResult(
            context.call_id,
            json.dumps(
                {
                    "status": "ok",
                    "engine": view.engine,
                    "pages": view.pages,
                    "truncated": view.truncated,
                    "total_chars": total_chars,
                    "output_truncated": output_truncated,
                    "markdown": markdown,
                },
                ensure_ascii=False,
            ),
        )

    registry.register(
        "document_view",
        document_view,
        load_schema("document_view"),
    )