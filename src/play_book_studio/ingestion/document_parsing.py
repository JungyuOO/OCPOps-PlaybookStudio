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


MARKDOWN_FORMATS = {"md", "asciidoc"}
TEXT_FORMATS = {"txt"}
CONVERTER_FORMATS = {"pdf", "docx", "pptx", "xlsx", "hwp", "hwpx", "hwpml"}
IMAGE_FORMATS = {"image"}


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
    asset_ids: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["section_path"] = list(self.section_path)
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
    asset_ids: tuple[str, ...] = field(default_factory=tuple)
    block_ordinals: tuple[int, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["section_path"] = list(self.section_path)
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
_XML_TEXT_TAG = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
_DOCX_PARAGRAPH_TAG = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"
_DOCX_TABLE_TAG = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tbl"
_DOCX_ROW_TAG = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tr"
_DOCX_CELL_TAG = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tc"
_PPT_TEXT_TAG = "{http://schemas.openxmlformats.org/drawingml/2006/main}t"


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

    if document_format in MARKDOWN_FORMATS | TEXT_FORMATS:
        markdown = path.read_text(encoding="utf-8-sig").strip()
        if document_format == "txt":
            markdown = _plain_text_to_markdown(markdown, title=path.stem)
    elif document_format in IMAGE_FORMATS:
        asset = _image_asset(path, sha256=sha256, mime_type=mime_type)
        description = image_describer(path, asset) if image_describer else ""
        if description:
            asset = DocumentAsset(**{**asset.to_dict(), "description": description})
        assets.append(asset)
        markdown = _image_markdown(asset)
    elif document_format in CONVERTER_FORMATS:
        if markdown_converter is None:
            markdown_converter = _default_markdown_converter
        converted = markdown_converter(path, document_format)
        if isinstance(converted, ConvertedMarkdown):
            markdown = converted.markdown.strip()
            assets.extend(converted.assets)
            warnings.extend(converted.warnings)
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

    blocks = tuple(_markdown_to_blocks(markdown, assets=tuple(assets)))
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
    max_chars: int = 1800,
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
        section_path = _last_section_path(current)
        asset_ids = tuple(dict.fromkeys(asset_id for block in current for asset_id in block.asset_ids))
        block_ordinals = tuple(block.ordinal for block in current)
        chunk_key = f"{parsed.document_id}:{ordinal}"
        chunks.append(
            DocumentChunk(
                chunk_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{chunk_key}:{markdown}")),
                chunk_key=chunk_key,
                ordinal=ordinal,
                markdown=markdown,
                embedding_text=_strip_markdown(markdown),
                section_path=section_path,
                asset_ids=asset_ids,
                block_ordinals=block_ordinals,
                metadata={
                    "filename": parsed.filename,
                    "document_format": parsed.document_format,
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
    description = image_describer(path, asset).strip()
    if not description:
        return asset
    return DocumentAsset(**{**asset.to_dict(), "description": description})


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


def _markdown_to_blocks(markdown: str, *, assets: tuple[DocumentAsset, ...]) -> list[DocumentBlock]:
    blocks: list[DocumentBlock] = []
    current_lines: list[str] = []
    section_path: list[str] = []
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
                block_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{ordinal}:{markdown_text}")),
                ordinal=ordinal,
                block_type=block_type,
                markdown=markdown_text,
                text=_strip_markdown(markdown_text),
                heading_level=heading_level,
                section_path=tuple(section_path),
                asset_ids=block_asset_ids,
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
            title = heading_match.group(2).strip()
            section_path = section_path[: max(0, level - 1)]
            section_path.append(title)
            append_block("heading", [line], heading_level=level)
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
    if document_format in {"hwp", "hwpx", "hwpml"}:
        raise RuntimeError(
            f"{document_format} parsing needs an internal HWP/HWPX adapter before runtime ingestion"
        )
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
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        slide_names = sorted(
            (name for name in names if re.match(r"ppt/slides/slide\d+\.xml$", name)),
            key=_natural_key,
        )
        media_names = sorted(name for name in names if name.startswith("ppt/media/"))
        for slide_index, slide_name in enumerate(slide_names, start=1):
            slide_root = ET.fromstring(archive.read(slide_name))
            texts = [text for text in _xml_texts(slide_root, text_tag=_PPT_TEXT_TAG) if text.strip()]
            lines.extend(["", f"## Slide {slide_index}"])
            for text in texts:
                lines.append(text.strip())
        for media_name in media_names:
            content = archive.read(media_name)
            asset = _blob_asset(path, media_name=media_name, content=content)
            assets.append(asset)
            lines.extend(["", _image_markdown(asset)])
    markdown = "\n".join(lines).strip()
    if len(lines) <= 1 and not assets:
        raise ValueError(f"PPTX produced empty markdown: {path.name}")
    return ConvertedMarkdown(markdown=markdown, assets=tuple(assets))


def _convert_pdf_to_markdown(path: Path) -> ConvertedMarkdown:
    try:
        from pypdf import PdfReader
    except Exception:  # noqa: BLE001
        return ConvertedMarkdown(
            markdown=_convert_with_markitdown(path),
            warnings=("pdf_used_markitdown_fallback",),
        )

    reader = PdfReader(str(path))
    lines = [f"# {path.stem}"]
    for page_index, page in enumerate(reader.pages, start=1):
        text = str(page.extract_text() or "").strip()
        if text:
            lines.extend(["", f"## Page {page_index}", "", text])
    markdown = "\n".join(lines).strip()
    if markdown == f"# {path.stem}":
        return ConvertedMarkdown(
            markdown=_convert_with_markitdown(path),
            warnings=("pdf_used_markitdown_fallback",),
        )
    return ConvertedMarkdown(markdown=markdown)


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


def _blob_asset(path: Path, *, media_name: str, content: bytes) -> DocumentAsset:
    sha256 = hashlib.sha256(content).hexdigest()
    filename = Path(media_name).name
    asset_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{path.name}:{media_name}:{sha256}"))
    mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return DocumentAsset(
        asset_id=asset_id,
        asset_type="image",
        filename=filename,
        mime_type=mime_type,
        sha256=sha256,
        storage_key=f"uploads/assets/{asset_id}{Path(filename).suffix.lower()}",
        metadata={"source_member": media_name},
    )


def _last_section_path(blocks: list[DocumentBlock]) -> tuple[str, ...]:
    for block in reversed(blocks):
        if block.section_path:
            return block.section_path
    return ()


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
