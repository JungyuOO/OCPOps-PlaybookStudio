"""Audit user-upload chunk quality from the PostgreSQL document corpus."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from play_book_studio.config.settings import load_settings
from play_book_studio.retrieval.payload import text_hash


RAW_MARKUP_RE = re.compile(r"\[/?(?:CODE|TABLE)[^\]]*\]", re.IGNORECASE)
SPACE_RE = re.compile(r"\s+")
DEFAULT_TITLE_ONLY_RATE_REVIEW = 0.35
DEFAULT_UNDERSIZED_RATE_REVIEW = 0.35


@dataclass(frozen=True, slots=True)
class AuditThresholds:
    title_only_rate_review: float = DEFAULT_TITLE_ONLY_RATE_REVIEW
    undersized_rate_review: float = DEFAULT_UNDERSIZED_RATE_REVIEW


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile)
    return ordered[max(0, min(index, len(ordered) - 1))]


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item).strip()]
    return []


def _compact(value: Any) -> str:
    return SPACE_RE.sub(" ", str(value or "")).strip()


def _chunk_text(row: dict[str, Any]) -> str:
    for key in ("embedding_text", "markdown", "text", "content"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _chunk_id(row: dict[str, Any]) -> str:
    return str(row.get("chunk_id") or row.get("id") or "").strip()


def _document_source_id(row: dict[str, Any]) -> str:
    return str(row.get("document_source_id") or "").strip()


def _parsed_document_id(row: dict[str, Any]) -> str:
    return str(row.get("parsed_document_id") or "").strip()


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "t", "true", "yes", "y"}


def is_title_only_user_upload_chunk(row: dict[str, Any]) -> bool:
    text = _compact(_chunk_text(row))
    if not text:
        return True
    if _string_list(row.get("asset_ids")):
        return False
    token_count = len([part for part in text.split(" ") if part.strip()])
    if len(text) > 140 or token_count >= 18:
        return False
    heading_terms = {
        _compact(value).casefold()
        for value in (
            row.get("document_title"),
            row.get("heading_title"),
            row.get("section"),
            *_string_list(row.get("section_path")),
            *_string_list(row.get("toc_path")),
        )
        if _compact(value)
    }
    text_terms = [
        _compact(line).casefold()
        for line in str(_chunk_text(row) or "").splitlines()
        if _compact(line)
    ]
    if text_terms and all(term in heading_terms for term in text_terms):
        return True
    return token_count <= 6 and len(text) < 80


def _sample(row: dict[str, Any], *, reason: str) -> dict[str, Any]:
    return {
        "chunk_id": _chunk_id(row),
        "document_source_id": _document_source_id(row),
        "parsed_document_id": _parsed_document_id(row),
        "document_title": str(row.get("document_title") or ""),
        "heading_title": str(row.get("heading_title") or ""),
        "token_count": _safe_int(row.get("token_count")),
        "reason": reason,
        "preview": _compact(_chunk_text(row))[:240],
    }


def _gate(name: str, passed: bool, detail: str, *, review: bool = False) -> dict[str, str]:
    if passed:
        status = "pass"
    elif review:
        status = "review"
    else:
        status = "fail"
    return {"name": name, "status": status, "detail": detail}


def build_user_upload_quality_audit(
    rows: list[dict[str, Any]],
    *,
    thresholds: AuditThresholds | None = None,
) -> dict[str, Any]:
    thresholds = thresholds or AuditThresholds()
    latest_rows = [row for row in rows if _bool(row.get("is_latest"))]
    stale_rows = [row for row in rows if not _bool(row.get("is_latest"))]
    source_ids = {_document_source_id(row) for row in rows if _document_source_id(row)}
    latest_source_ids = {_document_source_id(row) for row in latest_rows if _document_source_id(row)}
    parsed_ids = {_parsed_document_id(row) for row in rows if _parsed_document_id(row)}
    latest_parsed_ids = {_parsed_document_id(row) for row in latest_rows if _parsed_document_id(row)}

    token_counts: list[int] = []
    issue_counts: Counter[str] = Counter()
    issue_samples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    chunk_type_counts: Counter[str] = Counter()
    document_latest_counts: Counter[str] = Counter()
    missing_embedding_count = 0
    stale_embedding_count = 0
    indexable_count = 0
    empty_embedding_text_count = 0
    raw_markup_embedding_count = 0

    for row in latest_rows:
        chunk_type_counts[str(row.get("chunk_type") or "unknown")] += 1
        document_latest_counts[_document_source_id(row) or "unknown"] += 1
        text = _chunk_text(row)
        token_count = _safe_int(row.get("token_count")) or len(text.split())
        token_counts.append(token_count)
        embedding_text = str(row.get("embedding_text") or "")
        indexed_hash = str(row.get("indexed_embedding_text_hash") or "").strip()
        if not embedding_text.strip():
            empty_embedding_text_count += 1
            issue_counts["empty_embedding_text"] += 1
            if len(issue_samples["empty_embedding_text"]) < 8:
                issue_samples["empty_embedding_text"].append(_sample(row, reason="empty_embedding_text"))
        else:
            indexable_count += 1
            if not indexed_hash:
                missing_embedding_count += 1
                issue_counts["missing_embedding"] += 1
                if len(issue_samples["missing_embedding"]) < 8:
                    issue_samples["missing_embedding"].append(_sample(row, reason="missing_embedding"))
            elif indexed_hash != text_hash(embedding_text):
                stale_embedding_count += 1
                issue_counts["stale_embedding"] += 1
                if len(issue_samples["stale_embedding"]) < 8:
                    issue_samples["stale_embedding"].append(_sample(row, reason="stale_embedding"))
        if RAW_MARKUP_RE.search(embedding_text):
            raw_markup_embedding_count += 1
            issue_counts["raw_markup_embedding"] += 1
            if len(issue_samples["raw_markup_embedding"]) < 8:
                issue_samples["raw_markup_embedding"].append(_sample(row, reason="raw_markup_embedding"))
        if token_count < 18 and len(_compact(text)) < 120:
            issue_counts["undersized_chunk"] += 1
            if len(issue_samples["undersized_chunk"]) < 8:
                issue_samples["undersized_chunk"].append(_sample(row, reason="undersized_chunk"))
        if is_title_only_user_upload_chunk(row):
            issue_counts["title_only_chunk"] += 1
            if len(issue_samples["title_only_chunk"]) < 8:
                issue_samples["title_only_chunk"].append(_sample(row, reason="title_only_chunk"))

    latest_count = len(latest_rows)
    title_only_rate = _ratio(issue_counts.get("title_only_chunk", 0), latest_count)
    undersized_rate = _ratio(issue_counts.get("undersized_chunk", 0), latest_count)
    gates = [
        _gate(
            "latest_upload_documents_present",
            bool(latest_source_ids),
            f"latest_document_sources={len(latest_source_ids)}",
        ),
        _gate(
            "latest_chunks_present",
            latest_count > 0,
            f"latest_chunks={latest_count}",
        ),
        _gate(
            "latest_empty_embedding_text",
            empty_embedding_text_count == 0,
            f"empty_embedding_text={empty_embedding_text_count}",
        ),
        _gate(
            "latest_missing_embeddings",
            missing_embedding_count == 0,
            f"indexable={indexable_count} missing={missing_embedding_count}",
        ),
        _gate(
            "latest_stale_embeddings",
            stale_embedding_count == 0,
            f"stale={stale_embedding_count}",
        ),
        _gate(
            "latest_raw_markup_embedding",
            raw_markup_embedding_count == 0,
            f"raw_markup_embedding={raw_markup_embedding_count}",
        ),
        _gate(
            "title_only_rate",
            title_only_rate <= thresholds.title_only_rate_review,
            f"rate={title_only_rate} threshold={thresholds.title_only_rate_review}",
            review=True,
        ),
        _gate(
            "undersized_rate",
            undersized_rate <= thresholds.undersized_rate_review,
            f"rate={undersized_rate} threshold={thresholds.undersized_rate_review}",
            review=True,
        ),
    ]
    if any(gate["status"] == "fail" for gate in gates):
        decision = "fail"
    elif any(gate["status"] == "review" for gate in gates):
        decision = "review"
    else:
        decision = "pass"

    documents = []
    for source_id, chunk_count in document_latest_counts.most_common():
        source_rows = [row for row in rows if _document_source_id(row) == source_id]
        latest_doc_rows = [row for row in source_rows if _bool(row.get("is_latest"))]
        first = (latest_doc_rows or source_rows or [{}])[0]
        documents.append(
            {
                "document_source_id": source_id,
                "title": str(first.get("document_title") or first.get("filename") or ""),
                "filename": str(first.get("filename") or ""),
                "repository_id": str(first.get("repository_id") or first.get("source_repository_id") or ""),
                "owner_user_id": str(first.get("owner_user_id") or first.get("source_owner_user_id") or ""),
                "latest_chunk_count": int(chunk_count),
                "stale_parse_chunk_count": sum(1 for row in source_rows if not _bool(row.get("is_latest"))),
                "parsed_document_count": len({_parsed_document_id(row) for row in source_rows if _parsed_document_id(row)}),
            }
        )

    return {
        "schema": "pbs_user_upload_quality_audit_v1",
        "generated_at": _now(),
        "row_count": len(rows),
        "document_source_count": len(source_ids),
        "parsed_document_count": len(parsed_ids),
        "latest_document_source_count": len(latest_source_ids),
        "latest_parsed_document_count": len(latest_parsed_ids),
        "all_chunk_count": len(rows),
        "latest_chunk_count": latest_count,
        "stale_parse_chunk_count": len(stale_rows),
        "latest_chunk_ratio": _ratio(latest_count, len(rows)),
        "token_count": {
            "p50": _percentile(token_counts, 0.50),
            "p90": _percentile(token_counts, 0.90),
            "p95": _percentile(token_counts, 0.95),
            "max": max(token_counts or [0]),
        },
        "embedding": {
            "latest_indexable_count": indexable_count,
            "latest_empty_embedding_text_count": empty_embedding_text_count,
            "latest_missing_embedding_count": missing_embedding_count,
            "latest_stale_embedding_count": stale_embedding_count,
            "latest_raw_markup_embedding_count": raw_markup_embedding_count,
        },
        "chunk_type_counts": dict(sorted(chunk_type_counts.items())),
        "issue_counts": dict(sorted(issue_counts.items())),
        "issue_rates": {
            issue: _ratio(count, latest_count)
            for issue, count in sorted(issue_counts.items())
        },
        "issue_samples": dict(issue_samples),
        "documents": documents,
        "gates": gates,
        "decision": decision,
        "decision_detail": (
            "User-upload quality is evaluated against latest parsed document chunks only. "
            "Stale parse chunks may remain in PostgreSQL, but they must stay out of retrieval and embedding candidates."
        ),
    }


def load_user_upload_chunk_rows(
    database_url: str,
    *,
    model: str,
    repository_id: str = "",
    owner_user_id: str = "",
) -> list[dict[str, Any]]:
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH latest_parsed AS (
                    SELECT DISTINCT ON (document_source_id)
                        id,
                        document_source_id
                    FROM parsed_documents
                    ORDER BY document_source_id, created_at DESC, id DESC
                )
                SELECT
                    c.id::text AS chunk_id,
                    c.chunk_key,
                    c.ordinal,
                    c.chunk_type,
                    c.markdown,
                    c.embedding_text,
                    c.token_count,
                    c.section_path,
                    c.section_number,
                    c.heading_title,
                    c.source_anchor,
                    c.toc_path,
                    c.asset_ids,
                    c.repository_id::text AS repository_id,
                    c.owner_user_id,
                    c.visibility,
                    c.source_scope,
                    c.chunk_role,
                    c.navigation_only,
                    c.metadata AS chunk_metadata,
                    pd.id::text AS parsed_document_id,
                    pd.title AS document_title,
                    pd.created_at AS parsed_created_at,
                    ds.id::text AS document_source_id,
                    ds.filename,
                    ds.repository_id::text AS source_repository_id,
                    ds.owner_user_id AS source_owner_user_id,
                    ds.visibility AS source_visibility,
                    ds.source_scope AS source_source_scope,
                    ds.created_by,
                    lp.id::text AS latest_parsed_document_id,
                    (pd.id = lp.id) AS is_latest,
                    ce.embedding_text_hash AS indexed_embedding_text_hash,
                    ce.payload_hash AS indexed_payload_hash
                FROM document_sources ds
                JOIN parsed_documents pd ON pd.document_source_id = ds.id
                JOIN latest_parsed lp ON lp.document_source_id = ds.id
                JOIN document_chunks c ON c.parsed_document_id = pd.id
                LEFT JOIN chunk_embeddings ce ON ce.chunk_id = c.id AND ce.model = %s
                WHERE c.source_scope = 'user_upload'
                  AND (%s = '' OR c.repository_id::text = %s OR ds.repository_id::text = %s)
                  AND (%s = '' OR c.owner_user_id = %s OR ds.owner_user_id = %s OR ds.created_by = %s)
                ORDER BY ds.created_at ASC, pd.created_at ASC, c.ordinal ASC, c.id ASC
                """,
                (
                    model,
                    repository_id,
                    repository_id,
                    repository_id,
                    owner_user_id,
                    owner_user_id,
                    owner_user_id,
                    owner_user_id,
                ),
            )
            return [dict(row) for row in cursor.fetchall()]


def write_markdown_report(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    token = payload.get("token_count") if isinstance(payload.get("token_count"), dict) else {}
    embedding = payload.get("embedding") if isinstance(payload.get("embedding"), dict) else {}
    lines = [
        "# User Upload Quality Audit",
        "",
        f"- Schema: `{payload.get('schema')}`",
        f"- Generated at: `{payload.get('generated_at')}`",
        f"- Decision: `{payload.get('decision')}`",
        f"- Documents latest/all: `{payload.get('latest_document_source_count')}` / `{payload.get('document_source_count')}`",
        f"- Chunks latest/all/stale-parse: `{payload.get('latest_chunk_count')}` / `{payload.get('all_chunk_count')}` / `{payload.get('stale_parse_chunk_count')}`",
        f"- Token p50/p90/p95/max: `{token.get('p50')}` / `{token.get('p90')}` / `{token.get('p95')}` / `{token.get('max')}`",
        f"- Latest embeddings indexable/missing/stale: `{embedding.get('latest_indexable_count')}` / `{embedding.get('latest_missing_embedding_count')}` / `{embedding.get('latest_stale_embedding_count')}`",
        "",
        "## Gates",
        "",
    ]
    for gate in payload.get("gates") or []:
        if isinstance(gate, dict):
            lines.append(f"- `{gate.get('status')}` `{gate.get('name')}`: {gate.get('detail')}")
    lines.extend(["", "## Issue Counts", ""])
    issue_counts = payload.get("issue_counts") if isinstance(payload.get("issue_counts"), dict) else {}
    for issue, count in sorted(issue_counts.items()):
        rate = (payload.get("issue_rates") or {}).get(issue) if isinstance(payload.get("issue_rates"), dict) else None
        lines.append(f"- `{issue}`: `{count}` (`{rate}`)")
    lines.extend(["", "## Documents", ""])
    for doc in payload.get("documents") or []:
        if isinstance(doc, dict):
            lines.append(
                f"- `{doc.get('title') or doc.get('filename')}`: latest `{doc.get('latest_chunk_count')}`, "
                f"stale `{doc.get('stale_parse_chunk_count')}`, parsed `{doc.get('parsed_document_count')}`"
            )
    lines.extend(["", "## Decision Detail", "", str(payload.get("decision_detail") or "")])
    output_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def run_audit(
    *,
    root_dir: Path,
    output_json: Path | None = None,
    output_md: Path | None = None,
    repository_id: str = "",
    owner_user_id: str = "",
    model: str = "",
    thresholds: AuditThresholds | None = None,
) -> dict[str, Any]:
    settings = load_settings(root_dir)
    embedding_model = model or settings.embedding_model
    rows = load_user_upload_chunk_rows(
        settings.database_url,
        model=embedding_model,
        repository_id=repository_id,
        owner_user_id=owner_user_id,
    )
    payload = build_user_upload_quality_audit(rows, thresholds=thresholds)
    payload["root_dir"] = str(root_dir)
    payload["embedding_model"] = embedding_model
    if repository_id:
        payload["repository_id_filter"] = repository_id
    if owner_user_id:
        payload["owner_user_id_filter"] = owner_user_id
    if output_json is not None:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if output_md is not None:
        write_markdown_report(payload, output_md)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit user-upload chunk quality from PostgreSQL.")
    parser.add_argument("--root-dir", default=".", type=Path)
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=None)
    parser.add_argument("--repository-id", default="")
    parser.add_argument("--owner-user-id", default="")
    parser.add_argument("--embedding-model", default="")
    parser.add_argument("--title-only-rate-review", type=float, default=DEFAULT_TITLE_ONLY_RATE_REVIEW)
    parser.add_argument("--undersized-rate-review", type=float, default=DEFAULT_UNDERSIZED_RATE_REVIEW)
    args = parser.parse_args(argv)

    payload = run_audit(
        root_dir=args.root_dir.resolve(),
        output_json=args.output_json,
        output_md=args.output_md,
        repository_id=str(args.repository_id or ""),
        owner_user_id=str(args.owner_user_id or ""),
        model=str(args.embedding_model or ""),
        thresholds=AuditThresholds(
            title_only_rate_review=float(args.title_only_rate_review),
            undersized_rate_review=float(args.undersized_rate_review),
        ),
    )
    print(
        json.dumps(
            {
                "decision": payload.get("decision"),
                "latest_chunk_count": payload.get("latest_chunk_count"),
                "stale_parse_chunk_count": payload.get("stale_parse_chunk_count"),
                "gates": payload.get("gates"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if str(payload.get("decision")) in {"pass", "review"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
