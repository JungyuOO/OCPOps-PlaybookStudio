"""captured source를 canonical book으로 정규화하는 패키지."""

from .pdf import PdfOutlineEntry, _normalize_page_text, extract_pdf_markdown_with_docling, extract_pdf_outline, extract_pdf_pages
from .pdf_rows import (
    _build_pdf_rows_from_docling_markdown,
    _prepare_pdf_page_text,
    _segment_pdf_page,
)

__all__ = [
    "CustomerPackNormalizeService",
    "PdfOutlineEntry",
    "_normalize_page_text",
    "extract_pdf_markdown_with_docling",
    "extract_pdf_outline",
    "extract_pdf_pages",
    "_build_pdf_rows_from_docling_markdown",
    "_prepare_pdf_page_text",
    "_segment_pdf_page",
]


def __getattr__(name: str):
    if name == "CustomerPackNormalizeService":
        from .service import CustomerPackNormalizeService

        return CustomerPackNormalizeService
    raise AttributeError(name)
