from types import SimpleNamespace

import pytest

from app.agent import document_view_service as service_module
from app.agent.document_view_service import (
    EMPTY_PAGE_MARKER,
    DocumentContent,
    DocumentViewService,
)
from app.core.errors import DocumentConversionError


def make_settings(**overrides):
    values = {
        "DOCUMENT_OCR_ENABLED": True,
        "DOCUMENT_OCR_LANG": "eslav",
        "DOCUMENT_TABLE_STRUCTURE": False,
        "DOCUMENT_MAX_PAGES": 100,
        "DOCUMENT_MAX_FILE_MB": 30,
        "DOCUMENT_MAX_CHARS": 50_000,
        "DOCUMENT_ARTIFACTS_PATH": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeTextPage:
    def __init__(self, text: str):
        self.text = text

    def get_text_range(self) -> str:
        return self.text

    def close(self) -> None:
        pass


class FakePage:
    def __init__(self, text: str):
        self.text = text

    def get_textpage(self) -> FakeTextPage:
        return FakeTextPage(self.text)

    def close(self) -> None:
        pass


class FakePdfDocument:
    def __init__(self, pages):
        self.pages = pages

    def __len__(self):
        return len(self.pages)

    def __getitem__(self, index):
        return FakePage(self.pages[index])

    def close(self):
        pass


def install_pdf(monkeypatch, pages):
    monkeypatch.setattr(
        service_module.pdfium,
        "PdfDocument",
        lambda data: FakePdfDocument(pages),
    )


class FakeConversionResult:
    def __init__(self, markdown: str, pages: int):
        self.pages = list(range(pages))
        self.document = SimpleNamespace(export_to_markdown=lambda: markdown)


class FakeConverter:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.sources = []

    def convert(self, source):
        self.sources.append(source)
        if self.error is not None:
            raise self.error
        return self.result


@pytest.mark.asyncio
async def test_text_pdf_uses_pypdfium2_without_docling(monkeypatch):
    install_pdf(
        monkeypatch,
        [
            "ПАРАЛЛЕЛИЗМ\n"
            "Поддержка асинхронного выполнения задач и основы оффлоада\n"
            "К. Владимиров, Syntacore, 2023\n"
            "Параллелизм в алгоритмах, явная асинхронность, оффлоад и SYCL",
            "",
        ],
    )
    service = DocumentViewService(make_settings())
    monkeypatch.setattr(
        service, "_get_converter", lambda: pytest.fail("docling must not be used")
    )

    content = await service.convert_bytes_to_markdown(b"pdf", "lecture.pdf")

    assert isinstance(content, DocumentContent)
    assert content.engine == "pypdfium2"
    assert content.pages == 2
    assert content.truncated is False
    assert "## Page 1" in content.markdown
    assert "ПАРАЛЛЕЛИЗМ" in content.markdown
    assert EMPTY_PAGE_MARKER in content.markdown


@pytest.mark.asyncio
async def test_scan_falls_back_to_docling(monkeypatch):
    install_pdf(monkeypatch, ["скан"])
    service = DocumentViewService(make_settings())
    converter = FakeConverter(FakeConversionResult("# scanned text from the layout model", 1))
    monkeypatch.setattr(service, "_get_converter", lambda: converter)

    content = await service.convert_bytes_to_markdown(b"pdf", "scan.pdf")

    assert content.engine == "docling"
    assert content.markdown == "# scanned text from the layout model"
    assert len(converter.sources) == 1


@pytest.mark.asyncio
async def test_scan_without_ocr_reports_a_clear_error(monkeypatch):
    install_pdf(monkeypatch, [""])
    service = DocumentViewService(make_settings(DOCUMENT_OCR_ENABLED=False))
    converter = FakeConverter(FakeConversionResult("", 1))
    monkeypatch.setattr(service, "_get_converter", lambda: converter)

    with pytest.raises(DocumentConversionError, match="DOCUMENT_OCR_ENABLED"):
        await service.convert_bytes_to_markdown(b"pdf", "scan.pdf")


@pytest.mark.asyncio
async def test_unreadable_pdf_falls_back_to_docling(monkeypatch):
    def broken(data):
        raise RuntimeError("not a pdf")

    monkeypatch.setattr(service_module.pdfium, "PdfDocument", broken)
    service = DocumentViewService(make_settings())
    converter = FakeConverter(FakeConversionResult("text extracted by docling from the broken pdf", 1))
    monkeypatch.setattr(service, "_get_converter", lambda: converter)

    content = await service.convert_bytes_to_markdown(b"pdf", "broken.pdf")

    assert content.engine == "docling"


@pytest.mark.asyncio
async def test_size_limit_is_enforced_before_parsing(monkeypatch):
    monkeypatch.setattr(
        service_module.pdfium,
        "PdfDocument",
        lambda data: pytest.fail("must not parse an oversized file"),
    )
    service = DocumentViewService(make_settings(DOCUMENT_MAX_FILE_MB=1))

    with pytest.raises(DocumentConversionError, match="too large"):
        await service.convert_bytes_to_markdown(b"x" * (1024 * 1024 + 1), "big.pdf")


@pytest.mark.asyncio
async def test_page_limit_is_enforced(monkeypatch):
    install_pdf(monkeypatch, ["text"] * 5)
    service = DocumentViewService(make_settings(DOCUMENT_MAX_PAGES=3))

    with pytest.raises(DocumentConversionError, match="5 pages"):
        await service.convert_bytes_to_markdown(b"pdf", "long.pdf")


@pytest.mark.asyncio
async def test_long_markdown_is_truncated(monkeypatch):
    install_pdf(monkeypatch, ["x" * 200])
    service = DocumentViewService(make_settings(DOCUMENT_MAX_CHARS=100))

    content = await service.convert_bytes_to_markdown(b"pdf", "long.pdf")

    assert content.truncated is True
    assert len(content.markdown) < 300
    assert "document truncated" in content.markdown


@pytest.mark.asyncio
async def test_conversion_failure_is_wrapped(monkeypatch):
    install_pdf(monkeypatch, [""])
    service = DocumentViewService(make_settings())
    monkeypatch.setattr(
        service,
        "_get_converter",
        lambda: FakeConverter(error=RuntimeError("layout model exploded")),
    )

    with pytest.raises(DocumentConversionError) as raised:
        await service.convert_bytes_to_markdown(b"pdf", "scan.pdf")

    assert "layout model exploded" in str(raised.value)


@pytest.mark.asyncio
async def test_permission_error_mentions_model_directory(monkeypatch):
    install_pdf(monkeypatch, [""])
    service = DocumentViewService(make_settings())
    monkeypatch.setattr(
        service,
        "_get_converter",
        lambda: FakeConverter(error=PermissionError("denied")),
    )

    with pytest.raises(DocumentConversionError) as raised:
        await service.convert_bytes_to_markdown(b"pdf", "scan.pdf")

    assert "DOCUMENT_ARTIFACTS_PATH" in str(raised.value)


@pytest.mark.asyncio
async def test_url_conversion_uses_docling(monkeypatch):
    service = DocumentViewService(make_settings())
    converter = FakeConverter(FakeConversionResult("# markdown extracted from the url", 3))
    monkeypatch.setattr(service, "_get_converter", lambda: converter)

    content = await service.convert_to_markdown("https://example.test/file.pdf")

    assert content.markdown == "# markdown extracted from the url"
    assert converter.sources == ["https://example.test/file.pdf"]


def test_pipeline_options_configure_offline_ocr():
    service = DocumentViewService(
        make_settings(DOCUMENT_ARTIFACTS_PATH="/opt/docling-models")
    )

    options = service._pipeline_options()

    assert options.do_ocr is True
    assert options.do_table_structure is False
    assert str(options.artifacts_path) == "/opt/docling-models"
    assert options.ocr_options.backend == "onnxruntime"
    assert options.ocr_options.lang == ["eslav"]
    assert (
        options.ocr_options.rapidocr_params["Global.model_root_dir"]
        == "/opt/docling-models/RapidOcr"
    )


def test_pipeline_options_skip_ocr_when_disabled():
    from docling.datamodel.pipeline_options import RapidOcrOptions

    service = DocumentViewService(make_settings(DOCUMENT_OCR_ENABLED=False))

    options = service._pipeline_options()

    assert options.do_ocr is False
    assert not isinstance(options.ocr_options, RapidOcrOptions)
