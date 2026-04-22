# ingestion 산출물이 최소 계약을 만족하는지 검사하는 validator.
from __future__ import annotations

import json
import re
from collections import Counter

import requests

from play_book_studio.config.settings import Settings

from .manifest import read_manifest
from .topic_playbooks import build_expected_derived_playbook_outputs


HANGUL_RE = re.compile(r"[가-힣]")
NOISE_SECTION_RE = re.compile(r"^Legal Notice$", re.IGNORECASE)
REQUIRED_SECTION_KEYS = {
    "book_slug",
    "book_title",
    "heading",
    "section_level",
    "section_path",
    "anchor",
    "source_url",
    "viewer_path",
    "text",
}
REQUIRED_CHUNK_KEYS = {
    "chunk_id",
    "book_slug",
    "book_title",
    "chapter",
    "section",
    "anchor",
    "source_url",
    "viewer_path",
    "text",
    "token_count",
    "ordinal",
}
REQUIRED_BM25_KEYS = {
    "chunk_id",
    "book_slug",
    "chapter",
    "section",
    "anchor",
    "source_url",
    "viewer_path",
    "text",
}
REQUIRED_MANIFEST_METADATA_FIELDS = (
    "source_id",
    "source_lane",
    "source_collection",
    "original_title",
    "legal_notice_url",
    "license_or_terms",
    "review_status",
    "updated_at",
)
REQUIRED_MANIFEST_SECURITY_FIELDS = (
    "tenant_id",
    "workspace_id",
    "pack_id",
    "pack_version",
    "bundle_scope",
    "classification",
    "access_groups",
    "provider_egress_policy",
    "approval_state",
    "publication_state",
)
REQUIRED_ROW_METADATA_FIELDS = (
    "source_id",
    "source_lane",
    "source_type",
    "source_collection",
    "original_title",
    "legal_notice_url",
    "license_or_terms",
    "review_status",
    "updated_at",
)
REQUIRED_ROW_PARSED_FIELDS = ("parsed_artifact_id",)
REQUIRED_ROW_SECURITY_FIELDS = (
    "tenant_id",
    "workspace_id",
    "parent_pack_id",
    "pack_version",
    "bundle_scope",
    "classification",
    "access_groups",
    "provider_egress_policy",
    "approval_state",
    "publication_state",
    "redaction_state",
)
REQUIRED_PLAYBOOK_SOURCE_METADATA_FIELDS = (
    "source_id",
    "source_type",
    "source_lane",
    "source_collection",
    "product",
    "version",
    "trust_score",
    "original_url",
    "original_title",
    "legal_notice_url",
    "license_or_terms",
    "review_status",
    "verifiability",
    "updated_at",
)
REQUIRED_PLAYBOOK_SOURCE_PARSED_FIELDS = ("parsed_artifact_id",)
REQUIRED_PLAYBOOK_SOURCE_SECURITY_FIELDS = (
    "tenant_id",
    "workspace_id",
    "pack_id",
    "pack_version",
    "bundle_scope",
    "classification",
    "access_groups",
    "provider_egress_policy",
    "approval_state",
    "publication_state",
    "redaction_state",
)


def read_jsonl(path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _read_jsonl_safe(path) -> list[dict]:
    if path is None or not path.exists():
        return []
    return read_jsonl(path)


def _is_missing_metadata(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _missing_metadata_summary(
    rows: list[dict[str, object]],
    required_fields: tuple[str, ...],
) -> tuple[int, dict[str, int]]:
    missing_rows = 0
    missing_by_field: Counter[str] = Counter()
    for row in rows:
        row_missing = False
        for field_name in required_fields:
            if _is_missing_metadata(row.get(field_name)):
                missing_by_field[field_name] += 1
                row_missing = True
        if row_missing:
            missing_rows += 1
    return missing_rows, dict(missing_by_field)


def _text_has_hangul(text: str) -> bool:
    return bool(HANGUL_RE.search(text))


def _expected_subset_slugs(manifest, subset: str) -> list[str]:
    if subset == "high-value":
        return [entry.book_slug for entry in manifest if entry.high_value]
    return [entry.book_slug for entry in manifest]


def qdrant_count(base_url: str, collection: str, timeout: int) -> int | None:
    try:
        response = requests.post(
            f"{base_url}/collections/{collection}/points/count",
            json={"exact": True},
            timeout=timeout,
        )
        if not response.ok:
            return None
        return int(response.json()["result"]["count"])
    except Exception:  # noqa: BLE001
        return None


def qdrant_id_inventory(
    base_url: str,
    collection: str,
    timeout: int,
) -> tuple[set[str] | None, Counter[str] | None]:
    try:
        point_ids: set[str] = set()
        book_counts: Counter[str] = Counter()
        offset = None
        while True:
            payload: dict[str, object] = {
                "limit": 256,
                "with_payload": True,
                "with_vector": False,
            }
            if offset is not None:
                payload["offset"] = offset
            response = requests.post(
                f"{base_url}/collections/{collection}/points/scroll",
                json=payload,
                timeout=max(timeout, 30),
            )
            response.raise_for_status()
            result = response.json()["result"]
            for point in result["points"]:
                point_ids.add(str(point["id"]))
                payload_row = point.get("payload") or {}
                book_slug = payload_row.get("book_slug")
                if book_slug:
                    book_counts[str(book_slug)] += 1
            offset = result.get("next_page_offset")
            if offset is None:
                break
        return point_ids, book_counts
    except Exception:  # noqa: BLE001
        return None, None


def build_validation_report(
    settings: Settings,
    *,
    expected_process_subset: str = "high-value",
    artifact_expectation_mode: str = "runtime_baseline",
    include_qdrant_id_check: bool = True,
) -> dict:
    manifest_payload = json.loads(settings.source_manifest_path.read_text(encoding="utf-8"))
    manifest_rows = list(manifest_payload.get("entries", []))
    manifest = read_manifest(settings.source_manifest_path)
    expected_source_slugs = _expected_subset_slugs(manifest, expected_process_subset)
    expected_source_slug_set = set(expected_source_slugs)
    expected_derived_outputs = build_expected_derived_playbook_outputs(settings)
    expected_derived_slugs = list(expected_derived_outputs.get("generated_slugs", []))
    if artifact_expectation_mode == "source_subset":
        expected_artifact_slug_set = set(expected_source_slugs)
    else:
        expected_artifact_slug_set = set(expected_source_slugs) | set(expected_derived_slugs)

    raw_html_files = sorted(settings.raw_html_dir.glob("*.html"))
    raw_html_slugs = {path.stem for path in raw_html_files}
    normalized_docs = read_jsonl(settings.normalized_docs_path)
    chunks = read_jsonl(settings.chunks_path)
    bm25_rows = read_jsonl(settings.bm25_corpus_path)
    playbook_rows = _read_jsonl_safe(getattr(settings, "playbook_documents_path", None))

    normalized_book_counts = Counter(str(row["book_slug"]) for row in normalized_docs)
    chunk_book_counts = Counter(str(row["book_slug"]) for row in chunks)
    bm25_book_counts = Counter(str(row["book_slug"]) for row in bm25_rows)
    playbook_book_counts = Counter(str(row["book_slug"]) for row in playbook_rows)
    normalized_book_set = set(normalized_book_counts)
    chunk_book_set = set(chunk_book_counts)
    bm25_book_set = set(bm25_book_counts)
    playbook_book_set = set(playbook_book_counts)

    manifest_missing_rows, manifest_missing_by_field = _missing_metadata_summary(
        manifest_rows,
        REQUIRED_MANIFEST_METADATA_FIELDS,
    )
    manifest_security_missing_rows, manifest_security_missing_by_field = _missing_metadata_summary(
        manifest_rows,
        REQUIRED_MANIFEST_SECURITY_FIELDS,
    )
    normalized_missing_rows, normalized_missing_by_field = _missing_metadata_summary(
        normalized_docs,
        REQUIRED_ROW_METADATA_FIELDS,
    )
    normalized_parsed_missing_rows, normalized_parsed_missing_by_field = _missing_metadata_summary(
        normalized_docs,
        REQUIRED_ROW_PARSED_FIELDS,
    )
    normalized_security_missing_rows, normalized_security_missing_by_field = _missing_metadata_summary(
        normalized_docs,
        REQUIRED_ROW_SECURITY_FIELDS,
    )
    chunk_missing_rows, chunk_missing_by_field = _missing_metadata_summary(
        chunks,
        REQUIRED_ROW_METADATA_FIELDS,
    )
    chunk_parsed_missing_rows, chunk_parsed_missing_by_field = _missing_metadata_summary(
        chunks,
        REQUIRED_ROW_PARSED_FIELDS,
    )
    chunk_security_missing_rows, chunk_security_missing_by_field = _missing_metadata_summary(
        chunks,
        REQUIRED_ROW_SECURITY_FIELDS,
    )
    playbook_top_missing_rows, playbook_top_missing_by_field = _missing_metadata_summary(
        playbook_rows,
        ("legal_notice_url", "review_status"),
    )
    playbook_source_metadata_rows = [
        dict(row.get("source_metadata", {})) for row in playbook_rows
    ]
    playbook_source_missing_rows, playbook_source_missing_by_field = _missing_metadata_summary(
        playbook_source_metadata_rows,
        REQUIRED_PLAYBOOK_SOURCE_METADATA_FIELDS,
    )
    playbook_source_parsed_missing_rows, playbook_source_parsed_missing_by_field = _missing_metadata_summary(
        playbook_source_metadata_rows,
        REQUIRED_PLAYBOOK_SOURCE_PARSED_FIELDS,
    )
    playbook_source_security_missing_rows, playbook_source_security_missing_by_field = _missing_metadata_summary(
        playbook_source_metadata_rows,
        REQUIRED_PLAYBOOK_SOURCE_SECURITY_FIELDS,
    )
    playbook_missing_rows = sum(
        1
        for row in playbook_rows
        if _is_missing_metadata(row.get("legal_notice_url"))
        or _is_missing_metadata(row.get("review_status"))
        or any(
            _is_missing_metadata(dict(row.get("source_metadata", {})).get(field_name))
            for field_name in REQUIRED_PLAYBOOK_SOURCE_METADATA_FIELDS
        )
        or any(
            _is_missing_metadata(dict(row.get("source_metadata", {})).get(field_name))
            for field_name in REQUIRED_PLAYBOOK_SOURCE_PARSED_FIELDS
        )
        or any(
            _is_missing_metadata(dict(row.get("source_metadata", {})).get(field_name))
            for field_name in REQUIRED_PLAYBOOK_SOURCE_SECURITY_FIELDS
        )
    )
    parsed_lineage_missing_rows = (
        normalized_parsed_missing_rows
        + chunk_parsed_missing_rows
        + playbook_source_parsed_missing_rows
    )
    security_boundary_missing_rows = (
        manifest_security_missing_rows
        + normalized_security_missing_rows
        + chunk_security_missing_rows
        + playbook_source_security_missing_rows
    )

    section_key_errors = sum(
        1 for row in normalized_docs if not REQUIRED_SECTION_KEYS.issubset(row)
    )
    chunk_key_errors = sum(1 for row in chunks if not REQUIRED_CHUNK_KEYS.issubset(row))
    bm25_key_errors = sum(1 for row in bm25_rows if not REQUIRED_BM25_KEYS.issubset(row))
    empty_chunk_texts = sum(1 for row in chunks if not str(row["text"]).strip())

    chunk_ids = [str(row["chunk_id"]) for row in chunks]
    chunk_id_set = set(chunk_ids)
    unique_chunk_ids = len(chunk_id_set)
    bm25_id_set = {str(row["chunk_id"]) for row in bm25_rows}
    missing_bm25_ids = len(chunk_id_set - bm25_id_set)

    qdrant_points = qdrant_count(
        settings.qdrant_url,
        settings.qdrant_collection,
        settings.request_timeout_seconds,
    )
    qdrant_ids: set[str] | None = None
    qdrant_book_counts: Counter[str] | None = None
    if include_qdrant_id_check and qdrant_points is not None:
        qdrant_ids, qdrant_book_counts = qdrant_id_inventory(
            settings.qdrant_url,
            settings.qdrant_collection,
            settings.request_timeout_seconds,
        )

    hangul_sections = sum(1 for row in normalized_docs if _text_has_hangul(str(row["text"])))
    hangul_chunks = sum(1 for row in chunks if _text_has_hangul(str(row["text"])))

    per_book_section_totals: Counter[str] = Counter()
    per_book_hangul_sections: Counter[str] = Counter()
    for row in normalized_docs:
        book_slug = str(row["book_slug"])
        per_book_section_totals[book_slug] += 1
        if _text_has_hangul(str(row["text"])):
            per_book_hangul_sections[book_slug] += 1

    low_hangul_books: list[dict[str, object]] = []
    for book_slug in sorted(chunk_book_set):
        total_sections = per_book_section_totals.get(book_slug, 0)
        if total_sections == 0:
            continue
        hangul_ratio = round(
            per_book_hangul_sections.get(book_slug, 0) / total_sections,
            4,
        )
        if hangul_ratio < 0.5:
            low_hangul_books.append(
                {
                    "book_slug": book_slug,
                    "hangul_section_ratio": hangul_ratio,
                    "section_count": total_sections,
                    "chunk_count": chunk_book_counts.get(book_slug, 0),
                }
            )

    legal_sections = sum(
        1 for row in normalized_docs if NOISE_SECTION_RE.match(str(row["heading"]).strip())
    )
    legal_chunks = sum(
        1 for row in chunks if NOISE_SECTION_RE.match(str(row["section"]).strip())
    )

    missing_expected_books = sorted(expected_artifact_slug_set - chunk_book_set)
    unexpected_books = sorted(chunk_book_set - expected_artifact_slug_set)

    qdrant_missing_ids = None
    qdrant_extra_ids = None
    qdrant_books_match_chunks = None
    if qdrant_ids is not None:
        qdrant_missing_ids = len(chunk_id_set - qdrant_ids)
        qdrant_extra_ids = len(qdrant_ids - chunk_id_set)
    if qdrant_book_counts is not None:
        qdrant_books_match_chunks = dict(qdrant_book_counts) == dict(chunk_book_counts)

    return {
        "expected_process_subset": expected_process_subset,
        "artifact_expectation_mode": artifact_expectation_mode,
        "manifest_count": len(manifest),
        "manifest_high_value_count": sum(1 for entry in manifest if entry.high_value),
        "expected_book_count": len(expected_artifact_slug_set),
        "expected_source_book_count": len(expected_source_slug_set),
        "expected_derived_book_count": len(expected_derived_slugs),
        "raw_html_count": len(raw_html_files),
        "raw_html_expected_subset_count": len(raw_html_slugs & expected_source_slug_set),
        "normalized_doc_count": len(normalized_docs),
        "normalized_book_count": len(normalized_book_set),
        "chunk_count": len(chunks),
        "chunk_book_count": len(chunk_book_set),
        "bm25_row_count": len(bm25_rows),
        "bm25_book_count": len(bm25_book_set),
        "playbook_document_count": len(playbook_rows),
        "playbook_book_count": len(playbook_book_set),
        "qdrant_count": qdrant_points,
        "qdrant_missing_ids": qdrant_missing_ids,
        "qdrant_extra_ids": qdrant_extra_ids,
        "section_key_errors": section_key_errors,
        "chunk_key_errors": chunk_key_errors,
        "bm25_key_errors": bm25_key_errors,
        "empty_chunk_texts": empty_chunk_texts,
        "unique_chunk_ids": unique_chunk_ids,
        "duplicate_chunk_ids": len(chunks) - unique_chunk_ids,
        "missing_bm25_ids": missing_bm25_ids,
        "hangul_section_ratio": round(hangul_sections / max(len(normalized_docs), 1), 4),
        "hangul_chunk_ratio": round(hangul_chunks / max(len(chunks), 1), 4),
        "legal_notice_sections": legal_sections,
        "legal_notice_chunks": legal_chunks,
        "missing_expected_books": missing_expected_books,
        "expected_derived_missing_sources": list(expected_derived_outputs.get("missing_sources", [])),
        "unexpected_books": unexpected_books,
        "low_hangul_books": low_hangul_books,
        "manifest_missing_metadata_rows": manifest_missing_rows,
        "manifest_security_missing_rows": manifest_security_missing_rows,
        "normalized_missing_metadata_rows": normalized_missing_rows,
        "normalized_parsed_missing_rows": normalized_parsed_missing_rows,
        "normalized_security_missing_rows": normalized_security_missing_rows,
        "chunk_missing_metadata_rows": chunk_missing_rows,
        "chunk_parsed_missing_rows": chunk_parsed_missing_rows,
        "chunk_security_missing_rows": chunk_security_missing_rows,
        "playbook_missing_metadata_rows": playbook_missing_rows,
        "playbook_source_parsed_missing_rows": playbook_source_parsed_missing_rows,
        "playbook_source_security_missing_rows": playbook_source_security_missing_rows,
        "parsed_lineage_missing_rows": parsed_lineage_missing_rows,
        "security_boundary_missing_rows": security_boundary_missing_rows,
        "metadata_missing_by_field": {
            "manifest": manifest_missing_by_field,
            "manifest_security": manifest_security_missing_by_field,
            "normalized": normalized_missing_by_field,
            "normalized_parsed": normalized_parsed_missing_by_field,
            "normalized_security": normalized_security_missing_by_field,
            "chunks": chunk_missing_by_field,
            "chunks_parsed": chunk_parsed_missing_by_field,
            "chunks_security": chunk_security_missing_by_field,
            "playbook": {
                "top_level": playbook_top_missing_by_field,
                "source_metadata": playbook_source_missing_by_field,
                "source_parsed": playbook_source_parsed_missing_by_field,
                "source_security": playbook_source_security_missing_by_field,
            },
        },
        "checks": {
            "raw_html_covers_expected_subset": len(raw_html_slugs & expected_source_slug_set) == len(expected_source_slug_set),
            "artifact_books_match_expected_subset": (
                normalized_book_set == expected_artifact_slug_set
                and chunk_book_set == expected_artifact_slug_set
                and bm25_book_set == expected_artifact_slug_set
                and playbook_book_set == expected_artifact_slug_set
            ),
            "chunks_have_unique_ids": unique_chunk_ids == len(chunks),
            "bm25_matches_chunks": len(bm25_rows) == len(chunks) and missing_bm25_ids == 0,
            "qdrant_matches_chunks_by_count": qdrant_points == len(chunks),
            "qdrant_matches_chunks_by_ids": (
                qdrant_missing_ids == 0 and qdrant_extra_ids == 0
                if qdrant_missing_ids is not None and qdrant_extra_ids is not None
                else None
            ),
            "qdrant_books_match_chunks": qdrant_books_match_chunks,
            "required_keys_present": (
                section_key_errors == 0
                and chunk_key_errors == 0
                and bm25_key_errors == 0
            ),
            "manifest_metadata_complete": manifest_missing_rows == 0,
            "normalized_metadata_complete": normalized_missing_rows == 0,
            "chunk_metadata_complete": chunk_missing_rows == 0,
            "playbook_metadata_complete": (
                playbook_missing_rows == 0
                and playbook_top_missing_rows == 0
                and playbook_source_missing_rows == 0
            ),
            "parsed_lineage_complete": parsed_lineage_missing_rows == 0,
            "security_boundary_complete": security_boundary_missing_rows == 0,
            "provenance_metadata_complete": (
                manifest_missing_rows == 0
                and normalized_missing_rows == 0
                and chunk_missing_rows == 0
                and playbook_missing_rows == 0
                and parsed_lineage_missing_rows == 0
                and security_boundary_missing_rows == 0
            ),
            "no_empty_chunk_texts": empty_chunk_texts == 0,
            "no_legal_notice_chunks": legal_chunks == 0,
        },
    }
