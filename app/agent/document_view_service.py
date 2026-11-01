from pathlib import Path
from tempfile import NamedTemporaryFile

from docling.document_converter import DocumentConverter


class DocumentViewService:

    def __init__(self):
        self.converter = DocumentConverter()

    def convert_to_markdown(self, url: str) -> str:
        result = self.converter.convert(url)
        return result.document.export_to_markdown()

    def convert_bytes_to_markdown(self, data: bytes, file_name: str) -> str:
        suffix = Path(file_name).suffix.lower()
        with NamedTemporaryFile(suffix=suffix) as document:
            document.write(data)
            document.flush()
            return self.convert_to_markdown(document.name)
