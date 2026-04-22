"""업로드 문서/URL capture 패키지."""

from .pdf import resolve_pdf_capture
from .web import resolve_web_capture_url

__all__ = [
    "resolve_pdf_capture",
    "resolve_web_capture_url",
]
