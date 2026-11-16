from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

import pypdfium2 as pdfium

from app.core.errors import DocumentConversionError
from app.core.logging import logger

if TYPE_CHECKING:
    from app.config.settings import Settings

# A PDF whose text layer averages fewer characters than this per page is
# treated as a scan (or as slides made of screenshots) and handed to docling.
FAST_PATH_MIN_CHARS_PER_PAGE = 40

EMPTY_PAGE_MARKER = "[no text layer on this page]"

# Docling needs a short sample of the extracted text; below this the document
# is considered unreadable rather than merely sparse.
MIN_EXTRACTED_CHARS = 20

# Markers that mean Google answered with an authentication page instead of the
# requested file (e.g. a Drive link that requires the connected account).
GOOGLE_SIGNIN_MARKERS = (
    "to continue to Google Drive",
    "Google Drive: Sign-in",
    "Sign in - Google Accounts",
)


@dataclass(frozen=True)
class DocumentContent:
    """Markdown extracted from a document plus a little provenance."""

    markdown: str
    pages: int | None = None
    engine: str = "docling"
    truncated: bool = False


class DocumentViewService:
    """Extracts text from PDF and PPTX attachments.

    Text PDFs are read with pypdfium2, which takes milliseconds and needs no
    machine-learning models. Only scans and PPTX files go through docling,
    which is slow and memory-hungry, so it is built lazily and behind a lock.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._converter = None
        self._lock = asyncio.Lock()

    async def convert_to_markdown(self, url: str) -> DocumentContent:
        async with self._lock:
            return await asyncio.to_thread(self._convert_url, url)

    async def convert_bytes_to_markdown(
        self, data: bytes, file_name: str
    ) -> DocumentContent:
        self._validate_size(len(data), file_name)
        self._reject_google_signin_page(data, file_name)

        if Path(file_name).suffix.lower() == ".pdf":
            # Text extraction is independent per document, so it does not need
            # the docling lock and can run while another scan is converting.
            content = await asyncio.to_thread(self._extract_pdf_text, data)
            if content is not None:
                return content

        async with self._lock:
            return await asyncio.to_thread(
                self._convert_bytes, data, file_name
            )

    # ------------------------------------------------------------------ fast path

    def _extract_pdf_text(self, data: bytes) -> DocumentContent | None:
        try:
            document = pdfium.PdfDocument(data)
        except Exception as error:
            # Not a PDF pypdfium2 understands; docling may still handle it.
            logger.warning("pypdfium2 could not open the PDF: %s", error)
            return None

        try:
            pages = len(document)
            self._validate_pages(pages)
            texts = []
            for index in range(pages):
                page = document[index]
                try:
                    textpage = page.get_textpage()
                    try:
                        text = textpage.get_text_range()
                    finally:
                        textpage.close()
                finally:
                    page.close()
                texts.append(text.replace("\r\n", "\n").replace("\r", "\n").strip())
        finally:
            document.close()

        if pages == 0:
            raise DocumentConversionError("The PDF contains no pages.")

        total_chars = sum(len(text) for text in texts)
        if total_chars / pages < FAST_PATH_MIN_CHARS_PER_PAGE:
            logger.info(
                "PDF looks like a scan: %s chars over %s pages, falling back to docling",
                total_chars,
                pages,
            )
            return None

        markdown = "\n\n".join(
            f"## Page {number}\n\n{text or EMPTY_PAGE_MARKER}"
            for number, text in enumerate(texts, start=1)
        )
        logger.info(
            "Extracted PDF with pypdfium2: pages=%s chars=%s",
            pages,
            total_chars,
        )
        return self._finalize(markdown, pages, "pypdfium2")

    # ------------------------------------------------------------------- docling

    def _convert_url(self, url: str) -> DocumentContent:
        from urllib.parse import urlparse

        ocr_applies = not urlparse(url).path.lower().endswith(".pptx")
        return self._run_converter(url, source_label=url, ocr_applies=ocr_applies)

    def _convert_bytes(self, data: bytes, file_name: str) -> DocumentContent:
        from docling.datamodel.base_models import DocumentStream

        stream = DocumentStream(name=file_name, stream=BytesIO(data))
        return self._run_converter(
            stream,
            source_label=file_name,
            ocr_applies=Path(file_name).suffix.lower() == ".pdf",
        )

    def _run_converter(
        self, source, *, source_label: str, ocr_applies: bool
    ) -> DocumentContent:
        try:
            result = self._get_converter().convert(source)
        except DocumentConversionError:
            raise
        except Exception as error:
            raise self._conversion_error(source_label, error) from error

        pages = len(result.pages)
        self._validate_pages(pages)
        markdown = result.document.export_to_markdown()
        if any(marker in markdown for marker in GOOGLE_SIGNIN_MARKERS):
            raise self._signin_error(source_label)
        if len(markdown.strip()) < MIN_EXTRACTED_CHARS:
            if not ocr_applies:
                raise DocumentConversionError(
                    f"No text could be extracted from {source_label}: "
                    "the presentation contains no text."
                )
            if not self.settings.DOCUMENT_OCR_ENABLED:
                raise DocumentConversionError(
                    f"No text could be extracted from {source_label}: it is "
                    "probably a scan or an image-only document, and OCR is "
                    "disabled. Enable DOCUMENT_OCR_ENABLED and retry."
                )
            raise DocumentConversionError(
                f"No text could be extracted from {source_label}, even with OCR."
            )
        return self._finalize(markdown, pages, "docling")

    def _get_converter(self):
        if self._converter is not None:
            return self._converter

        # Imported here so a text PDF never loads torch or docling at all.
        from docling.datamodel.base_models import InputFormat
        from docling.document_converter import DocumentConverter, PdfFormatOption

        self._converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=self._pipeline_options()
                ),
            }
        )
        return self._converter

    def _pipeline_options(self):
        from docling.datamodel.pipeline_options import (
            PdfPipelineOptions,
            RapidOcrOptions,
        )

        artifacts_path = self._artifacts_path()
        options = PdfPipelineOptions(
            do_ocr=self.settings.DOCUMENT_OCR_ENABLED,
            do_table_structure=self.settings.DOCUMENT_TABLE_STRUCTURE,
            artifacts_path=artifacts_path,
        )
        if self.settings.DOCUMENT_OCR_ENABLED:
            # An explicit backend keeps docling off the torch fallback, which
            # would try to download .pth weights into site-packages.
            options.ocr_options = RapidOcrOptions(
                backend="onnxruntime",
                lang=[self.settings.DOCUMENT_OCR_LANG],
                rapidocr_params={
                    "Global.model_root_dir": str(self._ocr_model_root(artifacts_path)),
                },
            )
        logger.info(
            "Building docling options: ocr=%s ocr_lang=%s table_structure=%s artifacts=%s",
            self.settings.DOCUMENT_OCR_ENABLED,
            self.settings.DOCUMENT_OCR_LANG,
            self.settings.DOCUMENT_TABLE_STRUCTURE,
            artifacts_path,
        )
        return options

    def _artifacts_path(self) -> Path | None:
        raw = self.settings.DOCUMENT_ARTIFACTS_PATH
        return Path(raw).expanduser() if raw else None

    def _ocr_model_root(self, artifacts_path: Path | None) -> Path:
        if artifacts_path is not None:
            return artifacts_path / "RapidOcr"
        # Writable fallback for local runs: rapidocr defaults to a directory
        # inside site-packages, where a non-root process cannot write.
        return Path.home() / ".cache" / "rapidocr"

    # -------------------------------------------------------------------- helpers

    def _finalize(self, markdown: str, pages: int, engine: str) -> DocumentContent:
        limit = self.settings.DOCUMENT_MAX_CHARS
        truncated = limit > 0 and len(markdown) > limit
        if truncated:
            total = len(markdown)
            markdown = (
                markdown[:limit].rstrip()
                + f"\n\n[document truncated: showing the first {limit} of {total} characters]"
            )
        return DocumentContent(
            markdown=markdown,
            pages=pages,
            engine=engine,
            truncated=truncated,
        )

    def _validate_size(self, size: int, file_name: str) -> None:
        limit_mb = self.settings.DOCUMENT_MAX_FILE_MB
        if limit_mb > 0 and size > limit_mb * 1024 * 1024:
            raise DocumentConversionError(
                f"{file_name} is too large ({size / 1024 / 1024:.1f} MB); "
                f"the limit is {limit_mb} MB."
            )

    def _reject_google_signin_page(self, data: bytes, label: str) -> None:
        head = data[:8192].lower()
        if (
            b"<html" in head
            and b"google drive" in head
            and b"sign in" in head
        ):
            raise self._signin_error(label)

    @staticmethod
    def _signin_error(label: str) -> DocumentConversionError:
        return DocumentConversionError(
            f"Google returned its sign-in page instead of {label}. "
            "The file is not accessible without the connected Google account. "
            "Share the file with that account (or connect it) and retry."
        )

    def _validate_pages(self, pages: int) -> None:
        limit = self.settings.DOCUMENT_MAX_PAGES
        if limit > 0 and pages > limit:
            raise DocumentConversionError(
                f"The document has {pages} pages; the limit is {limit}."
            )

    def _conversion_error(self, label: str, error: Exception) -> DocumentConversionError:
        logger.exception("Document conversion failed: %s", label)
        detail = str(error).strip()
        if len(detail) > 300:
            detail = detail[:300].rstrip() + "..."

        if isinstance(error, PermissionError) or "Permission denied" in detail:
            hint = (
                "The OCR models are not readable by the bot user. "
                "Set DOCUMENT_ARTIFACTS_PATH to a readable model directory "
                "or turn DOCUMENT_OCR_ENABLED off."
            )
        elif not detail:
            hint = "The document could not be parsed."
        else:
            hint = f"The document could not be parsed: {detail}"

        return DocumentConversionError(f"Failed to convert {label}. {hint}")
