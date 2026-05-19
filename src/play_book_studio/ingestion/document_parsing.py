"""Internal document parsing boundary for upload ingestion.

This module intentionally models the Kordoc-style contract inside the Python
ingestion layer: detect the document format, produce Markdown, keep structured
blocks, and surface image assets separately so a vision model can describe them.
"""

from __future__ import annotations

import hashlib
import contextlib
import io
import json
import mimetypes
import re
import uuid
import zipfile
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal


DocumentFormat = Literal[
    "md",
    "txt",
    "asciidoc",
    "pdf",
    "docx",
    "pptx",
    "xlsx",
    "hwp",
    "hwpx",
    "hwpml",
    "image",
    "unknown",
]
ParseStatus = Literal["parsed", "staged", "failed"]
BlockType = Literal["heading", "paragraph", "table", "code", "image"]
PdfLayoutBlockKind = Literal["heading", "paragraph", "table", "code"]


MARKDOWN_FORMATS = {"md", "asciidoc"}
TEXT_FORMATS = {"txt"}
CONVERTER_FORMATS = {"pdf", "docx", "pptx", "xlsx"}
IMAGE_FORMATS = {"image"}
UNSUPPORTED_UPLOAD_FORMATS = {"hwp", "hwpx", "hwpml"}


@dataclass(frozen=True, slots=True)
class DocumentAsset:
    asset_id: str
    asset_type: str
    filename: str
    mime_type: str
    sha256: str
    storage_key: str = ""
    description: str = ""
    ocr_text: str = ""
    page_number: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DocumentBlock:
    block_id: str
    ordinal: int
    block_type: BlockType
    markdown: str
    text: str
    heading_level: int | None = None
    section_path: tuple[str, ...] = field(default_factory=tuple)
    section_number: str = ""
    heading_title: str = ""
    source_anchor: str = ""
    toc_path: tuple[str, ...] = field(default_factory=tuple)
    asset_ids: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["section_path"] = list(self.section_path)
        payload["toc_path"] = list(self.toc_path)
        payload["asset_ids"] = list(self.asset_ids)
        return payload


@dataclass(frozen=True, slots=True)
class ParsedUploadDocument:
    document_id: str
    filename: str
    document_format: DocumentFormat
    mime_type: str
    sha256: str
    markdown: str
    blocks: tuple[DocumentBlock, ...] = field(default_factory=tuple)
    assets: tuple[DocumentAsset, ...] = field(default_factory=tuple)
    parser_name: str = "internal_upload_parser"
    parser_version: str = "0.1"
    status: ParseStatus = "parsed"
    warnings: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "filename": self.filename,
            "document_format": self.document_format,
            "mime_type": self.mime_type,
            "sha256": self.sha256,
            "markdown": self.markdown,
            "blocks": [block.to_dict() for block in self.blocks],
            "assets": [asset.to_dict() for asset in self.assets],
            "parser_name": self.parser_name,
            "parser_version": self.parser_version,
            "status": self.status,
            "warnings": list(self.warnings),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ConvertedMarkdown:
    markdown: str
    assets: tuple[DocumentAsset, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    chunk_id: str
    chunk_key: str
    ordinal: int
    markdown: str
    embedding_text: str
    section_path: tuple[str, ...] = field(default_factory=tuple)
    section_number: str = ""
    heading_title: str = ""
    source_anchor: str = ""
    toc_path: tuple[str, ...] = field(default_factory=tuple)
    asset_ids: tuple[str, ...] = field(default_factory=tuple)
    block_ordinals: tuple[int, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["section_path"] = list(self.section_path)
        payload["toc_path"] = list(self.toc_path)
        payload["asset_ids"] = list(self.asset_ids)
        payload["block_ordinals"] = list(self.block_ordinals)
        return payload


@dataclass(frozen=True, slots=True)
class PdfLayoutBlock:
    kind: PdfLayoutBlockKind
    text: str
    bbox: tuple[float, float, float, float]
    font_size: float = 0.0
    language: str = ""
    confidence: float = 0.0
    reason: str = ""


MarkdownConverter = Callable[[Path, DocumentFormat], str | ConvertedMarkdown]
ImageDescriber = Callable[[Path, DocumentAsset], str]


_OLE_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")
_IMAGE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),
)
_MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_ASCIIDOC_HEADING_RE = re.compile(r"^(={1,6})\s+(.+?)\s*$")
_SECTION_NUMBER_RE = re.compile(r"^\s*((?:\d+\.)+\d+|\d+)(?:[.)]|장\.)?\s+(.+?)\s*$")
_XML_TEXT_TAG = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
_DOCX_PARAGRAPH_TAG = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"
_DOCX_PARAGRAPH_PROPS_TAG = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pPr"
_DOCX_PARAGRAPH_STYLE_TAG = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pStyle"
_DOCX_TABLE_TAG = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tbl"
_DOCX_ROW_TAG = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tr"
_DOCX_CELL_TAG = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tc"
_PPT_TEXT_TAG = "{http://schemas.openxmlformats.org/drawingml/2006/main}t"
_PPT_TABLE_TAG = "{http://schemas.openxmlformats.org/drawingml/2006/main}tbl"
_PPT_ROW_TAG = "{http://schemas.openxmlformats.org/drawingml/2006/main}tr"
_PPT_CELL_TAG = "{http://schemas.openxmlformats.org/drawingml/2006/main}tc"
_PAGE_MARKER_RE = re.compile(r"^<!--\s*(?:page|slide)\s*:\s*(\d+)\s*-->\s*$", re.IGNORECASE)
_DRAWING_EMBED_RE = re.compile(r'r:embed="([^"]+)"')
_PDF_LAYOUT_MARKER = "<!-- pbs-pdf-layout-v1 -->"
_PDF_LAYOUT_BLOCK_START_RE = re.compile(r"^<!--\s*pbs-layout-block\s+(?P<payload>\{.*\})\s*-->\s*$")
_PDF_LAYOUT_BLOCK_END = "<!-- /pbs-layout-block -->"


def detect_document_format(path: Path, *, sample_size: int = 4096) -> DocumentFormat:
    suffix = path.suffix.lower()
    head = path.read_bytes()[:sample_size]

    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(_OLE_MAGIC):
        return "hwp" if suffix == ".hwp" else "unknown"
    if _is_image_signature(head):
        return "image"
    if head.lstrip().startswith((b"<?xml", b"<HWPML", b"<hwpml")) and b"HWPML" in head[:sample_size].upper():
        return "hwpml"
    if zipfile.is_zipfile(path):
        return _detect_zip_document_format(path, suffix)

    if suffix in {".md", ".markdown"}:
        return "md"
    if suffix in {".adoc", ".asciidoc"}:
        return "asciidoc"
    if suffix in {".txt", ".log", ".csv"}:
        return "txt"
    if suffix == ".hwp":
        return "hwp"
    if suffix == ".hwpx":
        return "hwpx"
    return "unknown"


def parse_upload_document(
    path: Path,
    *,
    markdown_converter: MarkdownConverter | None = None,
    image_describer: ImageDescriber | None = None,
    progress: Callable[[str, str, dict[str, Any]], None] | None = None,
) -> ParsedUploadDocument:
    def _emit(status: str, **detail: Any) -> None:
        if progress is not None:
            progress("parse", status, detail)

    path = path.resolve()
    content = path.read_bytes()
    document_format = detect_document_format(path)
    sha256 = hashlib.sha256(content).hexdigest()
    mime_type = _detect_mime_type(path, document_format)
    document_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{path.name}:{sha256}"))

    _emit("info", note=f"포맷 감지: {document_format} · {len(content):,} bytes · sha256={sha256[:12]}…")

    warnings: list[str] = []
    assets: list[DocumentAsset] = []
    converter_metadata: dict[str, Any] = {}

    if document_format in MARKDOWN_FORMATS | TEXT_FORMATS:
        _emit("info", note="텍스트/마크다운 직접 읽기")
        markdown = path.read_text(encoding="utf-8-sig").strip()
        if document_format == "txt":
            markdown = _plain_text_to_markdown(markdown, title=path.stem)
    elif document_format in IMAGE_FORMATS:
        _emit("info", note="이미지 자산 처리")
        asset = _image_asset(path, sha256=sha256, mime_type=mime_type)
        if image_describer:
            _emit(
                "progress",
                note=f"이미지 OCR/설명 처리 중: {asset.filename} (0/1)",
                task_kind="image_ocr",
                progress_key="image_ocr",
                item_label=asset.filename,
                progress_current=0,
                progress_total=1,
                progress_percent=0,
            )
            asset = _describe_asset(path, asset, image_describer=image_describer)
            _emit(
                "progress",
                note=f"이미지 OCR/설명 완료: {asset.filename} (1/1)",
                task_kind="image_ocr",
                progress_key="image_ocr",
                item_label=asset.filename,
                progress_current=1,
                progress_total=1,
                progress_percent=100,
            )
        assets.append(asset)
        markdown = _image_markdown(asset)
    elif document_format in UNSUPPORTED_UPLOAD_FORMATS:
        raise ValueError(
            f"{document_format} uploads are intentionally unsupported for this service. "
            "Use PDF, DOCX, PPTX, XLSX, text, Markdown, or image inputs."
        )
    elif document_format in CONVERTER_FORMATS:
        # PDF인 경우 progress callback 같이 흘려서 추출기 진행 상황을 emit
        if document_format == "pdf" and markdown_converter is None:
            converted = _convert_pdf_to_markdown(path, progress=progress)
        else:
            if markdown_converter is None:
                markdown_converter = _default_markdown_converter
            _emit("info", note=f"{document_format} 변환기 호출 (markitdown)")
            converted = markdown_converter(path, document_format)
        if isinstance(converted, ConvertedMarkdown):
            markdown = converted.markdown.strip()
            assets.extend(converted.assets)
            warnings.extend(converted.warnings)
            converter_metadata.update(converted.metadata)
        else:
            markdown = converted.strip()
        if not markdown:
            raise ValueError(f"markdown converter produced empty output for {path.name}")
        if image_describer and assets:
            _emit("info", note=f"Company LLM 이미지 OCR/설명 생성 중 ({len(assets)}개 자산)...")
            described_assets: list[DocumentAsset] = []
            total_assets = len(assets)
            for index, asset in enumerate(assets, start=1):
                _emit(
                    "progress",
                    note=f"이미지 OCR/설명 처리 중: {asset.filename} ({index}/{total_assets})",
                    task_kind="image_ocr",
                    progress_key="image_ocr",
                    item_label=asset.filename,
                    progress_current=index - 1,
                    progress_total=total_assets,
                    progress_percent=round(((index - 1) / max(total_assets, 1)) * 100),
                )
                described = _describe_asset(path, asset, image_describer=image_describer)
                described_assets.append(described)
                _emit(
                    "progress",
                    note=f"이미지 OCR/설명 완료: {asset.filename} ({index}/{total_assets})",
                    task_kind="image_ocr",
                    progress_key="image_ocr",
                    item_label=asset.filename,
                    progress_current=index,
                    progress_total=total_assets,
                    progress_percent=round((index / max(total_assets, 1)) * 100),
                )
            assets = described_assets
    else:
        raise ValueError(f"unsupported document format for ingestion: {path.name}")

    _emit("info", note=f"markdown 추출 완료: {len(markdown):,} 자, block 분해 시작")
    blocks = tuple(_markdown_to_blocks(markdown, assets=tuple(assets), document_id=document_id))
    if not blocks:
        warnings.append("no_blocks_detected")
    _emit("info", note=f"block 분해 완료: {len(blocks)} blocks, {len(assets)} assets")

    return ParsedUploadDocument(
        document_id=document_id,
        filename=path.name,
        document_format=document_format,
        mime_type=mime_type,
        sha256=sha256,
        markdown=markdown,
        blocks=blocks,
        assets=tuple(assets),
        warnings=tuple(warnings),
        metadata={
            "byte_size": len(content),
            "source_path": str(path),
            **converter_metadata,
        },
    )


def _detect_zip_document_format(path: Path, suffix: str) -> DocumentFormat:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            mimetype = ""
            if "mimetype" in names:
                try:
                    mimetype = archive.read("mimetype").decode("utf-8", errors="ignore").lower()
                except Exception:  # noqa: BLE001
                    mimetype = ""
    except zipfile.BadZipFile:
        return "unknown"

    lowered = {name.lower() for name in names}
    if suffix == ".hwpx" or "application/hwp+zip" in mimetype or any(name.startswith("contents/") for name in lowered):
        return "hwpx"
    if "[content_types].xml" in lowered:
        if any(name.startswith("word/") for name in lowered):
            return "docx"
        if any(name.startswith("ppt/") for name in lowered):
            return "pptx"
        if any(name.startswith("xl/") for name in lowered):
            return "xlsx"
    if suffix == ".docx":
        return "docx"
    if suffix == ".pptx":
        return "pptx"
    if suffix == ".xlsx":
        return "xlsx"
    return "unknown"


def build_document_chunks(
    parsed: ParsedUploadDocument,
    *,
    max_chars: int = 1400,
    overlap_blocks: int = 1,
) -> tuple[DocumentChunk, ...]:
    chunks: list[DocumentChunk] = []
    current: list[DocumentBlock] = []
    current_chars = 0
    ordinal = 0

    def flush() -> None:
        nonlocal current, current_chars, ordinal
        if not current:
            return
        markdown = "\n\n".join(block.markdown for block in current).strip()
        section_block = _last_section_block(current)
        section_path = section_block.section_path if section_block else ()
        page_numbers = [
            int(page_number)
            for page_number in (block.metadata.get("page_number") for block in current)
            if isinstance(page_number, int)
        ]
        asset_ids = tuple(dict.fromkeys(asset_id for block in current for asset_id in block.asset_ids))
        block_ordinals = tuple(block.ordinal for block in current)
        chunk_key = f"{parsed.document_id}:{ordinal}"
        stripped_markdown = _strip_markdown(markdown)
        section_context = " > ".join(part for part in section_path if part)
        asset_context = "\n\n".join(
            asset.description
            for asset in parsed.assets
            if asset.asset_id in asset_ids and asset.description
        ).strip()
        stripped_with_asset_context = (
            f"{stripped_markdown}\n\n[이미지 OCR/설명]\n{asset_context}"
            if asset_context
            else stripped_markdown
        )
        embedding_text = (
            f"{section_context}\n\n{stripped_with_asset_context}"
            if section_context
            else stripped_with_asset_context
        )
        chunks.append(
            DocumentChunk(
                chunk_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{chunk_key}:{markdown}")),
                chunk_key=chunk_key,
                ordinal=ordinal,
                markdown=markdown,
                embedding_text=embedding_text,
                section_path=section_path,
                section_number=section_block.section_number if section_block else "",
                heading_title=section_block.heading_title if section_block else "",
                source_anchor=section_block.source_anchor if section_block else "",
                toc_path=section_block.toc_path if section_block else (),
                asset_ids=asset_ids,
                block_ordinals=block_ordinals,
                metadata={
                    "filename": parsed.filename,
                    "document_format": parsed.document_format,
                    "page_start": min(page_numbers) if page_numbers else None,
                    "page_end": max(page_numbers) if page_numbers else None,
                    "chunk_char_count": len(markdown),
                    "block_count": len(current),
                },
            )
        )
        ordinal += 1
        if overlap_blocks <= 0:
            current = []
        else:
            current = current[-overlap_blocks:]
        current_chars = sum(len(block.markdown) for block in current)

    for block in parsed.blocks:
        if block.block_type == "heading":
            flush()
            current = [block]
            current_chars = len(block.markdown)
            continue
        block_chars = len(block.markdown)
        if current and current_chars + block_chars > max_chars:
            flush()
        current.append(block)
        current_chars += block_chars
        if block.block_type in {"table", "code", "image"} and current_chars >= max_chars:
            flush()
    flush()
    return tuple(chunks)


def _is_image_signature(head: bytes) -> bool:
    for signature, mime_type in _IMAGE_SIGNATURES:
        if head.startswith(signature):
            if mime_type == "image/webp":
                return len(head) >= 12 and head[8:12] == b"WEBP"
            return True
    return False


def _detect_mime_type(path: Path, document_format: DocumentFormat) -> str:
    if document_format == "hwp":
        return "application/x-hwp"
    if document_format == "hwpx":
        return "application/hwp+zip"
    if document_format == "hwpml":
        return "application/xml"
    if document_format == "md":
        return "text/markdown"
    if document_format == "asciidoc":
        return "text/asciidoc"
    if document_format == "txt":
        return "text/plain"
    if document_format == "image":
        guessed, _ = mimetypes.guess_type(path.name)
        return guessed or "application/octet-stream"
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _plain_text_to_markdown(text: str, *, title: str) -> str:
    if not text:
        return f"# {title}".strip()
    if text.lstrip().startswith("#"):
        return text.strip()
    return f"# {title}\n\n{text.strip()}".strip()


def _image_asset(path: Path, *, sha256: str, mime_type: str) -> DocumentAsset:
    asset_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{path.name}:{sha256}:image"))
    return DocumentAsset(
        asset_id=asset_id,
        asset_type="image",
        filename=path.name,
        mime_type=mime_type,
        sha256=sha256,
        storage_key=f"uploads/assets/{asset_id}{path.suffix.lower()}",
    )


def _image_markdown(asset: DocumentAsset) -> str:
    description = asset.description.strip()
    if description:
        return f"![{asset.filename}](asset://{asset.asset_id})\n\n{description}"
    return f"![{asset.filename}](asset://{asset.asset_id})"


def _describe_asset(path: Path, asset: DocumentAsset, *, image_describer: ImageDescriber) -> DocumentAsset:
    vision_model = str(getattr(image_describer, "vision_model", "") or "").strip()
    vision_provider = str(getattr(image_describer, "vision_provider", "") or "").strip()
    try:
        description = image_describer(path, asset).strip()
    except Exception as exc:  # noqa: BLE001
        metadata = {**dict(asset.metadata), "vision_error": str(exc), "vision_status": "failed"}
        if vision_model:
            metadata.setdefault("vision_model", vision_model)
        if vision_provider:
            metadata.setdefault("vision_provider", vision_provider)
        return DocumentAsset(**{**asset.to_dict(), "metadata": metadata})
    if not description:
        metadata = {**dict(asset.metadata), "vision_status": "empty"}
        if vision_model:
            metadata.setdefault("vision_model", vision_model)
        if vision_provider:
            metadata.setdefault("vision_provider", vision_provider)
        return DocumentAsset(**{**asset.to_dict(), "metadata": metadata})
    metadata = {**dict(asset.metadata)}
    metadata.setdefault("vision_status", "described")
    if vision_model:
        metadata.setdefault("vision_model", vision_model)
    if vision_provider:
        metadata.setdefault("vision_provider", vision_provider)
    return DocumentAsset(**{**asset.to_dict(), "description": description, "metadata": metadata})


def _append_asset_descriptions(markdown: str, assets: list[DocumentAsset]) -> str:
    result = markdown
    for asset in assets:
        if not asset.description:
            continue
        marker = f"asset://{asset.asset_id})"
        replacement = f"asset://{asset.asset_id})\n\n{asset.description}"
        if marker in result and replacement not in result:
            result = result.replace(marker, replacement, 1)
    return result


def _markdown_to_blocks(
    markdown: str,
    *,
    assets: tuple[DocumentAsset, ...],
    document_id: str,
) -> list[DocumentBlock]:
    blocks: list[DocumentBlock] = []
    current_lines: list[str] = []
    section_path: list[str] = []
    toc_path: list[str] = []
    section_number = ""
    heading_title = ""
    source_anchor = ""
    page_number: int | None = None
    in_code = False
    code_lines: list[str] = []
    ordinal = 0

    asset_ids_by_filename = {asset.filename: asset.asset_id for asset in assets}

    def append_block(block_type: BlockType, lines: list[str], heading_level: int | None = None) -> None:
        nonlocal ordinal
        markdown_text = "\n".join(lines).strip()
        if not markdown_text:
            return
        block_asset_ids = tuple(
            asset_id
            for filename, asset_id in asset_ids_by_filename.items()
            if filename in markdown_text or asset_id in markdown_text
        )
        blocks.append(
            DocumentBlock(
                block_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{document_id}:{ordinal}:{markdown_text}")),
                ordinal=ordinal,
                block_type=block_type,
                markdown=markdown_text,
                text=_strip_markdown(markdown_text),
                heading_level=heading_level,
                section_path=tuple(section_path),
                section_number=section_number,
                heading_title=heading_title,
                source_anchor=source_anchor,
                toc_path=tuple(toc_path),
                asset_ids=block_asset_ids,
                metadata={"page_number": page_number} if page_number is not None else {},
            )
        )
        ordinal += 1

    def flush_paragraph() -> None:
        nonlocal current_lines
        if current_lines:
            block_type: BlockType = "table" if _looks_like_markdown_table(current_lines) else "paragraph"
            append_block(block_type, current_lines)
            current_lines = []

    for line in markdown.splitlines():
        stripped = line.strip()
        page_match = _PAGE_MARKER_RE.match(stripped)
        if page_match:
            flush_paragraph()
            page_number = int(page_match.group(1))
            continue
        if stripped.startswith(("```", "~~~")):
            if in_code:
                code_lines.append(line)
                append_block("code", code_lines)
                code_lines = []
                in_code = False
            else:
                flush_paragraph()
                code_lines = [line]
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue

        heading_match = _MARKDOWN_HEADING_RE.match(line) or _ASCIIDOC_HEADING_RE.match(line)
        if heading_match:
            flush_paragraph()
            level = len(heading_match.group(1))
            raw_title = heading_match.group(2).strip()
            parsed_number, parsed_title = _split_section_number_title(raw_title)
            section_path = section_path[: max(0, level - 1)]
            toc_path = toc_path[: max(0, level - 1)]
            section_path.append(parsed_title)
            toc_path.append(_toc_label(parsed_number, parsed_title))
            section_number = parsed_number
            heading_title = parsed_title
            source_anchor = _source_anchor(section_path=section_path, section_number=section_number)
            append_block("heading", [f"{'#' * level} {parsed_title}"], heading_level=level)
            continue

        if re.match(r"^!\[[^\]]*]\([^)]+\)", stripped):
            flush_paragraph()
            append_block("image", [line])
            continue

        if not stripped:
            flush_paragraph()
            continue
        current_lines.append(line)

    if in_code and code_lines:
        append_block("code", code_lines)
    flush_paragraph()
    return blocks


def _looks_like_markdown_table(lines: list[str]) -> bool:
    joined = "\n".join(lines)
    return "|" in joined and re.search(r"\|\s*:?-{3,}:?\s*\|", joined) is not None


def _strip_markdown(markdown: str) -> str:
    text = re.sub(r"^#{1,6}\s+", "", markdown, flags=re.MULTILINE)
    text = re.sub(r"!\[([^\]]*)]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", text)
    text = re.sub(r"`{1,3}", "", text)
    return text.strip()


def _default_markdown_converter(path: Path, document_format: DocumentFormat) -> str | ConvertedMarkdown:
    if document_format == "docx":
        return _convert_docx_to_markdown(path)
    if document_format == "pptx":
        return _convert_pptx_to_markdown(path)
    if document_format == "pdf":
        return _convert_pdf_to_markdown(path)
    return _convert_with_markitdown(path)


def _convert_docx_to_markdown(path: Path) -> ConvertedMarkdown:
    lines = [f"# {path.stem}"]
    with zipfile.ZipFile(path) as archive:
        document_xml = archive.read("word/document.xml")
    root = ET.fromstring(document_xml)
    body = root.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}body")
    if body is None:
        raise ValueError(f"DOCX body is missing: {path.name}")
    for child in body:
        if child.tag == _DOCX_PARAGRAPH_TAG:
            text = _xml_text(child, text_tag=_XML_TEXT_TAG)
            if text:
                heading_level = _docx_heading_level(child)
                if heading_level is not None:
                    lines.extend(["", f"{'#' * heading_level} {text}"])
                else:
                    lines.extend(["", text])
        elif child.tag == _DOCX_TABLE_TAG:
            table = _docx_table_to_markdown(child)
            if table:
                lines.extend(["", table])
    markdown = "\n".join(lines).strip()
    if markdown == f"# {path.stem}":
        raise ValueError(f"DOCX produced empty markdown: {path.name}")
    return ConvertedMarkdown(markdown=markdown)


def _convert_pptx_to_markdown(path: Path) -> ConvertedMarkdown:
    lines = [f"# {path.stem}"]
    assets: list[DocumentAsset] = []
    source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        slide_names = sorted(
            (name for name in names if re.match(r"ppt/slides/slide\d+\.xml$", name)),
            key=_natural_key,
        )
        for slide_index, slide_name in enumerate(slide_names, start=1):
            slide_xml = archive.read(slide_name)
            slide_root = ET.fromstring(slide_xml)
            texts = [text for text in _xml_texts(slide_root, text_tag=_PPT_TEXT_TAG) if text.strip()]
            table_markdowns = [
                table_markdown
                for table in slide_root.iter(_PPT_TABLE_TAG)
                if (table_markdown := _pptx_table_to_markdown(table))
            ]
            lines.extend(["", f"<!-- slide: {slide_index} -->", f"## Slide {slide_index}"])
            for text in texts:
                lines.append(text.strip())
            for table_markdown in table_markdowns:
                lines.extend(["", table_markdown])
            for media_name in _pptx_slide_media_names(archive, slide_name, slide_xml):
                if media_name not in names:
                    continue
                content = archive.read(media_name)
                asset = _blob_asset(
                    path,
                    media_name=media_name,
                    content=content,
                    source_sha256=source_sha256,
                    page_number=slide_index,
                )
                assets.append(asset)
                lines.extend(["", _image_markdown(asset)])
    markdown = "\n".join(lines).strip()
    if len(lines) <= 1 and not assets:
        raise ValueError(f"PPTX produced empty markdown: {path.name}")
    return ConvertedMarkdown(markdown=markdown, assets=tuple(assets), metadata={"slide_count": len(slide_names)})


def _looks_like_generated_upload_title(text: str) -> bool:
    compact = re.sub(r"[\s._\-()]+", "", str(text or "")).strip()
    if not compact:
        return True
    if re.fullmatch(r"\d{1,3}\d{2,4}", compact):
        return True
    if re.fullmatch(r"\d{1,3}\d{1,2}\d{1,2}", compact):
        return True
    return False


def _pdf_title_from_pages(pages: list[str], fallback: str) -> str:
    fallback_title = str(fallback or "").strip() or "Uploaded PDF"
    for page in pages:
        for raw_line in str(page or "").splitlines():
            line = " ".join(raw_line.strip().split())
            if not line:
                continue
            if line.startswith("<!--"):
                continue
            if len(line) > 80:
                continue
            if re.fullmatch(r"(?i)page\s+\d+", line):
                continue
            if _looks_like_generated_upload_title(line):
                continue
            return line
    return fallback_title


def _drop_duplicate_pdf_title_line(text: str, title: str) -> str:
    lines = str(text or "").splitlines()
    normalized_title = _normalize_pdf_title_for_compare(title)
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue
        if _normalize_pdf_title_for_compare(line) == normalized_title:
            del lines[index]
        break
    return "\n".join(lines).strip()


def _normalize_pdf_title_for_compare(text: str) -> str:
    return re.sub(r"[\s._\-()]+", "", str(text or "").strip().lower())


def _clean_pdf_line(raw_line: str) -> str:
    return " ".join(str(raw_line or "").strip().split())


_KNOWN_KOREAN_PDF_SECTION_HEADINGS = {
    "개념 살펴보기",
    "주요 개념",
    "핵심 개념",
    "실습 시나리오",
    "확인 방법",
    "체크리스트",
    "출력 예상 결과",
    "환경 변수와 볼륨 마운트 데모",
    "리소스별 설명",
    "동작 방식",
    "사용 방법",
    "구성 요소",
    "역할",
    "특징",
    "타입",
    "예시",
    "실습",
    "정리",
    "요약",
}


_PDF_LANGUAGE_LABELS = {
    "bash": "bash",
    "shell": "bash",
    "sh": "bash",
    "yaml": "yaml",
    "yml": "yaml",
    "json": "json",
}

_PDF_YAML_KEYS = {
    "apiVersion",
    "kind",
    "metadata",
    "spec",
    "storageClassName",
    "selector",
    "matchLabels",
    "labels",
    "annotations",
    "data",
    "stringData",
    "type",
    "namespace",
    "replicas",
    "template",
    "containers",
    "container",
    "image",
    "command",
    "args",
    "env",
    "envFrom",
    "value",
    "valueFrom",
    "configMapKeyRef",
    "secretKeyRef",
    "secretRef",
    "configMapRef",
    "volumeMounts",
    "mountPath",
    "readOnly",
    "volumes",
    "volume",
    "accessModes",
    "resources",
    "requests",
    "storage",
    "provisioner",
    "parameters",
    "reclaimPolicy",
    "volumeBindingMode",
    "persistentVolumeReclaimPolicy",
    "volumeHandle",
    "restartPolicy",
    "ports",
    "targetPort",
    "port",
    "host",
    "server",
    "services",
    "http",
    "paths",
    "path",
    "pathType",
    "backend",
    "service",
    "name",
    "app",
    "number",
    "tls",
    "termination",
    "to",
    "weight",
    "key",
    "nfs",
    "awsElasticBlockStore",
    "volumeID",
    "fsType",
    "local",
    "hostPath",
    "nodeAffinity",
    "required",
    "nodeSelectorTerms",
    "matchExpressions",
    "operator",
    "values",
}

_PDF_SHELL_COMMAND_RE = re.compile(
    r"^(?:"
    r"oc|kubectl|curl|wget|podman|docker|helm|cat|ls|grep|echo|sleep|"
    r"npm|npx|node|smee|git|gh|ssh|scp|tar|unzip|powershell|pwsh"
    r")(?:\s+\S*|$)",
    re.IGNORECASE,
)


def _is_pdf_repeated_header_or_footer(line: str, *, title: str) -> bool:
    candidate = _clean_pdf_line(line)
    if not candidate:
        return True
    if re.fullmatch(r"\d{1,3}", candidate):
        return True
    return _normalize_pdf_title_for_compare(candidate) == _normalize_pdf_title_for_compare(title)


def _is_pdf_heading_candidate(line: str) -> bool:
    candidate = _clean_pdf_line(line)
    heading_label = candidate.rstrip(":：")
    if not candidate or len(candidate) > 80:
        return False
    if re.fullmatch(r"(?i)page\s+\d+", candidate):
        return False
    if candidate.startswith(("#", "|", "!", "-", "*")):
        return False
    if re.match(r"^(?:Step\s*)?\d+[.)]\s+\S+", candidate, re.IGNORECASE):
        return True
    if re.match(r"^Step\s*\d+[.:]?\s+\S+", candidate, re.IGNORECASE):
        return True
    if re.search(r"[。.!?]$", candidate):
        return False
    if re.search(r"(다|요|니다|한다|된다|했다|있다|없다|한다\.)$", candidate):
        return False
    if "," in candidate or "，" in candidate or "、" in candidate:
        return False
    word_count = len(candidate.split())
    if word_count > 8:
        return False

    if heading_label in _KNOWN_KOREAN_PDF_SECTION_HEADINGS:
        return True
    if ":" in candidate and not re.search(r"\([A-Z0-9]{2,}\)", candidate):
        return False
    if re.search(r"\([A-Z0-9]{2,}\)", candidate):
        return True
    if re.fullmatch(r"[A-Z][A-Za-z0-9/ +._-]{1,40}\s*\([^)]+\)", candidate):
        return True
    if re.fullmatch(r"[A-Z][A-Za-z0-9/ +._-]{2,50}", candidate):
        return True
    if heading_label in _KNOWN_KOREAN_PDF_SECTION_HEADINGS:
        return True
    return False


def _pdf_language_label(line: str) -> str:
    stripped = str(line or "").strip()
    if not stripped:
        return ""
    return _PDF_LANGUAGE_LABELS.get(stripped.lower(), "")


def _is_pdf_code_line(line: str) -> bool:
    candidate = str(line or "").rstrip()
    stripped = candidate.strip()
    if not stripped:
        return False
    if candidate.startswith((" ", "\t")):
        return True
    if re.match(r"^#{1,6}\s+\S+", stripped):
        return True
    if stripped.startswith("$env:"):
        return True
    if _PDF_SHELL_COMMAND_RE.match(stripped):
        return True
    if stripped.startswith(("---", "-- [")):
        return True
    if re.match(r"^(?:Target API|Target URL|Auth Key|결과:|설명:)\b", stripped):
        return True
    if re.match(r"^[A-Z_][A-Z0-9_]*=", stripped):
        return True
    if re.match(r"^-+\s*[A-Za-z][A-Za-z0-9_.-]*:", stripped):
        return True
    key_match = re.match(r"^([A-Za-z][A-Za-z0-9_.-]*):(?:\s|$)", stripped)
    if key_match and key_match.group(1) in _PDF_YAML_KEYS:
        return True
    compact_key_match = re.match(r"^([A-Za-z][A-Za-z0-9_.-]*):\S+", stripped)
    if compact_key_match and compact_key_match.group(1) in _PDF_YAML_KEYS:
        return True
    if re.match(r"^[A-Z][A-Z0-9_]*:", stripped):
        return True
    return False


def _pdf_line_has_sentence_end(line: str) -> bool:
    stripped = str(line or "").rstrip()
    if not stripped:
        return False
    if stripped.endswith(("다.", "요.", "니다.", ".", "?", "!", "。", ")", "]", "}", '"', "'")):
        return True
    return False


def _pdf_code_line_looks_wrapped(previous: str, current: str) -> bool:
    prev = str(previous or "").rstrip()
    curr = str(current or "").strip()
    if not prev or not curr:
        return False
    if _pdf_language_label(curr) or _is_pdf_heading_candidate(curr):
        return False
    if re.match(r"^(?:[-*]|\d+[.)])\s+\S+", curr):
        return False
    if prev.endswith("\\"):
        return False
    if prev.count('"') % 2 == 1 or prev.count("'") % 2 == 1:
        return True
    if prev.count("(") > prev.count(")") or prev.count("[") > prev.count("]") or prev.count("{") > prev.count("}"):
        return True
    if re.search(r"(?:==|!=|&&|\|\||[-+*/=])\s*$", prev):
        return True
    if re.search(r"[A-Za-z가-힣_]+$", prev) and re.match(r'^[A-Za-z가-힣_"}).]', curr):
        return True
    return False


def _pdf_prose_line_looks_wrapped(previous: str, current: str) -> bool:
    prev = str(previous or "").rstrip()
    curr = str(current or "").strip()
    if not prev or not curr:
        return False
    if _pdf_line_has_sentence_end(prev):
        return False
    if _is_pdf_heading_candidate(prev):
        return False
    if _pdf_language_label(curr):
        return False
    if _is_pdf_heading_candidate(curr):
        return False
    if re.match(r"^(?:[-*]|\d+[.)])\s+\S+", curr):
        return False
    if re.match(r"^[가-힣A-Za-z0-9\"'(]", curr):
        return True
    return False


def _join_pdf_wrapped_line(previous: str, current: str) -> str:
    prev = str(previous or "").rstrip()
    curr = str(current or "").strip()
    if not prev:
        return curr
    if not curr:
        return prev
    if re.search(r"[가-힣]$", prev) and re.match(r"^(?:다|답|록|능|일|P|e)", curr):
        return f"{prev}{curr}"
    if re.search(r"(?:은|는|이|가|을|를|와|과|의|로|으로|에|에서|에게|보다|처럼)$", prev):
        return f"{prev} {curr}"
    if re.search(r"[A-Za-z0-9_]$", prev) and re.match(r"^[A-Za-z0-9_]", curr):
        return f"{prev}{curr}"
    if re.search(r"[가-힣]$", prev) and re.match(r"^[가-힣]", curr):
        return f"{prev}{curr}"
    return f"{prev} {curr}"


def _repair_pdf_wrapped_lines(lines: list[str]) -> list[str]:
    repaired: list[str] = []
    for raw_line in lines:
        line = str(raw_line or "").rstrip()
        if not line.strip():
            if repaired and repaired[-1] != "":
                repaired.append("")
            continue
        if not repaired:
            repaired.append(line)
            continue
        previous = repaired[-1]
        previous_is_code = _is_pdf_code_line(previous)
        current_is_code = _is_pdf_code_line(line)
        should_merge = False
        if previous_is_code and not current_is_code:
            should_merge = _pdf_code_line_looks_wrapped(previous, line)
        elif not previous_is_code and not current_is_code:
            should_merge = _pdf_prose_line_looks_wrapped(previous, line)
        if should_merge:
            repaired[-1] = _join_pdf_wrapped_line(previous, line)
        else:
            repaired.append(line)
    return repaired


def _split_pdf_code_and_prose(line: str) -> tuple[str, str]:
    candidate = str(line or "").rstrip()
    match = re.match(r"^(\s*[A-Za-z][A-Za-z0-9_.-]*:\s+\S+)\s+([가-힣].+)$", candidate)
    if not match:
        return candidate, ""
    prose = match.group(2).strip()
    if not re.search(r"(다|요|니다|한다|된다|했다|있다|없다|판단|할당)", prose):
        return candidate, ""
    return match.group(1).rstrip(), prose


def _pdf_code_language_for_line(line: str, pending_language: str = "") -> str:
    if pending_language:
        return pending_language
    stripped = str(line or "").strip()
    if re.search(r"\.(?:ya?ml)\b", stripped, re.IGNORECASE):
        return "yaml"
    if stripped.startswith("#"):
        return "bash"
    if stripped.startswith("$env:"):
        return "powershell"
    if _PDF_SHELL_COMMAND_RE.match(stripped):
        return "bash"
    if stripped.startswith("#") and re.search(r"\b(?:oc|kubectl|curl|podman|docker|helm)\b", stripped, re.IGNORECASE):
        return "bash"
    return "yaml"


def _pdf_line_looks_yaml_code(line: str) -> bool:
    stripped = str(line or "").strip()
    if not stripped or stripped.startswith("#"):
        return False
    if re.match(r"^-\s+\S+", stripped):
        return True
    key_match = re.match(r"^([A-Za-z][A-Za-z0-9_.-]*):(?:\s|$)", stripped)
    if key_match and key_match.group(1) in _PDF_YAML_KEYS:
        return True
    compact_key_match = re.match(r"^([A-Za-z][A-Za-z0-9_.-]*):\S+", stripped)
    return bool(compact_key_match and compact_key_match.group(1) in _PDF_YAML_KEYS)


def _serialize_pdf_layout_blocks(blocks: list[PdfLayoutBlock]) -> str:
    lines = [_PDF_LAYOUT_MARKER]
    for block in blocks:
        payload = {
            "kind": block.kind,
            "bbox": [round(value, 2) for value in block.bbox],
            "font_size": round(float(block.font_size or 0.0), 2),
            "language": block.language,
            "confidence": round(float(block.confidence or 0.0), 3),
            "reason": block.reason,
        }
        lines.append(f"<!-- pbs-layout-block {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))} -->")
        lines.extend(str(block.text or "").rstrip("\n").splitlines())
        lines.append(_PDF_LAYOUT_BLOCK_END)
    return "\n".join(lines).strip()


def _parse_pdf_layout_blocks_source(text: str) -> list[PdfLayoutBlock] | None:
    lines = str(text or "").splitlines()
    if not any(line.strip() == _PDF_LAYOUT_MARKER for line in lines[:3]):
        return None
    blocks: list[PdfLayoutBlock] = []
    index = 0
    while index < len(lines):
        start_match = _PDF_LAYOUT_BLOCK_START_RE.match(lines[index].strip())
        if start_match is None:
            index += 1
            continue
        try:
            payload = json.loads(start_match.group("payload"))
        except json.JSONDecodeError:
            index += 1
            continue
        body: list[str] = []
        index += 1
        while index < len(lines) and lines[index].strip() != _PDF_LAYOUT_BLOCK_END:
            body.append(lines[index].rstrip())
            index += 1
        raw_bbox = payload.get("bbox") if isinstance(payload, dict) else None
        bbox_values = raw_bbox if isinstance(raw_bbox, list) and len(raw_bbox) == 4 else [0, 0, 0, 0]
        kind = str(payload.get("kind") or "paragraph") if isinstance(payload, dict) else "paragraph"
        if kind not in {"heading", "paragraph", "table", "code"}:
            kind = "paragraph"
        blocks.append(
            PdfLayoutBlock(
                kind=kind,  # type: ignore[arg-type]
                text="\n".join(body).strip("\n"),
                bbox=tuple(float(value or 0) for value in bbox_values),  # type: ignore[arg-type]
                font_size=float(payload.get("font_size") or 0.0) if isinstance(payload, dict) else 0.0,
                language=str(payload.get("language") or "") if isinstance(payload, dict) else "",
                confidence=float(payload.get("confidence") or 0.0) if isinstance(payload, dict) else 0.0,
                reason=str(payload.get("reason") or "") if isinstance(payload, dict) else "",
            )
        )
        index += 1
    return blocks


def _pdf_noncode_lines_without_repeated(text: str, *, title: str) -> list[str]:
    cleaned: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.rstrip()
        if not _clean_pdf_line(line):
            if cleaned and cleaned[-1] != "":
                cleaned.append("")
            continue
        if _is_pdf_repeated_header_or_footer(line, title=title):
            continue
        cleaned.append(line)
    while cleaned and not cleaned[0].strip():
        cleaned.pop(0)
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()
    return cleaned


def _pdf_layout_blocks_to_markdown(blocks: list[PdfLayoutBlock], *, title: str, page_index: int) -> str:
    output: list[str] = []

    def append_blank() -> None:
        if output and output[-1] != "":
            output.append("")

    for block in blocks:
        text = str(block.text or "").strip("\n")
        if not text.strip():
            continue
        if block.kind == "table":
            append_blank()
            output.append(text.strip())
            output.append("")
            continue
        if block.kind == "code":
            code_lines = _repair_pdf_wrapped_lines([line.rstrip() for line in text.splitlines()])
            while code_lines and not code_lines[0].strip():
                code_lines.pop(0)
            while code_lines and not code_lines[-1].strip():
                code_lines.pop()
            if not code_lines:
                continue
            first_code_line = next((line for line in code_lines if line.strip()), "")
            language = block.language or _pdf_code_language_for_line(first_code_line)
            append_blank()
            output.append(f"```{language or 'text'}")
            output.extend(code_lines)
            output.append("```")
            output.append("")
            continue
        lines = _pdf_noncode_lines_without_repeated(text, title=title)
        if not lines:
            continue
        if block.kind == "heading":
            for line in lines:
                clean_line = _clean_pdf_line(line)
                if not clean_line:
                    continue
                if page_index == 1 and _normalize_pdf_title_for_compare(clean_line) == _normalize_pdf_title_for_compare(title):
                    continue
                append_blank()
                output.append(f"## {clean_line}")
                output.append("")
            continue
        repaired_lines = _repair_pdf_wrapped_lines(lines)
        paragraph_lines = [line for line in repaired_lines if line.strip()]
        if paragraph_lines:
            append_blank()
            output.extend(_clean_pdf_line(line) for line in paragraph_lines)
            output.append("")
    return "\n".join(output).strip()


def _pdf_page_text_to_markdown(text: str, *, title: str, page_index: int) -> str:
    layout_blocks = _parse_pdf_layout_blocks_source(text)
    if layout_blocks is not None:
        return _pdf_layout_blocks_to_markdown(layout_blocks, title=title, page_index=page_index)

    page_lines: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = str(raw_line or "").rstrip()
        if not _clean_pdf_line(line):
            page_lines.append("")
            continue
        if _is_pdf_repeated_header_or_footer(line, title=title):
            continue
        page_lines.append(line)
    if page_index == 1:
        joined = "\n".join(page_lines)
        page_lines = _drop_duplicate_pdf_title_line(joined, title).splitlines()
        page_lines = [
            line.rstrip()
            for line in page_lines
            if not _clean_pdf_line(line) or not _is_pdf_repeated_header_or_footer(line, title=title)
        ]
    page_lines = _repair_pdf_wrapped_lines(page_lines)

    output: list[str] = []
    previous_was_heading = False
    in_code = False
    pending_language = ""

    def close_code() -> None:
        nonlocal in_code
        if in_code:
            output.append("```")
            output.append("")
            in_code = False

    def next_nonempty_line(index: int) -> str:
        for candidate in page_lines[index + 1:]:
            if _clean_pdf_line(candidate):
                return candidate
        return ""

    for index, line in enumerate(page_lines):
        clean_line = _clean_pdf_line(line)
        if not clean_line:
            if in_code and _is_pdf_code_line(next_nonempty_line(index)):
                output.append("")
                continue
            close_code()
            if output and output[-1] != "":
                output.append("")
            previous_was_heading = False
            continue
        language_label = _pdf_language_label(clean_line)
        if language_label:
            close_code()
            if clean_line != clean_line.lower():
                if output and output[-1] != "":
                    output.append("")
                output.append(f"## {clean_line}")
                output.append("")
                previous_was_heading = True
            pending_language = language_label
            continue
        if _is_pdf_code_line(line):
            code_part, prose_part = _split_pdf_code_and_prose(line)
            if not in_code:
                if output and output[-1] != "":
                    output.append("")
                output.append(f"```{_pdf_code_language_for_line(code_part, pending_language)}")
                in_code = True
                pending_language = ""
            output.append(code_part.rstrip())
            if prose_part:
                close_code()
                output.append(prose_part)
            previous_was_heading = False
            continue
        close_code()
        if _is_pdf_heading_candidate(clean_line):
            if output and output[-1] != "":
                output.append("")
            output.append(f"## {clean_line}")
            output.append("")
            if clean_line.rstrip(":：") == "출력 예상 결과":
                pending_language = "text"
            previous_was_heading = True
            continue
        if previous_was_heading and output and output[-1] != "":
            output.append("")
        output.append(clean_line)
        previous_was_heading = False
    close_code()
    return "\n".join(output).strip()


def _pdf_pages_to_markdown(pages: list[str], stem: str, assets: tuple[DocumentAsset, ...] = ()) -> str:
    title = _pdf_title_from_pages(pages, stem)
    lines = [f"# {title}"]
    assets_by_page: dict[int, list[DocumentAsset]] = {}
    for asset in assets:
        if asset.page_number is None:
            continue
        assets_by_page.setdefault(int(asset.page_number), []).append(asset)
    for page_index, text in enumerate(pages, start=1):
        page_markdown = _pdf_page_text_to_markdown(text, title=title, page_index=page_index)
        if page_markdown:
            lines.extend(["", f"<!-- page: {page_index} -->", "", page_markdown])
        for asset in assets_by_page.get(page_index, []):
            lines.extend(["", _image_markdown(asset)])
    joined = "\n".join(lines).strip()
    return "" if joined == f"# {title}" else joined


def _pdf_rects_overlap(first: tuple[float, float, float, float], second: tuple[float, float, float, float]) -> bool:
    return not (first[2] <= second[0] or second[2] <= first[0] or first[3] <= second[1] or second[3] <= first[1])


def _normalize_pdf_table_cell(value: Any) -> str:
    text = " ".join(str(value or "").replace("\r", "\n").split())
    return text.strip()


def _markdown_escape_table_cell(value: Any) -> str:
    return _normalize_pdf_table_cell(value).replace("|", r"\|")


def _markdown_table_from_rows(rows: list[list[Any]]) -> str:
    normalized = [
        [_markdown_escape_table_cell(cell) for cell in row]
        for row in rows
        if any(_normalize_pdf_table_cell(cell) for cell in row)
    ]
    if len(normalized) < 2:
        return ""
    width = max(len(row) for row in normalized)
    padded = [row + [""] * (width - len(row)) for row in normalized]
    header = padded[0]
    separator = ["---"] * width
    body = padded[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


def _pdf_codeish_line_count(lines: list[str]) -> int:
    count = 0
    for line in lines:
        stripped = line.strip()
        if _is_pdf_code_line(line):
            count += 1
        elif stripped.startswith(("#", "---")):
            count += 1
        elif re.match(r"^[-]\s+\S+", stripped):
            count += 1
        elif re.match(r"^[A-Za-z][A-Za-z0-9_.-]*:\S+", stripped) and not re.match(r"^[a-z][a-z0-9+.-]*://", stripped, re.IGNORECASE):
            count += 1
    return count


def _pdf_text_block_looks_like_code(text: str) -> bool:
    lines = [line.rstrip() for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        return False

    codeish_count = _pdf_codeish_line_count(lines)
    return codeish_count > 0 and codeish_count >= max(1, len(lines) // 2)


def _pdf_layout_block_language(text: str) -> str:
    lines = [line for line in str(text or "").splitlines() if line.strip()]
    first_line = lines[0] if lines else ""
    if not first_line:
        return ""
    if any(str(line).strip().startswith("$env:") for line in lines):
        return "powershell"
    if any(_PDF_SHELL_COMMAND_RE.match(str(line).strip()) for line in lines):
        return "bash"
    if any(_pdf_line_looks_yaml_code(line) for line in lines):
        return "yaml"
    return _pdf_code_language_for_line(first_line)


def _pdf_classify_text_layout_block(
    *,
    text: str,
    bbox: tuple[float, float, float, float],
    font_size: float,
    median_font_size: float,
    font_names: list[str],
) -> PdfLayoutBlock:
    lines = [line.rstrip() for line in str(text or "").splitlines() if line.strip()]
    joined = _clean_pdf_line(" ".join(lines))
    mono_font = any(re.search(r"(?:mono|courier|consola|menlo|code)", font, re.IGNORECASE) for font in font_names)
    codeish_count = _pdf_codeish_line_count(lines)
    if lines and (
        _pdf_text_block_looks_like_code(text)
        or (mono_font and len(lines) >= 2)
        or (codeish_count > 0 and len(lines) >= 2 and bbox[0] >= 72)
    ):
        confidence = min(0.96, 0.62 + 0.16 * codeish_count + (0.12 if mono_font else 0.0))
        return PdfLayoutBlock(
            kind="code",
            text=text,
            bbox=bbox,
            font_size=font_size,
            language=_pdf_layout_block_language(text),
            confidence=confidence,
            reason="codeish_lines_or_monospace_region",
        )
    font_boost = median_font_size > 0 and font_size >= max(median_font_size + 1.2, median_font_size * 1.12)
    if joined and len(lines) <= 2 and _is_pdf_heading_candidate(joined):
        return PdfLayoutBlock(
            kind="heading",
            text=text,
            bbox=bbox,
            font_size=font_size,
            confidence=0.88 if font_boost else 0.76,
            reason="heading_candidate_with_layout",
        )
    if joined and len(lines) <= 2 and font_boost and len(joined) <= 80 and not _pdf_line_has_sentence_end(joined):
        return PdfLayoutBlock(
            kind="heading",
            text=text,
            bbox=bbox,
            font_size=font_size,
            confidence=0.72,
            reason="large_short_text",
        )
    return PdfLayoutBlock(
        kind="paragraph",
        text=text,
        bbox=bbox,
        font_size=font_size,
        confidence=0.7,
        reason="default_text_region",
    )


def _pdf_union_bbox(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    return (
        min(first[0], second[0]),
        min(first[1], second[1]),
        max(first[2], second[2]),
        max(first[3], second[3]),
    )


def _pdf_layout_blocks_should_merge_code(previous: PdfLayoutBlock, current: PdfLayoutBlock) -> bool:
    if previous.kind != "code" or current.kind != "code":
        return False
    if abs(previous.bbox[0] - current.bbox[0]) > 34:
        return False
    vertical_gap = float(current.bbox[1] - previous.bbox[3])
    return -3 <= vertical_gap <= 36


def _merge_pdf_layout_blocks(blocks: list[PdfLayoutBlock]) -> list[PdfLayoutBlock]:
    merged: list[PdfLayoutBlock] = []
    for block in blocks:
        if merged and _pdf_layout_blocks_should_merge_code(merged[-1], block):
            previous = merged[-1]
            vertical_gap = float(block.bbox[1] - previous.bbox[3])
            separator = "\n\n" if vertical_gap > 18 else "\n"
            merged[-1] = PdfLayoutBlock(
                kind="code",
                text=f"{previous.text.rstrip()}{separator}{block.text.lstrip()}",
                bbox=_pdf_union_bbox(previous.bbox, block.bbox),
                font_size=max(previous.font_size, block.font_size),
                language=_pdf_layout_block_language(f"{previous.text.rstrip()}{separator}{block.text.lstrip()}"),
                confidence=max(previous.confidence, block.confidence),
                reason=f"{previous.reason}+merged_layout_code",
            )
            continue
        merged.append(block)
    return merged


def _pdf_text_layout_blocks_with_pymupdf(
    page: Any,
    *,
    table_bboxes: list[tuple[float, float, float, float]],
) -> list[PdfLayoutBlock]:
    raw_blocks: list[dict[str, Any]] = []
    try:
        page_dict = page.get_text("dict")
        text_blocks = list(page_dict.get("blocks", []) or [])
    except Exception:  # noqa: BLE001
        text_blocks = []

    for block in text_blocks:
        if int(block.get("type", 0) or 0) != 0:
            continue
        raw_bbox = tuple(float(value) for value in block.get("bbox", ()) or ())
        if len(raw_bbox) != 4:
            continue
        bbox = raw_bbox  # type: ignore[assignment]
        if any(_pdf_rects_overlap(bbox, table_bbox) for table_bbox in table_bboxes):
            continue
        lines: list[str] = []
        font_sizes: list[float] = []
        font_names: list[str] = []
        for line in list(block.get("lines", []) or []):
            spans = list(line.get("spans", []) or [])
            text_line = "".join(str(span.get("text") or "") for span in spans).rstrip()
            if text_line.strip():
                lines.append(text_line)
            for span in spans:
                span_text = str(span.get("text") or "")
                if not span_text.strip():
                    continue
                font_sizes.append(float(span.get("size") or 0.0))
                font_names.append(str(span.get("font") or ""))
        text = "\n".join(lines).strip()
        if not text:
            continue
        raw_blocks.append(
            {
                "text": text,
                "bbox": bbox,
                "font_size": max(font_sizes) if font_sizes else 0.0,
                "font_names": font_names,
            }
        )

    if not raw_blocks:
        try:
            block_tuples = page.get_text("blocks")
        except Exception:  # noqa: BLE001
            block_tuples = []
        for block in block_tuples:
            if len(block) < 5:
                continue
            bbox = (float(block[0]), float(block[1]), float(block[2]), float(block[3]))
            if any(_pdf_rects_overlap(bbox, table_bbox) for table_bbox in table_bboxes):
                continue
            text = str(block[4] or "").strip()
            if not text:
                continue
            raw_blocks.append({"text": text, "bbox": bbox, "font_size": 0.0, "font_names": []})

    font_sizes = sorted(float(block.get("font_size") or 0.0) for block in raw_blocks if float(block.get("font_size") or 0.0) > 0)
    median_font_size = font_sizes[len(font_sizes) // 2] if font_sizes else 0.0
    return [
        _pdf_classify_text_layout_block(
            text=str(block["text"]),
            bbox=block["bbox"],
            font_size=float(block.get("font_size") or 0.0),
            median_font_size=median_font_size,
            font_names=list(block.get("font_names") or []),
        )
        for block in raw_blocks
    ]


def _extract_pdf_page_markdown_source_with_pymupdf(page: Any) -> str:
    blocks: list[PdfLayoutBlock] = []
    table_bboxes: list[tuple[float, float, float, float]] = []
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            tables = page.find_tables()
        table_items = list(getattr(tables, "tables", []) or [])
    except Exception:  # noqa: BLE001
        table_items = []
    for table in table_items:
        bbox_raw = tuple(float(value) for value in getattr(table, "bbox", ()) or ())
        if len(bbox_raw) != 4:
            continue
        try:
            markdown_table = _markdown_table_from_rows(table.extract())
        except Exception:  # noqa: BLE001
            markdown_table = ""
        if not markdown_table:
            continue
        table_bboxes.append(bbox_raw)  # type: ignore[arg-type]
        blocks.append(
            PdfLayoutBlock(
                kind="table",
                text=markdown_table,
                bbox=bbox_raw,  # type: ignore[arg-type]
                confidence=0.96,
                reason="pymupdf_table_detector",
            )
        )
    blocks.extend(_pdf_text_layout_blocks_with_pymupdf(page, table_bboxes=table_bboxes))
    blocks.sort(key=lambda block: (round(block.bbox[1], 1), round(block.bbox[0], 1)))
    return _serialize_pdf_layout_blocks(_merge_pdf_layout_blocks(blocks))


def _extract_pdf_pages_with_pymupdf(path: Path) -> list[str] | None:
    try:
        import fitz  # PyMuPDF
    except Exception:  # noqa: BLE001
        return None
    try:
        doc = fitz.open(str(path))
        try:
            return [_extract_pdf_page_markdown_source_with_pymupdf(page) for page in doc]
        finally:
            doc.close()
    except Exception:  # noqa: BLE001
        return None


def _extract_pdf_image_assets_with_pymupdf(path: Path, *, source_sha256: str) -> tuple[DocumentAsset, ...]:
    try:
        import fitz  # PyMuPDF
    except Exception:  # noqa: BLE001
        return ()
    assets: list[DocumentAsset] = []
    seen: set[tuple[int, int]] = set()
    try:
        doc = fitz.open(str(path))
        try:
            for page_number, page in enumerate(doc, start=1):
                for image_index, image_ref in enumerate(page.get_images(full=True), start=1):
                    xref = int(image_ref[0])
                    key = (page_number, xref)
                    if key in seen:
                        continue
                    seen.add(key)
                    image = doc.extract_image(xref)
                    content = bytes(image.get("image") or b"")
                    width = int(image.get("width") or 0)
                    height = int(image.get("height") or 0)
                    ext = str(image.get("ext") or "png").lower().lstrip(".") or "png"
                    if not content or width < 48 or height < 48:
                        continue
                    media_name = f"pdf-page-{page_number:03d}-image-{image_index:02d}.{ext}"
                    sha256 = hashlib.sha256(content).hexdigest()
                    asset_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{path.name}:{source_sha256}:pdf:{page_number}:{xref}:{sha256}"))
                    assets.append(
                        DocumentAsset(
                            asset_id=asset_id,
                            asset_type="image",
                            filename=media_name,
                            mime_type=mimetypes.guess_type(media_name)[0] or f"image/{ext}",
                            sha256=sha256,
                            storage_key=f"uploads/assets/{asset_id}.{ext}",
                            page_number=page_number,
                            metadata={
                                "source_member": f"pdf:xref:{xref}",
                                "pdf_xref": xref,
                                "pdf_image_index": image_index,
                                "width": width,
                                "height": height,
                            },
                        )
                    )
        finally:
            doc.close()
    except Exception:  # noqa: BLE001
        return ()
    return tuple(assets)


def _extract_pdf_pages_with_pdfplumber(path: Path) -> list[str] | None:
    try:
        import pdfplumber
    except Exception:  # noqa: BLE001
        return None
    try:
        with pdfplumber.open(str(path)) as pdf:
            return [str(page.extract_text() or "").strip() for page in pdf.pages]
    except Exception:  # noqa: BLE001
        return None


def _convert_pdf_to_markdown(
    path: Path,
    *,
    progress: Callable[[str, str, dict[str, Any]], None] | None = None,
) -> ConvertedMarkdown:
    """PDF → markdown 변환.

    한국어 PDF에서 폰트 매핑 깨짐 사례가 흔해서 — pymupdf(fitz)를 1차로 사용.
    추출기 우선순위 (한국어/영어 모두 안정적):
      1) pymupdf (fitz) — 한국어 폰트 매핑 가장 안정, 페이지·표 유지
      2) pdfplumber — pdfminer 기반, pymupdf 부재 시 차순위
      3) Docling — 영어/표 인식 강하지만 한국어 폰트 깨짐 잦음
      4) extract_pdf_pages 폴백 체인 (pypdf → mdls → string_scan → RapidOCR 스캔본)
      5) markitdown 최종 폴백

    progress(stage, status, detail) 콜백이 주어지면 각 시도/결과를 흘려보낸다.
    """

    def emit(status: str, **detail: Any) -> None:
        if progress is not None:
            progress("parse", status, detail)

    warnings: list[str] = []
    extractor_used = ""
    markdown = ""
    page_count = 0
    assets: tuple[DocumentAsset, ...] = _extract_pdf_image_assets_with_pymupdf(
        path,
        source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )

    # 1) pymupdf
    emit("info", note="pymupdf(fitz) 추출 시도 중 (한국어 폰트에 가장 안정)...")
    pages = _extract_pdf_pages_with_pymupdf(path)
    if pages:
        total = sum(len(p) for p in pages)
        if total >= 200:  # 최소 의미있는 분량
            markdown = _pdf_pages_to_markdown(pages, path.stem, assets=assets)
            if markdown:
                extractor_used = "pymupdf"
                page_count = len(pages)
                emit("info", note=f"pymupdf 성공: {len(pages)} 페이지, {len(markdown):,} 자, {len(assets)} images")
        else:
            warnings.append(f"pymupdf_low_quality:{total}_chars")
            emit("info", note=f"pymupdf 결과 부실 ({total} 자), pdfplumber로 폴백")
    else:
        warnings.append("pymupdf_unavailable_or_failed")
        emit("info", note="pymupdf 사용 불가/실패, pdfplumber 폴백")

    # 2) pdfplumber
    if not markdown:
        emit("info", note="pdfplumber 추출 시도 중...")
        pages = _extract_pdf_pages_with_pdfplumber(path)
        if pages:
            total = sum(len(p) for p in pages)
            if total >= 200:
                markdown = _pdf_pages_to_markdown(pages, path.stem, assets=assets)
                if markdown:
                    extractor_used = "pdfplumber"
                    page_count = len(pages)
                    emit("info", note=f"pdfplumber 성공: {len(pages)} 페이지, {len(markdown):,} 자, {len(assets)} images")
            else:
                warnings.append(f"pdfplumber_low_quality:{total}_chars")
                emit("info", note=f"pdfplumber 결과 부실 ({total} 자), Docling으로 폴백")
        else:
            warnings.append("pdfplumber_unavailable_or_failed")
            emit("info", note="pdfplumber 사용 불가/실패, Docling 폴백")

    # 3) Docling (영어/표 PDF 에 강함)
    if not markdown:
        try:
            from play_book_studio.intake.normalization.pdf import (
                extract_pdf_markdown_with_docling,
                extract_pdf_markdown_with_docling_ocr,
                extract_pdf_pages,
            )
        except Exception:  # noqa: BLE001
            extract_pdf_markdown_with_docling = None  # type: ignore[assignment]
            extract_pdf_markdown_with_docling_ocr = None  # type: ignore[assignment]
            extract_pdf_pages = None  # type: ignore[assignment]
            warnings.append("pdf_intake_pipeline_unavailable")

        if extract_pdf_markdown_with_docling is not None:
            emit("info", note="Docling 추출 시도 중 (영어/표 PDF)...")
            try:
                docling_md = extract_pdf_markdown_with_docling(path).strip()
                if docling_md:
                    markdown = docling_md
                    extractor_used = "docling"
                    emit("info", note=f"Docling 성공: {len(markdown):,} 자")
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"docling_failed:{type(exc).__name__}")
                emit("info", note=f"Docling 실패: {type(exc).__name__}, Docling+OCR 폴백")

        # 4) Docling + OCR (스캔본)
        if not markdown and extract_pdf_markdown_with_docling_ocr is not None:
            emit("info", note="Docling + 내장 OCR 시도 (스캔본 추정)...")
            try:
                docling_md = extract_pdf_markdown_with_docling_ocr(path).strip()
                if docling_md:
                    markdown = docling_md
                    extractor_used = "docling_ocr"
                    warnings.append("pdf_required_ocr")
                    emit("info", note=f"Docling OCR 성공: {len(markdown):,} 자 (스캔본)")
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"docling_ocr_failed:{type(exc).__name__}")
                emit("info", note=f"Docling OCR 실패: {type(exc).__name__}")

        # 5) extract_pdf_pages 폴백 체인
        if not markdown and extract_pdf_pages is not None:
            emit("info", note="extract_pdf_pages 폴백 (pypdf → mdls → string_scan → RapidOCR)...")
            try:
                pages = extract_pdf_pages(path)
                joined = _pdf_pages_to_markdown(pages, path.stem, assets=assets)
                if joined:
                    markdown = joined
                    extractor_used = "extract_pdf_pages_chain"
                    page_count = len(pages)
                    emit("info", note=f"폴백 체인 성공: {len(pages)} 페이지, {len(markdown):,} 자")
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"extract_pdf_pages_failed:{type(exc).__name__}")
                emit("info", note=f"폴백 체인 실패: {type(exc).__name__}")

    # 6) markitdown 최종 폴백
    if not markdown:
        emit("info", note="모든 PDF 추출기 실패, markitdown 최종 폴백 시도")
        return ConvertedMarkdown(
            markdown=_convert_with_markitdown(path),
            warnings=tuple(warnings + ["pdf_used_markitdown_fallback"]),
        )

    return ConvertedMarkdown(
        markdown=markdown,
        assets=assets,
        warnings=tuple(warnings),
        metadata={
            "pdf_extractor": extractor_used,
            "pdf_markdown_chars": len(markdown),
            "pdf_page_count": page_count,
            "pdf_image_count": len(assets),
        },
    )


def _convert_with_markitdown(path: Path) -> str:
    try:
        from play_book_studio.intake.normalization.markitdown_adapter import convert_with_markitdown
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("markdown converter is unavailable") from exc
    return convert_with_markitdown(path)


def _xml_text(element: ET.Element, *, text_tag: str) -> str:
    return " ".join(text.strip() for text in _xml_texts(element, text_tag=text_tag) if text.strip()).strip()


def _xml_texts(element: ET.Element, *, text_tag: str) -> list[str]:
    return [node.text or "" for node in element.iter() if node.tag == text_tag]


def _docx_table_to_markdown(table: ET.Element) -> str:
    rows: list[list[str]] = []
    for row in table.iter(_DOCX_ROW_TAG):
        cells = [_xml_text(cell, text_tag=_XML_TEXT_TAG) for cell in row.iter(_DOCX_CELL_TAG)]
        if any(cells):
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    header = normalized[0]
    separator = ["---"] * width
    body = normalized[1:] or [[""] * width]
    markdown_rows = [header, separator, *body]
    return "\n".join("| " + " | ".join(cell.replace("\n", " ") for cell in row) + " |" for row in markdown_rows)


def _pptx_table_to_markdown(table: ET.Element) -> str:
    rows: list[list[str]] = []
    for row in table.iter(_PPT_ROW_TAG):
        cells = [_xml_text(cell, text_tag=_PPT_TEXT_TAG) for cell in row.iter(_PPT_CELL_TAG)]
        if any(cells):
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    header = normalized[0]
    separator = ["---"] * width
    body = normalized[1:] or [[""] * width]
    return "\n".join("| " + " | ".join(cell.replace("\n", " ") for cell in row) + " |" for row in [header, separator, *body])


def _docx_heading_level(paragraph: ET.Element) -> int | None:
    props = paragraph.find(_DOCX_PARAGRAPH_PROPS_TAG)
    style = props.find(_DOCX_PARAGRAPH_STYLE_TAG) if props is not None else None
    if style is None:
        return None
    value = style.attrib.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val", "")
    match = re.search(r"heading\s*(\d+)|Heading\s*(\d+)", value, flags=re.IGNORECASE)
    if not match:
        return None
    level = int(match.group(1) or match.group(2))
    return max(1, min(level, 6))


def _pptx_slide_media_names(archive: zipfile.ZipFile, slide_name: str, slide_xml: bytes) -> tuple[str, ...]:
    rels_name = f"{Path(slide_name).parent.as_posix()}/_rels/{Path(slide_name).name}.rels"
    if rels_name not in archive.namelist():
        return tuple(sorted(name for name in archive.namelist() if name.startswith("ppt/media/")))
    try:
        rels_xml = archive.read(rels_name).decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return ()
    targets_by_id: dict[str, str] = {}
    try:
        rels_root = ET.fromstring(rels_xml)
        relationships = [node for node in rels_root.iter() if node.tag.endswith("Relationship")]
    except ET.ParseError:
        relationships = []
    for relationship in relationships:
        rel_id = str(relationship.attrib.get("Id") or "").strip()
        target = str(relationship.attrib.get("Target") or "").strip()
        if not rel_id or not target:
            continue
        target_path = _resolve_pptx_relationship_target(slide_name, target)
        if target_path.startswith("ppt/media/"):
            targets_by_id[rel_id] = target_path
    embedded_ids = _DRAWING_EMBED_RE.findall(slide_xml.decode("utf-8", errors="ignore"))
    return tuple(dict.fromkeys(targets_by_id[rel_id] for rel_id in embedded_ids if rel_id in targets_by_id))


def _resolve_pptx_relationship_target(slide_name: str, target: str) -> str:
    if target.startswith("/"):
        return target.strip("/")
    base = Path(slide_name).parent
    parts: list[str] = []
    for part in (base / target).as_posix().split("/"):
        if part == "..":
            if parts:
                parts.pop()
            continue
        if part == "." or not part:
            continue
        parts.append(part)
    return "/".join(parts)


def _blob_asset(
    path: Path,
    *,
    media_name: str,
    content: bytes,
    source_sha256: str,
    page_number: int | None = None,
) -> DocumentAsset:
    sha256 = hashlib.sha256(content).hexdigest()
    filename = Path(media_name).name
    asset_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{path.name}:{source_sha256}:{media_name}:{sha256}:{page_number or 0}"))
    mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return DocumentAsset(
        asset_id=asset_id,
        asset_type="image",
        filename=filename,
        mime_type=mime_type,
        sha256=sha256,
        storage_key=f"uploads/assets/{asset_id}{Path(filename).suffix.lower()}",
        page_number=page_number,
        metadata={"source_member": media_name},
    )


def _last_section_block(blocks: list[DocumentBlock]) -> DocumentBlock | None:
    for block in reversed(blocks):
        if block.section_path:
            return block
    return None


def _split_section_number_title(title: str) -> tuple[str, str]:
    match = _SECTION_NUMBER_RE.match(title)
    if not match:
        return "", title.strip()
    number = match.group(1).strip().rstrip(".")
    heading = match.group(2).strip()
    return number, heading or title.strip()


def _toc_label(section_number: str, heading_title: str) -> str:
    if section_number:
        return f"{section_number} {heading_title}".strip()
    return heading_title.strip()


def _source_anchor(*, section_path: list[str], section_number: str) -> str:
    basis = "-".join([section_number, *section_path]).strip("-") or "section"
    normalized = re.sub(r"[^0-9A-Za-z가-힣._-]+", "-", basis).strip("-").lower()
    return normalized or "section"


def _natural_key(value: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", value)]


__all__ = [
    "DocumentAsset",
    "DocumentBlock",
    "DocumentChunk",
    "DocumentFormat",
    "ConvertedMarkdown",
    "ParsedUploadDocument",
    "build_document_chunks",
    "detect_document_format",
    "parse_upload_document",
]
