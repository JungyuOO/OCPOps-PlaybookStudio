"""Internal document parsing boundary for upload ingestion.

This module intentionally models the Kordoc-style contract inside the Python
ingestion layer: detect the document format, produce Markdown, keep structured
blocks, and surface image assets separately so a vision model can describe them.
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
import uuid
import zipfile
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

from .metadata_spine import build_chunk_metadata_spine


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
    content: bytes = field(default=b"", repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("content", None)
        return payload


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
) -> ParsedUploadDocument:
    path = path.resolve()
    content = path.read_bytes()
    document_format = detect_document_format(path)
    sha256 = hashlib.sha256(content).hexdigest()
    mime_type = _detect_mime_type(path, document_format)
    document_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{path.name}:{sha256}"))

    warnings: list[str] = []
    assets: list[DocumentAsset] = []
    converter_metadata: dict[str, Any] = {}

    if document_format in MARKDOWN_FORMATS | TEXT_FORMATS:
        markdown = path.read_text(encoding="utf-8-sig").strip()
        if document_format == "txt":
            markdown = _plain_text_to_markdown(markdown, title=path.stem)
    elif document_format in IMAGE_FORMATS:
        asset = _image_asset(path, sha256=sha256, mime_type=mime_type)
        if image_describer:
            asset = _describe_asset(path, asset, image_describer=image_describer)
        assets.append(asset)
        markdown = _image_markdown(asset)
    elif document_format in UNSUPPORTED_UPLOAD_FORMATS:
        raise ValueError(
            f"{document_format} uploads are intentionally unsupported for this service. "
            "Use PDF, DOCX, PPTX, XLSX, text, Markdown, or image inputs."
        )
    elif document_format in CONVERTER_FORMATS:
        if markdown_converter is None:
            markdown_converter = _default_markdown_converter
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
            assets = [
                _describe_asset(path, asset, image_describer=image_describer)
                for asset in assets
            ]
            markdown = _append_asset_descriptions(markdown, assets)
    else:
        raise ValueError(f"unsupported document format for ingestion: {path.name}")

    blocks = tuple(_markdown_to_blocks(markdown, assets=tuple(assets), document_id=document_id))
    if not blocks:
        warnings.append("no_blocks_detected")

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


def rebuild_parsed_document_from_markdown(
    parsed: ParsedUploadDocument,
    markdown: str,
    *,
    metadata: dict[str, Any] | None = None,
    warnings: tuple[str, ...] | None = None,
) -> ParsedUploadDocument:
    """Rebuild blocks for an existing parsed document while preserving assets."""

    next_markdown = str(markdown or "")
    next_metadata = {**dict(parsed.metadata), **dict(metadata or {})}
    next_warnings = warnings if warnings is not None else parsed.warnings
    blocks = tuple(
        _markdown_to_blocks(
            next_markdown,
            assets=parsed.assets,
            document_id=parsed.document_id,
        )
    )
    return replace(
        parsed,
        markdown=next_markdown,
        blocks=blocks,
        warnings=tuple(next_warnings),
        metadata=next_metadata,
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
        embedding_text = (
            f"{section_context}\n\n{stripped_markdown}"
            if section_context and section_context not in stripped_markdown
            else stripped_markdown
        )
        block_kinds = tuple(dict.fromkeys(block.block_type for block in current if block.block_type))
        metadata = {
            "filename": parsed.filename,
            "document_format": parsed.document_format,
            "page_start": min(page_numbers) if page_numbers else None,
            "page_end": max(page_numbers) if page_numbers else None,
            "chunk_char_count": len(markdown),
            "block_count": len(current),
        }
        metadata.update(
            build_chunk_metadata_spine(
                embedding_text,
                section_path=section_path,
                filename=parsed.filename,
                source_scope=str(parsed.metadata.get("source_scope") or "user_upload"),
                block_kinds=block_kinds,
                existing_metadata=metadata,
            )
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
                metadata=metadata,
            )
        )
        ordinal += 1
        if overlap_blocks <= 0:
            current = []
        else:
            current = current[-overlap_blocks:]
        current_chars = sum(len(block.markdown) for block in current)

    def is_page_heading_only(block: DocumentBlock) -> bool:
        if block.block_type != "heading":
            return False
        return bool(re.match(r"^Page\s+\d+$", str(block.heading_title or block.text or "").strip(), re.I))

    for block in parsed.blocks:
        if block.block_type == "heading":
            flush()
            current = [block]
            current_chars = len(block.markdown)
            continue
        block_chars = len(block.markdown)
        if current and current_chars + block_chars > max_chars and not (
            len(current) == 1 and is_page_heading_only(current[0])
        ):
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
        content=path.read_bytes(),
    )


def _image_markdown(asset: DocumentAsset) -> str:
    description = asset.description.strip()
    if description:
        return f"![{asset.filename}](asset://{asset.asset_id})\n\n{description}"
    return f"![{asset.filename}](asset://{asset.asset_id})"


def _describe_asset(path: Path, asset: DocumentAsset, *, image_describer: ImageDescriber) -> DocumentAsset:
    qwen_model = str(getattr(image_describer, "qwen_model", "") or "").strip()
    try:
        description = image_describer(path, asset).strip()
    except Exception as exc:  # noqa: BLE001
        metadata = {**dict(asset.metadata), "qwen_error": str(exc), "qwen_status": "failed"}
        if qwen_model:
            metadata.setdefault("qwen_model", qwen_model)
        return replace(asset, metadata=metadata)
    if not description:
        metadata = {**dict(asset.metadata), "qwen_status": "empty"}
        if qwen_model:
            metadata.setdefault("qwen_model", qwen_model)
        return replace(asset, metadata=metadata)
    metadata = {**dict(asset.metadata)}
    metadata.setdefault("qwen_status", "described")
    if qwen_model:
        metadata.setdefault("qwen_model", qwen_model)
    return replace(asset, description=description, metadata=metadata)


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


def _convert_pdf_to_markdown(path: Path) -> ConvertedMarkdown:
    source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    pdf_assets, pdf_asset_warnings = _extract_pdf_image_assets(path, source_sha256=source_sha256)
    assets_by_page: dict[int, list[DocumentAsset]] = {}
    for asset in pdf_assets:
        assets_by_page.setdefault(int(asset.page_number or 0), []).append(asset)
    page_texts, text_warnings, text_metadata = _extract_pdf_page_texts(path)
    lines = [f"# {path.stem}"]
    for page_index, text in enumerate(page_texts, start=1):
        page_assets = assets_by_page.get(page_index, [])
        if text:
            lines.extend(["", f"<!-- page: {page_index} -->", f"## Page {page_index}", "", text])
        elif page_assets:
            lines.extend(["", f"<!-- page: {page_index} -->", f"## Page {page_index}"])
        for asset in page_assets:
            lines.extend(["", _image_markdown(asset)])
    markdown = "\n".join(lines).strip()
    if markdown == f"# {path.stem}":
        converted = _convert_with_markitdown(path)
        if pdf_assets:
            converted = _append_pdf_assets_to_markdown(converted, pdf_assets)
        return ConvertedMarkdown(
            markdown=converted,
            assets=tuple(pdf_assets),
            warnings=("pdf_used_markitdown_fallback", *text_warnings, *pdf_asset_warnings),
            metadata={"pdf_image_count": len(pdf_assets), **text_metadata},
        )
    return ConvertedMarkdown(
        markdown=markdown,
        assets=tuple(pdf_assets),
        warnings=(*text_warnings, *pdf_asset_warnings),
        metadata={"pdf_image_count": len(pdf_assets), **text_metadata},
    )


def _extract_pdf_page_texts(path: Path) -> tuple[list[str], tuple[str, ...], dict[str, Any]]:
    """Extract PDF text with the least destructive local extractor available."""

    warnings: list[str] = []
    try:
        import fitz  # type: ignore[import-untyped]
    except Exception:  # noqa: BLE001
        fitz = None  # type: ignore[assignment]
    if fitz is not None:
        try:
            document = fitz.open(str(path))
            try:
                pages = [
                    _normalize_pdf_page_text(str(document.load_page(index).get_text("text") or ""))
                    for index in range(len(document))
                ]
                if any(text.strip() for text in pages):
                    return (
                        pages,
                        tuple(warnings),
                        {"page_count": len(document), "pdf_text_extractor": "pymupdf"},
                    )
                warnings.append("pdf_text_pymupdf_empty")
            finally:
                document.close()
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"pdf_text_pymupdf_failed:{exc}")

    try:
        from pypdf import PdfReader
    except Exception as exc:  # noqa: BLE001
        return [], (*warnings, f"pdf_text_pypdf_unavailable:{exc}"), {"pdf_text_extractor": "none"}

    try:
        reader = PdfReader(str(path))
        pages = [_normalize_pdf_page_text(str(page.extract_text() or "")) for page in reader.pages]
    except Exception as exc:  # noqa: BLE001
        return [], (*warnings, f"pdf_text_pypdf_failed:{exc}"), {"pdf_text_extractor": "none"}
    return (
        pages,
        (*warnings, "pdf_text_used_pypdf_fallback") if warnings else ("pdf_text_used_pypdf",),
        {"page_count": len(reader.pages), "pdf_text_extractor": "pypdf"},
    )


def _normalize_pdf_page_text(text: str) -> str:
    return str(text or "").replace("\x00", "").strip()


def _append_pdf_assets_to_markdown(markdown: str, assets: tuple[DocumentAsset, ...]) -> str:
    if not assets:
        return markdown
    lines = [markdown.strip(), "", "## 원본 이미지"]
    for asset in assets:
        page_label = f"page {asset.page_number}" if asset.page_number else "pdf"
        lines.extend(["", f"<!-- {page_label} -->", _image_markdown(asset)])
    return "\n".join(part for part in lines if part is not None).strip()


def _extract_pdf_image_assets(path: Path, *, source_sha256: str) -> tuple[tuple[DocumentAsset, ...], tuple[str, ...]]:
    try:
        import fitz  # type: ignore[import-untyped]
    except Exception:  # noqa: BLE001
        rendered, render_warnings = _render_pdf_pages_as_image_assets(path, source_sha256=source_sha256)
        return rendered, ("pdf_image_extraction_unavailable", *render_warnings)

    assets: list[DocumentAsset] = []
    warnings: list[str] = []
    try:
        document = fitz.open(str(path))
    except Exception as exc:  # noqa: BLE001
        rendered, render_warnings = _render_pdf_pages_as_image_assets(path, source_sha256=source_sha256)
        return rendered, (f"pdf_image_extraction_failed:{exc}", *render_warnings)
    try:
        seen: set[tuple[int, int, str]] = set()
        for page_index in range(len(document)):
            page_number = page_index + 1
            page = document.load_page(page_index)
            for image_index, image in enumerate(page.get_images(full=True), start=1):
                xref = int(image[0])
                try:
                    extracted = document.extract_image(xref)
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"pdf_image_extract_failed:page={page_number}:xref={xref}:{exc}")
                    continue
                content = bytes(extracted.get("image") or b"")
                if not content:
                    continue
                sha256 = hashlib.sha256(content).hexdigest()
                key = (page_number, xref, sha256)
                if key in seen:
                    continue
                seen.add(key)
                ext = str(extracted.get("ext") or "png").strip().lstrip(".").lower() or "png"
                if ext == "jpeg":
                    ext = "jpg"
                filename = f"page-{page_number:03d}-image-{image_index:02d}.{ext}"
                asset = _blob_asset(
                    path,
                    media_name=f"pdf/{filename}",
                    content=content,
                    source_sha256=source_sha256,
                    page_number=page_number,
                )
                assets.append(
                    replace(
                        asset,
                        filename=filename,
                        metadata={
                            **dict(asset.metadata),
                            "source_member": f"pdf:xref:{xref}",
                            "pdf_xref": xref,
                            "image_index": image_index,
                            "width": int(extracted.get("width") or image[2] or 0),
                            "height": int(extracted.get("height") or image[3] or 0),
                        },
                    )
                )
    finally:
        document.close()
    return tuple(assets), tuple(warnings)


def _render_pdf_pages_as_image_assets(path: Path, *, source_sha256: str) -> tuple[tuple[DocumentAsset, ...], tuple[str, ...]]:
    try:
        import pypdfium2 as pdfium  # type: ignore[import-untyped]
    except Exception:  # noqa: BLE001
        return (), ("pdf_page_render_fallback_unavailable",)

    assets: list[DocumentAsset] = []
    warnings: list[str] = ["pdf_page_render_fallback_used"]
    try:
        document = pdfium.PdfDocument(str(path))
    except Exception as exc:  # noqa: BLE001
        return (), (f"pdf_page_render_fallback_failed:{exc}",)
    try:
        for page_index in range(len(document)):
            page_number = page_index + 1
            page = None
            bitmap = None
            try:
                page = document[page_index]
                bitmap = page.render(scale=1.5)
                image = bitmap.to_pil()
                buffer = BytesIO()
                image.save(buffer, format="PNG")
                content = buffer.getvalue()
                filename = f"page-{page_number:03d}.png"
                asset = _blob_asset(
                    path,
                    media_name=f"pdf/rendered/{filename}",
                    content=content,
                    source_sha256=source_sha256,
                    page_number=page_number,
                )
                assets.append(
                    replace(
                        asset,
                        filename=filename,
                        metadata={
                            **dict(asset.metadata),
                            "source_member": f"pdf:rendered:page:{page_number}",
                            "pdf_rendered_page": True,
                            "width": int(image.size[0] or 0),
                            "height": int(image.size[1] or 0),
                        },
                    )
                )
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"pdf_page_render_failed:page={page_number}:{exc}")
            finally:
                for closable_name in ("bitmap", "page"):
                    closable = locals().get(closable_name)
                    close = getattr(closable, "close", None)
                    if callable(close):
                        try:
                            close()
                        except Exception:  # noqa: BLE001
                            pass
    finally:
        close = getattr(document, "close", None)
        if callable(close):
            close()
    return tuple(assets), tuple(warnings)


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
        content=content,
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
    "rebuild_parsed_document_from_markdown",
]
