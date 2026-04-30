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


MarkdownConverter = Callable[[Path, DocumentFormat], str]
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
        markdown = markdown_converter(path, document_format).strip()
        if not markdown:
            raise ValueError(f"markdown converter produced empty output for {path.name}")
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


def _default_markdown_converter(path: Path, document_format: DocumentFormat) -> str:
    try:
        from play_book_studio.intake.normalization.markitdown_adapter import convert_with_markitdown
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("markdown converter is unavailable") from exc

    if document_format in {"hwp", "hwpx", "hwpml"}:
        raise RuntimeError(
            f"{document_format} parsing needs an internal HWP/HWPX adapter before runtime ingestion"
        )
    return convert_with_markitdown(path)


__all__ = [
    "DocumentAsset",
    "DocumentBlock",
    "DocumentFormat",
    "ParsedUploadDocument",
    "detect_document_format",
    "parse_upload_document",
]
