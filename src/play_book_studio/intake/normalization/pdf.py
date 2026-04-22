from __future__ import annotations

# PDF 원문에서 텍스트/outline을 추출하는 intake 정규화 보조 모듈.

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_PDF_TEXT_FALLBACK_RE = re.compile(rb"\((?:\\.|[^\\)]){2,}\)")
_PDF_OCTAL_ESCAPE_RE = re.compile(rb"\\([0-7]{1,3})")
_PDF_INTERNAL_TOKEN_RE = re.compile(
    r"(?:\bendobj\b|/Type\s+/Page\b|/Filter\s+/FlateDecode\b)",
    re.IGNORECASE,
)
_CONTROL_CHAR_RE = re.compile(r"[\x01-\x08\x0b\x0c\x0e-\x1f]")
_DUPLICATED_TOKEN_RE = re.compile(r"\b([A-Za-z0-9가-힣][A-Za-z0-9가-힣\-\./®]{0,})\s+\1\b")
_DOCLING_IMAGE_COMMENT_RE = re.compile(r"<!--\s*image\s*-->", re.IGNORECASE)
_RAPIDOCR_ENGINE: Any | None = None


@dataclass(slots=True)
class PdfOutlineEntry:
    level: int
    title: str


def extract_pdf_markdown_with_docling(source: str | Path) -> str:
    return _extract_pdf_markdown_with_docling(source, enable_ocr=False)


def extract_pdf_markdown_with_docling_ocr(source: str | Path) -> str:
    return _extract_pdf_markdown_with_docling(source, enable_ocr=True)


def _extract_pdf_markdown_with_docling(source: str | Path, *, enable_ocr: bool) -> str:
    path = Path(source).expanduser()
    try:
        from docling.datamodel.base_models import InputFormat  # type: ignore[import-not-found]
        from docling.datamodel.pipeline_options import PdfPipelineOptions  # type: ignore[import-not-found]
        from docling.document_converter import DocumentConverter, PdfFormatOption  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"docling을 불러오지 못했습니다: {exc}") from exc

    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = enable_ocr
    # force_backend_text=True causes character-level tokenization on Korean PDFs.
    # Let docling use its layout analysis engine instead for clean paragraph merging.
    pipeline_options.force_backend_text = False
    converter = DocumentConverter(
        allowed_formats=[InputFormat.PDF],
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
        },
    )
    result = converter.convert(str(path))
    markdown = result.document.export_to_markdown()
    markdown = _normalize_docling_markdown(markdown)
    if not markdown.strip():
        raise ValueError("docling이 비어 있는 Markdown을 반환했습니다.")
    return markdown


def extract_pdf_pages(source: str | Path) -> list[str]:
    path = Path(source).expanduser()
    errors: list[str] = []

    try:
        pages = _extract_pdf_pages_with_pypdf(path)
        if _looks_like_real_pdf_text(pages):
            return pages
        if pages:
            errors.append("pypdf: low quality text")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"pypdf: {exc}")

    try:
        pages = _extract_pdf_pages_with_mdls(path)
        if _looks_like_real_pdf_text(pages):
            return pages
        if pages:
            errors.append("mdls: low quality text")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"mdls: {exc}")

    fallback_pages = _extract_pdf_pages_with_string_scan(path)
    if _looks_like_real_pdf_text(fallback_pages):
        return fallback_pages
    if fallback_pages:
        errors.append("string_scan: low quality text")

    try:
        pages = _extract_pdf_pages_with_rendered_ocr(path)
        if _looks_like_real_pdf_text(pages):
            return pages
        if pages:
            errors.append("rendered_ocr: low quality text")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"rendered_ocr: {exc}")

    detail = "; ".join(errors) if errors else "텍스트를 찾지 못함"
    raise ValueError(
        "PDF 텍스트를 추출하지 못했습니다. "
        "텍스트 기반 PDF인지 확인하거나 OCR runtime/사전 OCR 산출물을 준비해야 합니다. "
        f"detail={detail}"
    )


def extract_pdf_outline(source: str | Path) -> list[PdfOutlineEntry]:
    path = Path(source).expanduser()
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]

        reader = PdfReader(str(path))
        outline = reader.outline
    except Exception:  # noqa: BLE001
        return []

    entries: list[PdfOutlineEntry] = []

    def walk(items: object, *, depth: int) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if isinstance(item, list):
                walk(item, depth=depth + 1)
                continue
            title = str(getattr(item, "title", "") or "").strip()
            if not title:
                continue
            if title.lower() == "table of contents":
                continue
            entries.append(PdfOutlineEntry(level=max(depth, 1), title=title))

    walk(outline, depth=1)
    return entries


def _extract_pdf_pages_with_pypdf(path: Path) -> list[str]:
    from pypdf import PdfReader  # type: ignore[import-not-found]

    reader = PdfReader(str(path))
    pages = [_normalize_page_text(page.extract_text() or "") for page in reader.pages]
    return [page for page in pages if page]


def _extract_pdf_pages_with_mdls(path: Path) -> list[str]:
    completed = subprocess.run(
        ["mdls", "-raw", "-name", "kMDItemTextContent", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip() or "mdls failed"
        raise RuntimeError(stderr)
    text = (completed.stdout or "").strip()
    if not text or text == "(null)":
        raise ValueError("Spotlight text content unavailable")
    return [_normalize_page_text(text)]


def _extract_pdf_pages_with_string_scan(path: Path) -> list[str]:
    payload = path.read_bytes()
    fragments: list[str] = []
    for match in _PDF_TEXT_FALLBACK_RE.finditer(payload):
        decoded = _decode_pdf_string(match.group(0)[1:-1])
        cleaned = _normalize_page_text(decoded)
        if cleaned:
            fragments.append(cleaned)
    merged = "\n".join(fragment for fragment in fragments if fragment)
    if not merged.strip():
        return []
    return [_normalize_page_text(merged)]


def _rendered_pdf_ocr_engine():
    global _RAPIDOCR_ENGINE
    if _RAPIDOCR_ENGINE is not None:
        return _RAPIDOCR_ENGINE
    try:
        from rapidocr import RapidOCR  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"rapidocr unavailable: {exc}") from exc
    _RAPIDOCR_ENGINE = RapidOCR()
    return _RAPIDOCR_ENGINE


def _extract_pdf_pages_with_rendered_ocr(path: Path) -> list[str]:
    try:
        import pypdfium2 as pdfium  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"pypdfium2 unavailable: {exc}") from exc

    document = pdfium.PdfDocument(str(path))
    extracted_pages: list[str] = []
    try:
        ocr = _rendered_pdf_ocr_engine()
        for page_index in range(len(document)):
            page = document[page_index]
            try:
                bitmap = page.render(scale=2)
                pil_image = bitmap.to_pil()
                output = ocr(pil_image)
            finally:
                try:
                    page.close()
                except Exception:  # noqa: BLE001
                    pass
            page_text = _ocr_output_text(output)
            normalized = _normalize_page_text(page_text)
            if normalized:
                extracted_pages.append(normalized)
    finally:
        document.close()
    return extracted_pages


def _ocr_output_text(output: object) -> str:
    txts = getattr(output, "txts", None)
    if isinstance(txts, (list, tuple)):
        return "\n".join(str(item).strip() for item in txts if str(item).strip())
    if isinstance(output, dict):
        values = output.get("txts")
        if isinstance(values, (list, tuple)):
            return "\n".join(str(item).strip() for item in values if str(item).strip())
    return ""


def _decode_pdf_string(raw: bytes) -> str:
    escaped = raw.replace(rb"\(", b"(").replace(rb"\)", b")").replace(rb"\\", b"\\")

    def _replace_octal(match: re.Match[bytes]) -> bytes:
        return bytes([int(match.group(1), 8)])

    escaped = _PDF_OCTAL_ESCAPE_RE.sub(_replace_octal, escaped)
    escaped = escaped.replace(rb"\n", b"\n").replace(rb"\r", b"\n").replace(rb"\t", b"\t")
    return escaped.decode("utf-8", errors="ignore")


def _normalize_page_text(text: str) -> str:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\x00", "")
    normalized = re.sub(r"\n[ \t]+\n", "\n", normalized)
    normalized = re.sub(r"[ \t]+\n", "\n", normalized)
    normalized = re.sub(r"\n[ \t]+", "\n", normalized)
    normalized = re.sub(r"(?<!\n)\n(?!\n)", " ", normalized)
    normalized = re.sub(r"[ \t]{2,}", " ", normalized)
    while True:
        deduped = _DUPLICATED_TOKEN_RE.sub(r"\1", normalized)
        if deduped == normalized:
            break
        normalized = deduped
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _normalize_docling_markdown(markdown: str) -> str:
    normalized = str(markdown or "").replace("\r\n", "\n").replace("\r", "\n")
    normalized = _DOCLING_IMAGE_COMMENT_RE.sub("", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _looks_like_real_pdf_text(pages: list[str]) -> bool:
    if not pages:
        return False
    merged = "\n".join(page for page in pages if page).strip()
    if len(merged) < 24:
        return False
    if _PDF_INTERNAL_TOKEN_RE.search(merged):
        return False
    control_count = len(_CONTROL_CHAR_RE.findall(merged))
    if control_count > max(8, len(merged) // 120):
        return False
    printable_count = sum(
        1
        for char in merged
        if char.isprintable() or char in "\n\t"
    )
    if printable_count / max(len(merged), 1) < 0.96:
        return False
    return True
