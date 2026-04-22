from __future__ import annotations

# PDF source의 capture 경로와 전략을 결정하는 helper.


def resolve_pdf_capture(uri: str) -> tuple[str, str]:
    normalized = (uri or "").strip()
    return normalized, "pdf_text_extract_v1"


__all__ = ["resolve_pdf_capture"]
