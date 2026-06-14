"""Enrich tracked official gold chunks without re-fetching source documents."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import uuid
from typing import Any

from play_book_studio.config.corpus_paths import OFFICIAL_GOLD_CHUNKS_PATH

from .chunk_question_candidates import build_chunk_question_candidates, has_current_question_candidates
from .runtime_catalog_library import _bm25_row


SPACE_RE = re.compile(r"\s+")
NAVIGATION_PHRASES = (
    "관련 문서",
    "이 문서에서는",
    "다음 문서",
    "문서를 참조",
    "open document",
    "close",
)


def enrich_official_gold_chunks(
    chunks_path: Path = OFFICIAL_GOLD_CHUNKS_PATH,
    *,
    bm25_path: Path | None = None,
    dry_run: bool = False,
    question_llm_client: Any | None = None,
) -> dict[str, Any]:
    rows = _read_jsonl(chunks_path)
    leaf_rows = [
        _enrich_leaf(row, question_llm_client=question_llm_client)
        for row in rows
        if str(row.get("chunk_role") or "leaf") != "parent"
    ]
    parents = [_parent_row(group, question_llm_client=question_llm_client) for group in _groups(leaf_rows).values() if group]
    enriched_rows = _sort_rows([*leaf_rows, *parents])
    bm25_rows = [_bm25_row(row) for row in enriched_rows]

    if not dry_run:
        _write_jsonl(chunks_path, enriched_rows)
        if bm25_path is not None:
            _write_jsonl(bm25_path, bm25_rows)

    return {
        "chunks_path": str(chunks_path),
        "bm25_path": str(bm25_path) if bm25_path is not None else "",
        "dry_run": dry_run,
        "input_count": len(rows),
        "leaf_count": len(leaf_rows),
        "parent_count": len(parents),
        "output_count": len(enriched_rows),
        "navigation_only_count": sum(1 for row in enriched_rows if row.get("navigation_only")),
        "starter_candidate_count": sum(1 for row in enriched_rows if row.get("starter_question_candidates")),
        "followup_candidate_count": sum(1 for row in enriched_rows if row.get("followup_question_candidates")),
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _groups(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_group_key(row)].append(row)
    return grouped


def _group_key(row: dict[str, Any]) -> str:
    return "|".join(
        (
            str(row.get("source_id") or ""),
            str(row.get("book_slug") or ""),
            str(row.get("section_id") or ""),
            str(row.get("anchor") or ""),
        )
    )


def _sort_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            str(row.get("book_slug") or ""),
            str(row.get("section_id") or ""),
            0 if row.get("chunk_role") == "parent" else 1,
            int(row.get("ordinal") or 0),
            str(row.get("chunk_id") or ""),
        ),
    )


def _enrich_leaf(row: dict[str, Any], *, question_llm_client: Any | None = None) -> dict[str, Any]:
    enriched = dict(row)
    enriched["chunk_role"] = "leaf"
    enriched["parent_chunk_id"] = _parent_id_for_group_key(_group_key(enriched))
    enriched["child_chunk_ids"] = []
    enriched["navigation_only"] = bool(enriched.get("navigation_only")) or _is_navigation_only(enriched)
    enriched.setdefault("beginner_narrative", "")
    _apply_question_candidates(enriched, llm_client=question_llm_client)
    return enriched


def _parent_row(group: list[dict[str, Any]], *, question_llm_client: Any | None = None) -> dict[str, Any]:
    first = dict(group[0])
    parent = dict(first)
    parent["chunk_id"] = _parent_id_for_group_key(_group_key(first))
    parent["chunk_role"] = "parent"
    parent["parent_chunk_id"] = ""
    parent["child_chunk_ids"] = [str(row.get("chunk_id") or "") for row in group if row.get("chunk_id")]
    parent["text"] = _parent_text(group)
    parent["token_count"] = sum(int(row.get("token_count") or 0) for row in group) or _token_estimate(parent["text"])
    parent["ordinal"] = max((int(row.get("ordinal") or 0) for row in group), default=0) + 1
    parent["navigation_only"] = False
    parent.setdefault("beginner_narrative", "")
    _apply_question_candidates(parent, llm_client=question_llm_client)
    return parent


def _parent_id_for_group_key(group_key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"official-gold-parent:{group_key}"))


def _parent_text(group: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for row in group:
        for block in str(row.get("text") or "").split("\n\n"):
            cleaned = block.strip()
            if not cleaned:
                continue
            key = SPACE_RE.sub(" ", cleaned).lower()
            if key in seen:
                continue
            seen.add(key)
            parts.append(cleaned)
    return "\n\n".join(parts)


def _token_estimate(text: str) -> int:
    return max(1, len(SPACE_RE.findall(text)) + 1)


def _is_navigation_only(row: dict[str, Any]) -> bool:
    text = SPACE_RE.sub(" ", str(row.get("text") or "")).strip()
    if not text:
        return True
    if str(row.get("chunk_type") or "").strip() != "reference":
        return False
    if len(text.split()) >= 60:
        return False
    lowered = text.lower()
    return any(phrase in text or phrase in lowered for phrase in NAVIGATION_PHRASES)


def _apply_question_candidates(row: dict[str, Any], *, llm_client: Any | None = None) -> None:
    candidates = (
        build_chunk_question_candidates(row, llm_client=llm_client)
        if str(row.get("chunk_role") or "leaf") == "parent" or has_current_question_candidates(row)
        else {"starter_question_candidates": [], "followup_question_candidates": []}
    )
    row["starter_question_candidates"] = candidates["starter_question_candidates"]
    row["followup_question_candidates"] = candidates["followup_question_candidates"]
    row["question_candidates_version"] = 2 if candidates["starter_question_candidates"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enrich tracked official gold chunks in-place.")
    parser.add_argument("--chunks-path", type=Path, default=OFFICIAL_GOLD_CHUNKS_PATH)
    parser.add_argument("--bm25-path", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    print(
        json.dumps(
            enrich_official_gold_chunks(
                args.chunks_path,
                bm25_path=args.bm25_path,
                dry_run=args.dry_run,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
