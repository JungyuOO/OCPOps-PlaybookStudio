"""Offline quality audit for runtime corpus JSONL chunks."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from play_book_studio.config.corpus_paths import (
    COURSE_PBS_DIR,
    OFFICIAL_GOLD_CHUNKS_PATH,
    OPS_LEARNING_CHUNKS_PATH,
)


HANGUL_SYLLABLE_RE = re.compile(r"[\uac00-\ud7a3]")
CJK_IDEOGRAPH_RE = re.compile(r"[\u4e00-\u9fff]")
REPLACEMENT_CHAR_RE = re.compile("\ufffd")
COMMAND_RE = re.compile(r"\b(?:oc|kubectl)\s+[A-Za-z0-9._:/=-]+", re.IGNORECASE)

TEXT_KEYS = (
    "text",
    "search_text",
    "embedding_text",
    "body_md",
    "beginner_explanation",
    "source_summary",
    "visual_text",
)
TITLE_KEYS = ("title", "book_title", "source_title", "chapter", "section")
SOURCE_KEYS = ("source_url", "viewer_path", "source_ref", "source_pptx", "source_id")
ID_KEYS = ("chunk_id", "learning_chunk_id", "id")


@dataclass(frozen=True)
class CorpusAuditTarget:
    label: str
    path: Path
    source_scope: str


def default_corpus_audit_targets(root_dir: Path) -> list[CorpusAuditTarget]:
    root = root_dir.resolve()
    return [
        CorpusAuditTarget(
            label="official_gold_chunks",
            path=root / OFFICIAL_GOLD_CHUNKS_PATH,
            source_scope="official_docs",
        ),
        CorpusAuditTarget(
            label="kmsc_course_chunks",
            path=root / COURSE_PBS_DIR / "chunks.jsonl",
            source_scope="study_docs",
        ),
        CorpusAuditTarget(
            label="kmsc_ops_learning_chunks",
            path=root / OPS_LEARNING_CHUNKS_PATH,
            source_scope="study_docs",
        ),
    ]


def load_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def audit_runtime_corpus(root_dir: Path, *, max_examples: int = 5) -> dict[str, Any]:
    targets = default_corpus_audit_targets(root_dir)
    reports = [audit_corpus_jsonl(target, max_examples=max_examples) for target in targets]
    present_reports = [report for report in reports if report["exists"]]
    return {
        "canonical_model": "corpus_quality_audit_v1",
        "root_dir": str(root_dir.resolve()),
        "target_count": len(reports),
        "present_target_count": len(present_reports),
        "row_count": sum(int(report["row_count"]) for report in present_reports),
        "mojibake_suspect_count": sum(int(report["mojibake"]["suspect_count"]) for report in present_reports),
        "missing_text_count": sum(int(report["missing_text_count"]) for report in present_reports),
        "targets": reports,
    }


def audit_corpus_jsonl(target: CorpusAuditTarget, *, max_examples: int = 5) -> dict[str, Any]:
    if not target.path.exists():
        return {
            "label": target.label,
            "source_scope": target.source_scope,
            "path": str(target.path),
            "exists": False,
            "row_count": 0,
            "missing_text_count": 0,
            "mojibake": {"suspect_count": 0, "suspect_ratio": 0.0, "examples": []},
        }

    rows = load_jsonl_rows(target.path)
    return audit_chunk_rows(
        rows,
        label=target.label,
        source_scope=target.source_scope,
        path=target.path,
        max_examples=max_examples,
    )


def audit_chunk_rows(
    rows: list[dict[str, Any]],
    *,
    label: str,
    source_scope: str,
    path: Path | None = None,
    max_examples: int = 5,
) -> dict[str, Any]:
    row_count = len(rows)
    ids: list[str] = []
    missing_id_count = 0
    missing_text_count = 0
    missing_title_count = 0
    missing_source_count = 0
    too_short_count = 0
    too_long_count = 0
    command_reference_count = 0
    image_reference_count = 0
    asset_reference_count = 0
    image_without_direct_asset_count = 0
    source_chunk_reference_count = 0
    query_variant_count = 0
    text_lengths: list[int] = []
    mojibake_examples: list[dict[str, Any]] = []
    mojibake_count = 0
    per_source_type: Counter[str] = Counter()

    for index, row in enumerate(rows):
        chunk_id = _first_string(row, ID_KEYS)
        if chunk_id:
            ids.append(chunk_id)
        else:
            missing_id_count += 1

        text = chunk_text(row)
        text_length = len(text)
        if text:
            text_lengths.append(text_length)
        else:
            missing_text_count += 1
        if text and text_length < 80:
            too_short_count += 1
        if text_length > 4000:
            too_long_count += 1

        title = _first_string(row, TITLE_KEYS)
        if not title:
            missing_title_count += 1
        if not _has_source_reference(row):
            missing_source_count += 1

        if _has_command_reference(row, text):
            command_reference_count += 1
        has_image_reference = _has_image_reference(row)
        direct_asset_count = _asset_reference_count(row)
        if has_image_reference:
            image_reference_count += 1
            if direct_asset_count == 0:
                image_without_direct_asset_count += 1
        asset_reference_count += direct_asset_count
        if row.get("source_chunk_ids"):
            source_chunk_reference_count += 1
        query_variant_count += len([item for item in row.get("query_variants") or [] if str(item or "").strip()])

        source_type = str(row.get("source_type") or row.get("source_kind") or row.get("chunk_type") or "").strip()
        if source_type:
            per_source_type[source_type] += 1

        if _looks_like_mojibake(" ".join(part for part in (title, text[:1200]) if part)):
            mojibake_count += 1
            if len(mojibake_examples) < max_examples:
                mojibake_examples.append(
                    {
                        "index": index,
                        "chunk_id": chunk_id,
                        "title": title[:160],
                        "text_preview": text[:240],
                    }
                )

    duplicate_id_count = sum(count - 1 for count in Counter(ids).values() if count > 1)
    return {
        "label": label,
        "source_scope": source_scope,
        "path": str(path) if path else "",
        "exists": True,
        "row_count": row_count,
        "missing_id_count": missing_id_count,
        "duplicate_id_count": duplicate_id_count,
        "missing_text_count": missing_text_count,
        "missing_title_count": missing_title_count,
        "missing_source_count": missing_source_count,
        "too_short_count": too_short_count,
        "too_long_count": too_long_count,
        "text_length": _length_summary(text_lengths),
        "command_reference_count": command_reference_count,
        "image_reference_count": image_reference_count,
        "asset_reference_count": asset_reference_count,
        "image_without_direct_asset_count": image_without_direct_asset_count,
        "source_chunk_reference_count": source_chunk_reference_count,
        "query_variant_count": query_variant_count,
        "source_type_counts": dict(sorted(per_source_type.items())),
        "mojibake": {
            "suspect_count": mojibake_count,
            "suspect_ratio": _ratio(mojibake_count, row_count),
            "examples": mojibake_examples,
        },
    }


def chunk_text(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in TEXT_KEYS:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    index_texts = row.get("index_texts")
    if isinstance(index_texts, dict):
        for key in ("dense_text", "sparse_text", "title_text", "visual_text"):
            value = index_texts.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
    return "\n".join(dict.fromkeys(parts))


def _first_string(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _has_source_reference(row: dict[str, Any]) -> bool:
    if _first_string(row, SOURCE_KEYS):
        return True
    return bool(row.get("source_chunk_ids"))


def _has_command_reference(row: dict[str, Any], text: str) -> bool:
    commands = row.get("cli_commands")
    if isinstance(commands, list) and any(str(item or "").strip() for item in commands):
        return True
    return bool(COMMAND_RE.search(text))


def _has_image_reference(row: dict[str, Any]) -> bool:
    if isinstance(row.get("image_attachments"), list) and row["image_attachments"]:
        return True
    if isinstance(row.get("image_evidence_assets"), list) and row["image_evidence_assets"]:
        return True
    if isinstance(row.get("image_evidence_texts"), list) and row["image_evidence_texts"]:
        return True
    facets = row.get("facets")
    return isinstance(facets, dict) and bool(facets.get("has_image"))


def _asset_reference_count(row: dict[str, Any]) -> int:
    count = 0
    for attachment in row.get("image_attachments") or []:
        if isinstance(attachment, dict) and str(attachment.get("asset_path") or "").strip():
            count += 1
    for attachment in row.get("image_evidence_assets") or []:
        if isinstance(attachment, dict) and str(attachment.get("asset_path") or "").strip():
            count += 1
    return count


def _looks_like_mojibake(text: str) -> bool:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return False
    hangul_count = len(HANGUL_SYLLABLE_RE.findall(cleaned))
    cjk_count = len(CJK_IDEOGRAPH_RE.findall(cleaned))
    replacement_count = len(REPLACEMENT_CHAR_RE.findall(cleaned))
    question_count = cleaned.count("?")
    if replacement_count:
        return True
    if cjk_count >= 3 and hangul_count == 0:
        return True
    return cjk_count >= 6 and question_count >= 2 and hangul_count < cjk_count


def _length_summary(lengths: list[int]) -> dict[str, int]:
    if not lengths:
        return {"min": 0, "p50": 0, "p95": 0, "max": 0}
    sorted_lengths = sorted(lengths)
    return {
        "min": sorted_lengths[0],
        "p50": _percentile(sorted_lengths, 0.50),
        "p95": _percentile(sorted_lengths, 0.95),
        "max": sorted_lengths[-1],
    }


def _percentile(sorted_values: list[int], percentile: float) -> int:
    if not sorted_values:
        return 0
    index = min(len(sorted_values) - 1, max(0, round((len(sorted_values) - 1) * percentile)))
    return sorted_values[index]


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / max(denominator, 1), 4)


__all__ = [
    "CorpusAuditTarget",
    "audit_chunk_rows",
    "audit_corpus_jsonl",
    "audit_runtime_corpus",
    "chunk_text",
    "default_corpus_audit_targets",
    "load_jsonl_rows",
]
