"""Import existing official gold retrieval chunks into PostgreSQL."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from play_book_studio.config.corpus_paths import OFFICIAL_GOLD_CHUNKS_PATH
from play_book_studio.db.document_repository import (
    _fetch_id,
    _json,
    _upsert_repository,
    _upsert_tenant,
    _upsert_workspace,
)
from play_book_studio.ingestion.learning_metadata import (
    CATEGORY_LABELS,
    build_chunk_learning_metadata,
    build_learning_book_index,
    infer_category_key,
)
from play_book_studio.ingestion.internal_markup import render_internal_markup_for_retrieval
from play_book_studio.ingestion.chunk_question_candidates import build_chunk_question_candidates

_SECTION_NUMBER_RE = re.compile(r"^\s*((?:\d+\.)+\d+|\d+)(?:[.)]|\.?)\s+(.+?)\s*$")
OFFICIAL_EMBEDDING_CHUNKS_VERSION = "official_embedding_chunks_v1"
OFFICIAL_TEXT_LAYERS_VERSION = "official_text_layers_v1"

_EMBEDDING_CODE_BLOCK_RE = re.compile(
    r"\[CODE[^\]]*\]\s*(?P<body>.*?)\s*\[/CODE\]",
    re.DOTALL | re.IGNORECASE,
)
_EMBEDDING_TABLE_BLOCK_RE = re.compile(
    r"\[TABLE[^\]]*\]\s*(?P<body>.*?)\s*\[/TABLE\]",
    re.DOTALL | re.IGNORECASE,
)
_EMBEDDING_MARKER_RE = re.compile(r"\[/?(?:CODE|TABLE)[^\]]*\]", re.IGNORECASE)
_EMBEDDING_DANGLING_MARKER_RE = re.compile(r"\[/?(?:CODE|TABLE)[^\]]*$", re.IGNORECASE)
_EMBEDDING_ORPHAN_CLOSE_MARKER_RE = re.compile(r"(?<!\[)/(?:CODE|TABLE)\]", re.IGNORECASE)
_EMBEDDING_HTML_ANCHOR_RE = re.compile(r"</?a\b[^>]*>", re.IGNORECASE)
_EMBEDDING_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((?:https?://|/docs/)[^)]+\)")
_EMBEDDING_DOCS_URL_RE = re.compile(r"https?://docs\.redhat\.com/\S+|/docs/ocp/\S+", re.IGNORECASE)


def _official_gold_storage_key(source_key: str = "") -> str:
    base = OFFICIAL_GOLD_CHUNKS_PATH.as_posix()
    suffix = str(source_key or "").strip()
    return f"{base}#{suffix}" if suffix else base


@dataclass(frozen=True, slots=True)
class OfficialGoldImportSummary:
    chunks_path: str
    source_count: int
    chunk_count: int
    imported_chunk_count: int
    repository_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunks_path": self.chunks_path,
            "source_count": self.source_count,
            "chunk_count": self.chunk_count,
            "imported_chunk_count": self.imported_chunk_count,
            "repository_id": self.repository_id,
        }


def build_official_gold_import_plan(chunks_path: Path, *, limit: int = 0) -> dict[str, Any]:
    rows = _load_gold_chunk_rows(chunks_path, limit=limit)
    grouped = _group_rows_by_source(rows)
    learning_by_book = _learning_by_book_slug(grouped)
    return {
        "chunks_path": str(chunks_path.resolve()),
        "source_count": len(grouped),
        "chunk_count": len(rows),
        "repository_slug": "official-docs",
        "repository_kind": "official",
        "visibility": "global_shared",
        "source_scope": "official_docs",
        "sources": [
            {
                "source_key": source_key,
                "book_slug": str(source_rows[0].get("book_slug") or source_key),
                "title": _source_title(source_rows),
                "category_key": str(
                    (learning_by_book.get(str(source_rows[0].get("book_slug") or source_key)) or {}).get("category_key")
                    or infer_category_key(str(source_rows[0].get("book_slug") or source_key))
                ),
                "next_refs": list(
                    (
                        (learning_by_book.get(str(source_rows[0].get("book_slug") or source_key)) or {})
                        .get("learning")
                        or {}
                    ).get("next_refs")
                    or []
                ),
                "chunk_count": len(source_rows),
            }
            for source_key, source_rows in sorted(grouped.items())
        ],
    }


def import_official_gold_chunks(
    connection,
    *,
    chunks_path: Path,
    tenant_slug: str = "public",
    tenant_name: str = "Public",
    workspace_slug: str = "default",
    workspace_name: str = "Default",
    limit: int = 0,
) -> OfficialGoldImportSummary:
    rows = _load_gold_chunk_rows(chunks_path, limit=limit)
    grouped = _group_rows_by_source(rows)
    learning_by_book = _learning_by_book_slug(grouped)
    imported_chunk_count = 0
    repository_id = ""

    with connection.transaction():
        with connection.cursor() as cursor:
            tenant_id = _upsert_tenant(cursor, tenant_slug=tenant_slug, tenant_name=tenant_name)
            workspace_id = _upsert_workspace(
                cursor,
                tenant_id=tenant_id,
                workspace_slug=workspace_slug,
                workspace_name=workspace_name,
            )
            repository_id = _upsert_repository(
                cursor,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                owner_user_id="",
                slug="official-docs",
                title="Official Docs",
                repository_kind="official",
                visibility="global_shared",
            )
            for source_key, source_rows in grouped.items():
                source_id = _upsert_official_document_source(
                    cursor,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    repository_id=repository_id,
                    source_key=source_key,
                    rows=source_rows,
                    chunks_path=chunks_path,
                    learning_by_book=learning_by_book,
                )
                version_id = _upsert_official_document_version(
                    cursor,
                    source_id=source_id,
                    source_key=source_key,
                    chunks_path=chunks_path,
                )
                parse_job_id = _upsert_official_parse_job(
                    cursor,
                    source_id=source_id,
                    version_id=version_id,
                    source_key=source_key,
                )
                parsed_document_id = _upsert_official_parsed_document(
                    cursor,
                    source_id=source_id,
                    version_id=version_id,
                    parse_job_id=parse_job_id,
                    source_key=source_key,
                    rows=source_rows,
                    learning_by_book=learning_by_book,
                )
                for ordinal, row in enumerate(source_rows):
                    _upsert_official_document_chunk(
                        cursor,
                        parsed_document_id=parsed_document_id,
                        row=row,
                        ordinal=ordinal,
                        learning_by_book=learning_by_book,
                    )
                    imported_chunk_count += 1

    return OfficialGoldImportSummary(
        chunks_path=str(chunks_path.resolve()),
        source_count=len(grouped),
        chunk_count=len(rows),
        imported_chunk_count=imported_chunk_count,
        repository_id=repository_id,
    )


def _load_gold_chunk_rows(chunks_path: Path, *, limit: int = 0) -> list[dict[str, Any]]:
    chunks_path = chunks_path.resolve()
    rows: list[dict[str, Any]] = []
    with chunks_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            rows.append(json.loads(stripped))
            if limit > 0 and len(rows) >= limit:
                break
    return rows


def _group_rows_by_source(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_source_key(row)].append(row)
    return dict(grouped)


def _learning_by_book_slug(grouped: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    book_slugs = tuple(
        str((source_rows[0] if source_rows else {}).get("book_slug") or source_key).strip()
        for source_key, source_rows in sorted(grouped.items())
    )
    return build_learning_book_index(book_slugs, corpus_kind="official_docs")


def _source_key(row: dict[str, Any]) -> str:
    return str(row.get("source_id") or row.get("book_slug") or "official-doc").strip()


def _source_title(rows: list[dict[str, Any]]) -> str:
    first = rows[0] if rows else {}
    return str(first.get("book_title") or first.get("book_slug") or _source_key(first))


def _stable_uuid(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, ":".join(str(part) for part in parts)))


def _uuid_from_row_chunk_id(row: dict[str, Any]) -> str:
    raw = str(row.get("chunk_id") or "").strip()
    try:
        return str(uuid.UUID(raw))
    except ValueError:
        return _stable_uuid("official-gold-chunk", raw or json.dumps(row, sort_keys=True))


def _stable_sha256(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _section_path(row: dict[str, Any]) -> list[str]:
    value = row.get("section_path")
    if isinstance(value, list):
        return [_split_section_number_title(str(item))[1] for item in value if str(item).strip()]
    chapter = str(row.get("chapter") or "").strip()
    section = str(row.get("section") or "").strip()
    return [_split_section_number_title(item)[1] for item in (chapter, section) if item]


def _section_number(row: dict[str, Any]) -> str:
    explicit = str(row.get("section_number") or "").strip()
    if explicit:
        return explicit
    for candidate in reversed(_raw_section_labels(row)):
        section_number, _ = _split_section_number_title(candidate)
        if section_number:
            return section_number
    return ""


def _heading_title(row: dict[str, Any], section_path: list[str]) -> str:
    if section_path:
        return section_path[-1]
    for candidate in (row.get("section"), row.get("chapter"), row.get("book_title"), row.get("book_slug")):
        text = str(candidate or "").strip()
        if text:
            return _split_section_number_title(text)[1]
    return ""


def _toc_path(row: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for raw_label in _raw_section_labels(row):
        section_number, heading_title = _split_section_number_title(raw_label)
        if not heading_title:
            continue
        labels.append(f"{section_number} {heading_title}".strip() if section_number else heading_title)
    return labels


def _raw_section_labels(row: dict[str, Any]) -> list[str]:
    value = row.get("section_path")
    if isinstance(value, list):
        labels = [str(item).strip() for item in value if str(item).strip()]
        if labels:
            return labels
    labels = []
    for item in (row.get("chapter"), row.get("section")):
        text = str(item or "").strip()
        if text and text not in labels:
            labels.append(text)
    return labels


def _split_section_number_title(title: str) -> tuple[str, str]:
    title = str(title or "").strip()
    match = _SECTION_NUMBER_RE.match(title)
    if not match:
        return "", title
    section_number = match.group(1).strip().rstrip(".")
    heading_title = match.group(2).strip()
    return section_number, heading_title or title


def _source_anchor(row: dict[str, Any]) -> str:
    for key in ("anchor", "anchor_id", "source_anchor"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    section_id = str(row.get("section_id") or "").strip()
    if ":" in section_id:
        return section_id.rsplit(":", 1)[-1]
    return section_id


def _normalized_chunk_text(row: dict[str, Any]) -> str:
    text = str(row.get("text") or "").strip()
    if not text:
        return ""
    raw_labels = _raw_section_labels(row)
    removable = {
        str(row.get("book_title") or "").strip(),
        str(row.get("book_slug") or "").strip(),
        *raw_labels,
        " > ".join(raw_labels),
        *_section_path(row),
        *_toc_path(row),
    }
    lines = text.splitlines()
    while lines and lines[0].strip() in removable:
        lines.pop(0)
    while lines and not lines[0].strip():
        lines.pop(0)
    return render_internal_markup_for_retrieval("\n".join(lines).strip() or text)


def _embedding_chunk_text(row: dict[str, Any]) -> str:
    text = _strip_embedding_leading_context(str(row.get("text") or ""), row)
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    text = text.replace("&quot;", '"').replace("\u00a0", " ")
    text = _repair_embedding_placeholder_artifacts(text)
    if _is_broken_pipe_table_fragment(text):
        return ""
    text = _condense_pipe_table_lines_for_embedding(text)
    protected: list[tuple[str, str]] = []

    def keep(value: str) -> str:
        cleaned = _clean_protected_embedding_span(value)
        if not cleaned:
            return " "
        token = f"PBSKEEP{len(protected)}PBS"
        protected.append((token, cleaned))
        return f" {token} "

    text = _EMBEDDING_CODE_BLOCK_RE.sub(lambda match: keep(str(match.group("body") or "")), text)
    text = _EMBEDDING_TABLE_BLOCK_RE.sub(lambda match: f" {_flatten_plain_text(str(match.group('body') or ''))} ", text)
    text = re.sub(r"`([^`]+)`", lambda match: _inline_code_embedding_replacement(match, keep), text)
    text = _protect_inline_commands(text, keep)
    text = _protect_command_lines(text, keep)
    text = _EMBEDDING_MARKER_RE.sub(" ", text)
    text = _EMBEDDING_DANGLING_MARKER_RE.sub(" ", text)
    text = _EMBEDDING_ORPHAN_CLOSE_MARKER_RE.sub(" ", text)
    text = _EMBEDDING_MARKDOWN_LINK_RE.sub(lambda match: str(match.group(1) or "").strip(), text)
    text = _EMBEDDING_HTML_ANCHOR_RE.sub(" ", text)
    text = _EMBEDDING_DOCS_URL_RE.sub(" ", text)
    text = text.replace("```", " ").replace("`", "")
    text = text.replace("Expand", " ")
    text = re.sub(r"%[0-9A-Fa-f]{2}", " ", text)
    text = _flatten_plain_text(_normalize_embedding_layout(text))
    for token, value in protected:
        text = text.replace(token, value)
    return re.sub(r"\s+", " ", text).strip()


def _keyword_normalized_chunk_text(row: dict[str, Any]) -> str:
    return _flatten_keyword_text(_embedding_chunk_text(row))


def _flatten_keyword_text(text: str) -> str:
    flattened = _flatten_plain_text(text)
    if not flattened:
        return ""
    flattened = re.sub(r"<\s*([^<>]+?)\s*>", r" \1 ", flattened)
    flattened = re.sub(r"--([A-Za-z0-9_.-]+)\s*=\s*", r" \1 ", flattened)
    flattened = re.sub(r"--([A-Za-z0-9_.-]+)", r" \1 ", flattened)
    flattened = re.sub(r"(?<=\w)=(?=\S)", " ", flattened)
    flattened = flattened.replace("\\\n", " ")
    flattened = re.sub(r"[$`\"'{}()[\],;|]", " ", flattened)
    flattened = re.sub(r"[:]", " ", flattened)
    flattened = re.sub(r"\s+", " ", flattened)
    return flattened.strip()


def _condense_pipe_table_lines_for_embedding(text: str) -> str:
    lines: list[str] = []
    for line in str(text or "").splitlines():
        if line.count("|") < 3:
            lines.append(line)
            continue
        cells: list[str] = []
        seen: set[str] = set()
        for raw_cell in line.split("|"):
            cell = _flatten_plain_text(raw_cell)
            if not cell:
                continue
            key = cell.casefold()
            if key in seen:
                continue
            seen.add(key)
            cells.append(cell)
        lines.append(" ".join(cells) if cells else line)
    return "\n".join(lines)


def _is_broken_pipe_table_fragment(text: str) -> bool:
    for line in str(text or "").splitlines():
        first = line.strip()
        if not first:
            continue
        if first.count("|") < 3:
            return False
        lowered = first.casefold()
        return (
            lowered.startswith("브스크립션 필요")
            or lowered.startswith("- 별도의 서브스크립션 필요")
            or lowered.startswith("별도의 서브스크립션 필요")
            or lowered.startswith("포함되지 않음")
            or lowered.startswith("포함됨")
        )
    return False


def _flatten_plain_text(text: str) -> str:
    """Return cleaned prose text with formatting punctuation removed."""
    flattened = unicodedata.normalize("NFC", str(text or ""))
    flattened = flattened.replace("\u00a0", " ")
    flattened = re.sub(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]+", " ", flattened)
    flattened = re.sub(r"[\r\n\t]+", " ", flattened)
    flattened = re.sub(r"[^\w\s]", " ", flattened, flags=re.UNICODE)
    flattened = flattened.replace("_", " ")
    flattened = re.sub(r"\s+", " ", flattened)
    return flattened.strip()


def _protect_command_lines(text: str, keep) -> str:
    protected_lines: list[str] = []
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if _is_command_like_text(stripped):
            protected_lines.append(keep(stripped))
        else:
            protected_lines.append(line)
    return "\n".join(protected_lines)


def _protect_inline_commands(text: str, keep) -> str:
    command_starters = (
        r"oc|oc-mirror|kubectl|podman|butane|nmcli|etcdctl|grep|egrep|cluster-backup\.sh|"
        r"/usr/local/bin/cluster-backup\.sh"
    )
    pattern = re.compile(rf"(?P<cmd>\$\s*(?:{command_starters})\b[^\n가-힣]*)", re.IGNORECASE)
    return pattern.sub(lambda match: keep(str(match.group("cmd") or "")), str(text or ""))


def _inline_code_embedding_replacement(match: re.Match[str], keep) -> str:
    value = str(match.group(1) or "").strip()
    if _is_command_like_text(value):
        return keep(value)
    return f" {value} "


def _is_command_like_text(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    return bool(
        re.match(
            r"^(?:[$#]\s*|sh-[0-9.]+#\s*)?(?:oc|oc-mirror|kubectl|podman|butane|nmcli|etcdctl|grep|egrep|ip|cluster-backup\.sh|/usr/local/bin/cluster-backup\.sh)\b",
            value,
            flags=re.IGNORECASE,
        )
        or re.match(r"^\$\s+", value)
        or re.match(r"^sh-[0-9.]+#\s+", value)
        or re.match(r"^for\s+\w+\s+in\s+.+\bdo\b", value, flags=re.IGNORECASE)
    )


def _clean_protected_embedding_span(text: str) -> str:
    cleaned = _repair_embedding_placeholder_artifacts(
        str(text or "")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("\u00a0", " ")
        .replace("```", " ")
        .replace("`", "")
    )
    cleaned = cleaned.replace('"', " ").replace("'", " ")
    cleaned = cleaned.replace("\\", " ")
    cleaned = _EMBEDDING_MARKER_RE.sub(" ", cleaned)
    cleaned = _EMBEDDING_DANGLING_MARKER_RE.sub(" ", cleaned)
    cleaned = _EMBEDDING_ORPHAN_CLOSE_MARKER_RE.sub(" ", cleaned)
    cleaned = re.sub(r"%[0-9A-Fa-f]{2}", " ", cleaned)
    cleaned = re.sub(r"[\r\n\t]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _embedding_structured_block(match: re.Match[str]) -> str:
    return "\n" + _clean_embedding_structured_body(str(match.group("body") or "")) + "\n"


def _embedding_table_body(match: re.Match[str]) -> str:
    return "\n" + _clean_embedding_structured_body(str(match.group("body") or "")) + "\n"


def _clean_embedding_structured_body(text: str) -> str:
    text = _repair_embedding_placeholder_artifacts(
        str(text or "")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("\u00a0", " ")
        .replace("```", " ")
    )
    lines = [re.sub(r"[ \t]+$", "", line) for line in text.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def _repair_embedding_placeholder_artifacts(text: str) -> str:
    repaired = re.sub(r"&\s*amp\s*;", "&", str(text or ""), flags=re.IGNORECASE)
    repaired = re.sub(r"&\s*lt\s*;", "<", repaired, flags=re.IGNORECASE)
    repaired = re.sub(r"&\s*gt\s*;", ">", repaired, flags=re.IGNORECASE)
    repaired = re.sub(r"&\s*`?\s*lt\s*`?\s*;", "<", repaired, flags=re.IGNORECASE)
    repaired = re.sub(r"&\s*`?\s*gt\s*`?\s*;", ">", repaired, flags=re.IGNORECASE)
    repaired = repaired.replace("</>", " ").replace("<>", " ").replace("<.>", " ")
    repaired = re.sub(r"<\.\s*(?=\n\s*<)", "", repaired)
    repaired = re.sub(r"<\.\s*", " ", repaired)
    repaired = re.sub(
        r"<([A-Za-z_][A-Za-z0-9_-]*)-<([A-Za-z_][A-Za-z0-9_-]*)>-([A-Za-z_][A-Za-z0-9_-]*)-<([A-Za-z_][A-Za-z0-9_-]*)>",
        lambda match: _normalized_placeholder("-".join(match.groups())),
        repaired,
    )
    repaired = re.sub(
        r"<\s*접미사\s+(-[A-Za-z0-9_-]+)\s+로\s+구성됩니다\.\s*([A-Za-z_][A-Za-z0-9_]*)>",
        lambda match: f"<{match.group(2)}>{match.group(1)} 로 구성됩니다.",
        repaired,
    )
    repaired = re.sub(
        r"&\s*lt;\s*([^&<>]+?)\s*&\s*gt;",
        lambda match: _normalized_placeholder(match.group(1)),
        repaired,
        flags=re.IGNORECASE,
    )
    repaired = re.sub(
        r"<\.\s*([A-Za-z_][A-Za-z0-9_-]*)>",
        lambda match: _normalized_placeholder(match.group(1)),
        repaired,
    )
    repaired = repaired.replace("<.>", " ")
    repaired = repaired.replace("\\//", " ")
    repaired = re.sub(
        r"<\s*([A-Za-z_][A-Za-z0-9_\s-]*?)\s*>",
        lambda match: _normalized_placeholder(match.group(1)),
        repaired,
    )
    repaired = re.sub(
        r"(?<![<,/])\b([A-Za-z_][A-Za-z0-9_-]*)>(?=(?:-[A-Za-z0-9_./-]+)|\s*(?:은|는|을|를|와|과|의|로|에|파일|값|이|가))",
        lambda match: _normalized_placeholder(match.group(1)),
        repaired,
    )
    return repaired


def _normalized_placeholder(raw: str) -> str:
    name = re.sub(r"\s+", "", str(raw or "").strip())
    name = name.replace("_ ", "_").replace(" _", "_")
    return f"<{name}>" if name else ""


def _clean_embedding_table_pipes(text: str) -> str:
    lines: list[str] = []
    for line in str(text or "").splitlines():
        if _looks_embedding_table_pipe_line(line):
            line = line.replace("|", " ")
        lines.append(line)
    return "\n".join(lines)


def _normalize_embedding_layout(text: str) -> str:
    output: list[str] = []
    prose_buffer: list[str] = []

    def flush_prose() -> None:
        if not prose_buffer:
            return
        prose = re.sub(r"\s+", " ", " ".join(prose_buffer)).strip()
        if prose:
            output.append(prose)
        prose_buffer.clear()

    for raw_line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").splitlines():
        stripped = re.sub(r"[ \t]+$", "", raw_line).strip()
        if not stripped:
            flush_prose()
            continue
        if _is_embedding_structural_line(raw_line):
            flush_prose()
            output.append(re.sub(r"[ \t]+$", "", raw_line))
        else:
            prose_buffer.append(stripped)
    flush_prose()
    compact: list[str] = []
    for line in output:
        stripped = line.strip()
        if not stripped:
            continue
        if compact and compact[-1].strip() == stripped:
            continue
        compact.append(line)
    return "\n".join(compact).strip()


def _is_embedding_structural_line(line: str) -> bool:
    stripped = str(line or "").strip()
    if not stripped:
        return False
    if str(line or "").startswith((" ", "\t")):
        return True
    if stripped.startswith(("$", "#", "-", "{", "}", "[", "]")):
        return True
    if "|" in stripped:
        return True
    if re.match(r"^[A-Za-z0-9_./-]+:\s*", stripped):
        return True
    if re.match(r"^[A-Za-z0-9_.-]+\s*=\s*", stripped):
        return True
    if re.match(r"^(oc|kubectl|podman|curl|jq|grep|awk|sed|cat|sudo|chroot|ssh|for|while|if|export)\b", stripped):
        return True
    return False


def _looks_embedding_table_pipe_line(line: str) -> bool:
    stripped = str(line or "").strip()
    if "|" not in stripped:
        return False
    if stripped.startswith(
        (
            "$",
            "#",
            "oc ",
            "kubectl ",
            "podman ",
            "curl ",
            "jq ",
            "grep ",
            "awk ",
            "sed ",
            "cat ",
            "sudo ",
            "chroot ",
            "ssh ",
            "for ",
            "while ",
            "if ",
            "export ",
        )
    ):
        return False
    return True


def _strip_embedding_leading_context(text: str, row: dict[str, Any]) -> str:
    if not text:
        return ""
    labels = _embedding_navigation_labels(row)
    lines = text.splitlines()
    while lines:
        first = lines[0].strip()
        if not first:
            lines.pop(0)
            continue
        if first in labels:
            lines.pop(0)
            continue
        break
    while lines and not lines[0].strip():
        lines.pop(0)
    return "\n".join(lines).strip()


def _embedding_navigation_labels(row: dict[str, Any]) -> set[str]:
    raw_labels = _raw_section_labels(row)
    labels = {
        str(row.get("book_title") or "").strip(),
        str(row.get("book_slug") or "").strip(),
        str(row.get("chapter") or "").strip(),
        str(row.get("section") or "").strip(),
        " > ".join(raw_labels),
        " > ".join(_section_path(row)),
        *_section_path(row),
        *_toc_path(row),
        *raw_labels,
    }
    for label in tuple(labels):
        _, title = _split_section_number_title(label)
        if title:
            labels.add(title)
    return {label for label in labels if label}


def _embedding_chunk_export_row(row: dict[str, Any]) -> dict[str, Any]:
    embedding_text = _embedding_chunk_text(row)
    normalized_text = _keyword_normalized_chunk_text(row)
    section_path = _section_path(row)
    toc_path = _toc_path(row)
    section_number = _section_number(row)
    heading_title = _heading_title(row, section_path)
    return {
        "schema_version": OFFICIAL_EMBEDDING_CHUNKS_VERSION,
        "chunk_id": _uuid_from_row_chunk_id(row),
        "source_chunk_id": str(row.get("source_chunk_id") or row.get("chunk_id") or ""),
        "parent_chunk_id": str(row.get("parent_chunk_id") or ""),
        "chunk_role": str(row.get("chunk_role") or "leaf"),
        "navigation_only": bool(row.get("navigation_only") or False),
        "chunk_type": str(row.get("chunk_type") or "reference"),
        "semantic_role": str(row.get("semantic_role") or ""),
        "book_slug": str(row.get("book_slug") or ""),
        "book_title": str(row.get("book_title") or ""),
        "chapter": str(row.get("chapter") or ""),
        "section": str(row.get("section") or ""),
        "section_id": str(row.get("section_id") or ""),
        "section_path": section_path,
        "section_number": section_number,
        "heading_title": heading_title,
        "breadcrumb": " > ".join(toc_path or section_path),
        "source_anchor": _source_anchor(row),
        "source_url": str(row.get("source_url") or ""),
        "viewer_path": str(row.get("viewer_path") or ""),
        "source_id": str(row.get("source_id") or ""),
        "source_lane": str(row.get("source_lane") or ""),
        "source_language": str(row.get("source_language") or row.get("locale") or ""),
        "source_type": str(row.get("source_type") or ""),
        "source_collection": str(row.get("source_collection") or ""),
        "product": str(row.get("product") or ""),
        "version": str(row.get("version") or ""),
        "locale": str(row.get("locale") or ""),
        "review_status": str(row.get("review_status") or ""),
        "normalized_text": normalized_text,
        "embedding_text": embedding_text,
        "text": embedding_text,
        "token_count": len(embedding_text.split()),
    }


def _text_layer_export_row(row: dict[str, Any]) -> dict[str, Any]:
    raw_text = str(row.get("text") or "")
    markdown = _normalized_chunk_text(row)
    normalized_text = _keyword_normalized_chunk_text(row)
    embedding_text = _embedding_chunk_text(row)
    section_path = _section_path(row)
    toc_path = _toc_path(row)
    section_number = _section_number(row)
    heading_title = _heading_title(row, section_path)
    return {
        "schema_version": OFFICIAL_TEXT_LAYERS_VERSION,
        "chunk_id": _uuid_from_row_chunk_id(row),
        "source_chunk_id": str(row.get("source_chunk_id") or row.get("chunk_id") or ""),
        "parent_chunk_id": str(row.get("parent_chunk_id") or ""),
        "chunk_role": str(row.get("chunk_role") or "leaf"),
        "navigation_only": bool(row.get("navigation_only") or False),
        "chunk_type": str(row.get("chunk_type") or "reference"),
        "semantic_role": str(row.get("semantic_role") or ""),
        "book_slug": str(row.get("book_slug") or ""),
        "book_title": str(row.get("book_title") or ""),
        "chapter": str(row.get("chapter") or ""),
        "section": str(row.get("section") or ""),
        "section_id": str(row.get("section_id") or ""),
        "section_path": section_path,
        "toc_path": toc_path,
        "section_number": section_number,
        "heading_title": heading_title,
        "breadcrumb": " > ".join(toc_path or section_path),
        "source_anchor": _source_anchor(row),
        "source_url": str(row.get("source_url") or ""),
        "viewer_path": str(row.get("viewer_path") or ""),
        "source_id": str(row.get("source_id") or ""),
        "source_lane": str(row.get("source_lane") or ""),
        "source_language": str(row.get("source_language") or row.get("locale") or ""),
        "source_type": str(row.get("source_type") or ""),
        "source_collection": str(row.get("source_collection") or ""),
        "product": str(row.get("product") or ""),
        "version": str(row.get("version") or ""),
        "locale": str(row.get("locale") or ""),
        "review_status": str(row.get("review_status") or ""),
        "raw_text": raw_text,
        "markdown": markdown,
        "normalized_text": normalized_text,
        "embedding_text": embedding_text,
        "embedding_text_present": bool(embedding_text),
        "token_count": len(embedding_text.split()),
    }


def write_official_embedding_chunks(
    chunks_path: Path,
    output_path: Path,
    *,
    limit: int = 0,
) -> dict[str, Any]:
    rows = _load_gold_chunk_rows(chunks_path, limit=limit)
    export_rows: list[dict[str, Any]] = []
    output_path.parent.mkdir(parents=True, exist_ok=True)
    skipped_empty_count = 0
    for row in rows:
        export_row = _embedding_chunk_export_row(row)
        if not export_row["embedding_text"]:
            skipped_empty_count += 1
            continue
        export_rows.append(export_row)
    export_rows, suppression = _suppress_redundant_embedding_rows(export_rows)
    with output_path.open("w", encoding="utf-8") as handle:
        for export_row in export_rows:
            handle.write(json.dumps(export_row, ensure_ascii=False, sort_keys=True) + "\n")
    return {
        "source_chunks_path": str(chunks_path.resolve()),
        "embedding_chunks_path": str(output_path.resolve()),
        "schema_version": OFFICIAL_EMBEDDING_CHUNKS_VERSION,
        "input_chunk_count": len(rows),
        "embedding_chunk_count": len(export_rows),
        "skipped_empty_embedding_count": skipped_empty_count,
        **suppression,
    }


def write_official_text_layers(
    chunks_path: Path,
    output_path: Path,
    *,
    limit: int = 0,
) -> dict[str, Any]:
    rows = _load_gold_chunk_rows(chunks_path, limit=limit)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    embedding_text_present_count = 0
    with output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            export_row = _text_layer_export_row(row)
            embedding_text_present_count += int(bool(export_row["embedding_text_present"]))
            handle.write(json.dumps(export_row, ensure_ascii=False, sort_keys=True) + "\n")
    return {
        "source_chunks_path": str(chunks_path.resolve()),
        "text_layers_path": str(output_path.resolve()),
        "schema_version": OFFICIAL_TEXT_LAYERS_VERSION,
        "input_chunk_count": len(rows),
        "text_layer_row_count": len(rows),
        "embedding_text_present_count": embedding_text_present_count,
    }


def _suppress_redundant_embedding_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    keep = [True] * len(rows)
    skipped_exact_duplicate_count = 0
    skipped_contained_overlap_count = 0
    seen: set[tuple[str, str, str]] = set()
    for index, row in enumerate(rows):
        key = (
            str(row.get("source_id") or ""),
            str(row.get("section_id") or ""),
            str(row.get("embedding_text") or ""),
        )
        if key in seen:
            keep[index] = False
            skipped_exact_duplicate_count += 1
            continue
        seen.add(key)

    scope_indexes: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        scope_indexes[(str(row.get("source_id") or ""), str(row.get("section_id") or ""))].append(index)

    for indexes in scope_indexes.values():
        for position, index in enumerate(indexes):
            if not keep[index]:
                continue
            text = str(rows[index].get("embedding_text") or "")
            window = indexes[max(0, position - 3) : min(len(indexes), position + 4)]
            for other_index in window:
                if other_index == index or not keep[other_index]:
                    continue
                other_text = str(rows[other_index].get("embedding_text") or "")
                if _is_redundant_embedding_overlap(text, other_text):
                    keep[index] = False
                    skipped_contained_overlap_count += 1
                    break

    kept_rows = [row for row, should_keep in zip(rows, keep, strict=True) if should_keep]
    return kept_rows, {
        "skipped_exact_duplicate_embedding_count": skipped_exact_duplicate_count,
        "skipped_contained_overlap_embedding_count": skipped_contained_overlap_count,
    }


def _is_redundant_embedding_overlap(text: str, other_text: str) -> bool:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    other_text = re.sub(r"\s+", " ", str(other_text or "")).strip()
    if len(text) < 80 or len(other_text) <= len(text) or text == other_text:
        return False
    if len(text) / max(len(other_text), 1) < 0.45:
        return False
    return text in other_text


def _chunk_metadata(row: dict[str, Any]) -> dict[str, Any]:
    keep_keys = (
        "book_slug",
        "book_title",
        "chapter",
        "section",
        "section_id",
        "anchor",
        "source_url",
        "viewer_path",
        "source_id",
        "source_lane",
        "source_type",
        "source_collection",
        "review_status",
        "trust_score",
        "parsed_artifact_id",
        "semantic_role",
        "block_kinds",
        "cli_commands",
        "error_strings",
        "k8s_objects",
        "operator_names",
        "verification_hints",
        "citation_eligible",
        "citation_block_reason",
        "enabled_for_chat",
        "product",
        "version",
        "locale",
        "translation_status",
        "approval_state",
        "publication_state",
        "chunk_role",
        "parent_chunk_id",
        "child_chunk_ids",
        "navigation_only",
        "beginner_narrative",
        "starter_question_candidates",
        "followup_question_candidates",
        "question_candidates_version",
    )
    return {key: row[key] for key in keep_keys if key in row}


def _official_chunk_metadata(
    row: dict[str, Any],
    *,
    ordinal: int,
    learning_by_book: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    section_path = _section_path(row)
    section_number = _section_number(row)
    heading_title = _heading_title(row, section_path)
    raw_text = str(row.get("text") or "")
    chunk_text = _normalized_chunk_text(row)
    normalized_text = _keyword_normalized_chunk_text(row)
    embedding_text = _embedding_chunk_text(row)
    metadata = _chunk_metadata(row)
    book_slug = str(row.get("book_slug") or "").strip()
    learning = dict(((learning_by_book or {}).get(book_slug) or {}).get("learning") or {})
    metadata["learning"] = build_chunk_learning_metadata(
        learning,
        ordinal=int(row.get("ordinal") if row.get("ordinal") is not None else ordinal),
        section_number=section_number,
        heading=heading_title,
        text="\n".join([chunk_text, " ".join(str(item) for item in row.get("cli_commands", []) if str(item).strip())]),
    )
    candidates = build_chunk_question_candidates({**row, "text": chunk_text})
    metadata.setdefault("starter_question_candidates", candidates["starter_question_candidates"])
    metadata.setdefault("followup_question_candidates", candidates["followup_question_candidates"])
    metadata.setdefault("question_candidates_version", 1 if candidates["starter_question_candidates"] else 0)
    metadata["normalized_text"] = normalized_text
    metadata["text_layers"] = {
        "version": OFFICIAL_TEXT_LAYERS_VERSION,
        "raw_text": raw_text,
        "markdown": chunk_text,
        "normalized_text": normalized_text,
        "embedding_text": embedding_text,
        "quality_warnings": [],
        "rechunk_status": "unchanged",
    }
    return metadata


def _source_metadata(
    source_key: str,
    rows: list[dict[str, Any]],
    chunks_path: Path,
    *,
    learning_by_book: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    first = rows[0] if rows else {}
    book_slug = str(first.get("book_slug") or source_key)
    learning_node = (learning_by_book or {}).get(book_slug) or {}
    category_key = str(learning_node.get("category_key") or infer_category_key(book_slug))
    return {
        **_chunk_metadata(first),
        "source_id": source_key,
        "book_slug": book_slug,
        "book_title": _source_title(rows),
        "category_key": category_key,
        "category_label": str(learning_node.get("category_label") or CATEGORY_LABELS.get(category_key, "Wiki")),
        "learning": dict(learning_node.get("learning") or {}),
        "document_format": "official_gold_jsonl",
        "source_scope": "official_docs",
        "visibility": "global_shared",
        "chunk_count": len(rows),
        "source_jsonl": str(chunks_path.resolve()),
    }


def _upsert_official_document_source(
    cursor,
    *,
    tenant_id: str,
    workspace_id: str,
    repository_id: str,
    source_key: str,
    rows: list[dict[str, Any]],
    chunks_path: Path,
    learning_by_book: dict[str, dict[str, Any]],
) -> str:
    first = rows[0]
    source_id = _stable_uuid("official-gold-source", source_key)
    source_sha256 = _stable_sha256("official-gold-source", source_key)
    cursor.execute(
        """
        INSERT INTO document_sources (
            id, tenant_id, workspace_id, source_kind, filename, mime_type, sha256,
            storage_key, byte_size, access_policy, metadata, created_by,
            repository_id, owner_user_id, visibility, source_scope
        )
        VALUES (
            %s, %s, %s, 'official_gold', %s, 'application/x-jsonlines', %s,
            %s, 0, '{}'::jsonb, %s::jsonb, '',
            %s::uuid, '', 'global_shared', 'official_docs'
        )
        ON CONFLICT (id) DO UPDATE SET
            filename = EXCLUDED.filename,
            storage_key = EXCLUDED.storage_key,
            metadata = EXCLUDED.metadata,
            repository_id = EXCLUDED.repository_id,
            visibility = EXCLUDED.visibility,
            source_scope = EXCLUDED.source_scope
        RETURNING id
        """,
        (
            source_id,
            tenant_id,
            workspace_id,
            f"{str(first.get('book_slug') or source_key)}.jsonl",
            source_sha256,
            _official_gold_storage_key(source_key),
            _json(_source_metadata(source_key, rows, chunks_path, learning_by_book=learning_by_book)),
            repository_id,
        ),
    )
    return _fetch_id(cursor)


def _upsert_official_document_version(
    cursor,
    *,
    source_id: str,
    source_key: str,
    chunks_path: Path,
) -> str:
    version_id = _stable_uuid("official-gold-version", source_key)
    source_sha256 = _stable_sha256("official-gold-source", source_key)
    cursor.execute(
        """
        INSERT INTO document_versions (id, document_source_id, version_no, source_sha256, storage_key)
        VALUES (%s, %s, 1, %s, %s)
        ON CONFLICT (document_source_id, version_no) DO UPDATE SET
            source_sha256 = EXCLUDED.source_sha256,
            storage_key = EXCLUDED.storage_key
        RETURNING id
        """,
        (version_id, source_id, source_sha256, _official_gold_storage_key()),
    )
    return _fetch_id(cursor)


def _upsert_official_parse_job(
    cursor,
    *,
    source_id: str,
    version_id: str,
    source_key: str,
) -> str:
    parse_job_id = _stable_uuid("official-gold-parse-job", source_key)
    cursor.execute(
        """
        INSERT INTO parse_jobs (
            id, document_source_id, document_version_id, parser_name, parser_version,
            status, completed_at
        )
        VALUES (%s, %s, %s, 'official-gold-import', '0.1', 'succeeded', now())
        ON CONFLICT (id) DO UPDATE SET
            status = EXCLUDED.status,
            completed_at = now()
        RETURNING id
        """,
        (parse_job_id, source_id, version_id),
    )
    return _fetch_id(cursor)


def _upsert_official_parsed_document(
    cursor,
    *,
    source_id: str,
    version_id: str,
    parse_job_id: str,
    source_key: str,
    rows: list[dict[str, Any]],
    learning_by_book: dict[str, dict[str, Any]],
) -> str:
    parsed_document_id = _stable_uuid("official-gold-parsed-document", source_key)
    book_slug = str((rows[0] if rows else {}).get("book_slug") or source_key).strip()
    learning = dict(((learning_by_book or {}).get(book_slug) or {}).get("learning") or {})
    cursor.execute(
        """
        INSERT INTO parsed_documents (
            id, document_source_id, document_version_id, parse_job_id,
            parser_name, parser_version, title, markdown, metadata, outline, warnings
        )
        VALUES (%s, %s, %s, %s, 'official-gold-import', '0.1', %s, '', %s::jsonb, '[]'::jsonb, '[]'::jsonb)
        ON CONFLICT (id) DO UPDATE SET
            title = EXCLUDED.title,
            metadata = EXCLUDED.metadata
        RETURNING id
        """,
        (
            parsed_document_id,
            source_id,
            version_id,
            parse_job_id,
            _source_title(rows),
            _json({"source_key": source_key, "chunk_count": len(rows), "document_format": "official_gold_jsonl", "learning": learning}),
        ),
    )
    return _fetch_id(cursor)


def _upsert_official_document_chunk(
    cursor,
    *,
    parsed_document_id: str,
    row: dict[str, Any],
    ordinal: int,
    learning_by_book: dict[str, dict[str, Any]],
) -> str:
    chunk_id = _uuid_from_row_chunk_id(row)
    section_path = _section_path(row)
    section_number = _section_number(row)
    heading_title = _heading_title(row, section_path)
    source_anchor = _source_anchor(row)
    toc_path = _toc_path(row)
    chunk_text = _normalized_chunk_text(row)
    embedding_text = _embedding_chunk_text(row)
    metadata = _official_chunk_metadata(row, ordinal=ordinal, learning_by_book=learning_by_book)
    cursor.execute(
        """
        INSERT INTO document_chunks (
            id, parsed_document_id, chunk_key, ordinal, chunk_type, markdown,
            embedding_text, token_count, page_start, page_end, section_path,
            section_number, heading_title, source_anchor, toc_path,
            asset_ids, metadata, repository_id, owner_user_id, visibility, source_scope,
            chunk_role, parent_chunk_id, child_chunk_ids, navigation_only, beginner_narrative,
            starter_question_candidates, followup_question_candidates, question_candidates_version
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL, %s::jsonb,
            %s, %s, %s, %s::jsonb, '[]'::jsonb, %s::jsonb,
            (
                SELECT ds.repository_id
                FROM parsed_documents pd
                JOIN document_sources ds ON ds.id = pd.document_source_id
                WHERE pd.id = %s
            ),
            '', 'global_shared', 'official_docs',
            %s, NULLIF(%s, '')::uuid, %s::jsonb, %s, %s,
            %s::jsonb, %s::jsonb, %s
        )
        ON CONFLICT (id) DO UPDATE SET
            parsed_document_id = EXCLUDED.parsed_document_id,
            chunk_key = EXCLUDED.chunk_key,
            ordinal = EXCLUDED.ordinal,
            chunk_type = EXCLUDED.chunk_type,
            markdown = EXCLUDED.markdown,
            embedding_text = EXCLUDED.embedding_text,
            token_count = EXCLUDED.token_count,
            section_path = EXCLUDED.section_path,
            section_number = EXCLUDED.section_number,
            heading_title = EXCLUDED.heading_title,
            source_anchor = EXCLUDED.source_anchor,
            toc_path = EXCLUDED.toc_path,
            metadata = EXCLUDED.metadata,
            repository_id = EXCLUDED.repository_id,
            visibility = EXCLUDED.visibility,
            source_scope = EXCLUDED.source_scope,
            chunk_role = EXCLUDED.chunk_role,
            parent_chunk_id = EXCLUDED.parent_chunk_id,
            child_chunk_ids = EXCLUDED.child_chunk_ids,
            navigation_only = EXCLUDED.navigation_only,
            beginner_narrative = EXCLUDED.beginner_narrative,
            starter_question_candidates = EXCLUDED.starter_question_candidates,
            followup_question_candidates = EXCLUDED.followup_question_candidates,
            question_candidates_version = EXCLUDED.question_candidates_version
        RETURNING id
        """,
        (
            chunk_id,
            parsed_document_id,
            chunk_id,
            int(row.get("ordinal") if row.get("ordinal") is not None else ordinal),
            str(row.get("chunk_type") or "reference"),
            chunk_text,
            embedding_text,
            len(embedding_text.split()),
            _json(section_path),
            section_number,
            heading_title,
            source_anchor,
            _json(toc_path),
            _json(metadata),
            parsed_document_id,
            str(row.get("chunk_role") or metadata.get("chunk_role") or "leaf"),
            str(row.get("parent_chunk_id") or metadata.get("parent_chunk_id") or ""),
            _json(row.get("child_chunk_ids") or metadata.get("child_chunk_ids") or []),
            bool(row.get("navigation_only") or metadata.get("navigation_only") or False),
            str(row.get("beginner_narrative") or metadata.get("beginner_narrative") or ""),
            _json(row.get("starter_question_candidates") or metadata.get("starter_question_candidates") or []),
            _json(row.get("followup_question_candidates") or metadata.get("followup_question_candidates") or []),
            int(row.get("question_candidates_version") or metadata.get("question_candidates_version") or 0),
        ),
    )
    return _fetch_id(cursor)


__all__ = [
    "OFFICIAL_EMBEDDING_CHUNKS_VERSION",
    "OFFICIAL_TEXT_LAYERS_VERSION",
    "OfficialGoldImportSummary",
    "build_official_gold_import_plan",
    "import_official_gold_chunks",
    "write_official_embedding_chunks",
    "write_official_text_layers",
]
