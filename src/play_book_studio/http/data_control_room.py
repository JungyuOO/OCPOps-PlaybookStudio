"""데이터상황실 전용 집계 payload."""

from __future__ import annotations

from collections import Counter
from functools import lru_cache
import hashlib
from pathlib import Path
from typing import Any

from play_book_studio.http.data_control_room_buckets import (
    _build_approved_wiki_runtime_book_bucket,
    _build_buyer_packet_bundle_bucket,
    _build_gold_candidate_book_bucket,
    _build_navigation_backlog_bucket,
    _build_product_gate_bucket,
    _build_product_rehearsal_summary,
    _build_release_candidate_freeze_summary,
    _build_wiki_usage_signal_bucket,
    _iso_now,
    _safe_int,
    _safe_read_json,
)
from play_book_studio.config.settings import load_settings
from play_book_studio.db.official_documents import load_official_manifest_entries
from play_book_studio.intake import CustomerPackDraftStore

from .data_control_room_helpers import (
    _build_high_value_focus,
    _build_known_books_section,
    _build_source_of_truth_drift,
    _candidate_file_rows,
    _candidate_playbook_dirs,
    _grade_label,
    _is_gold_book,
    _job_payload,
    _job_report_path,
    _path_snapshot,
    _path_snapshot_for_optional,
    _resolve_report_path,
    _select_report_candidate,
    _simplify_book,
    _summarize_eval,
)
from .data_control_room_detail import load_customer_pack_private_chunk_rows
from .data_control_room_library import (
    DATA_CONTROL_ROOM_DERIVED_PLAYBOOK_SOURCE_TYPES,
    DATA_CONTROL_ROOM_DERIVED_PLAYBOOK_SOURCE_TYPE_SET,
    OPERATION_PLAYBOOK_SOURCE_TYPE,
    POLICY_OVERLAY_BOOK_SOURCE_TYPE,
    SYNTHESIZED_PLAYBOOK_SOURCE_TYPE,
    TOPIC_PLAYBOOK_SOURCE_TYPE,
    TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE,
    _aggregate_corpus_books,
    _aggregate_playbooks,
    _attach_corpus_status,
    _apply_customer_pack_runtime_truth,
    _apply_viewer_path_fallback,
    _build_manual_book_library,
    _build_playbook_library,
    _derived_family_status,
)


def _path_fingerprint(path: Path | None) -> tuple[str, bool, int, int]:
    if path is None:
        return ("", False, 0, 0)
    target = Path(path).resolve()
    try:
        stat = target.stat()
    except FileNotFoundError:
        return (str(target), False, 0, 0)
    if target.is_dir():
        return _directory_tree_fingerprint(target)
    return (str(target), True, int(stat.st_mtime_ns), int(stat.st_size))


def _directory_tree_fingerprint(target: Path) -> tuple[str, bool, int, int]:
    latest_mtime_ns = 0
    file_count = 0
    digest = hashlib.sha256()
    try:
        children = sorted(target.rglob("*"))
    except OSError:
        return (str(target), False, 0, 0)
    for child in children:
        if not child.is_file():
            continue
        try:
            stat = child.stat()
        except OSError:
            continue
        file_count += 1
        latest_mtime_ns = max(latest_mtime_ns, int(stat.st_mtime_ns))
        rel_path = child.relative_to(target).as_posix()
        digest.update(rel_path.encode("utf-8", errors="ignore"))
        digest.update(b"\0")
        digest.update(str(int(stat.st_mtime_ns)).encode("ascii"))
        digest.update(b":")
        digest.update(str(int(stat.st_size)).encode("ascii"))
        digest.update(b"\n")
    root_stat = target.stat()
    latest_mtime_ns = max(latest_mtime_ns, int(root_stat.st_mtime_ns))
    return (f"{target}#{digest.hexdigest()[:16]}", True, latest_mtime_ns, file_count)


def _database_official_docs_fingerprint(database_url: str) -> tuple[tuple[str, bool, int, int], ...]:
    normalized_url = str(database_url or "").strip()
    if not normalized_url:
        return ()
    try:
        import psycopg

        with psycopg.connect(normalized_url, connect_timeout=2) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    WITH latest_parsed AS (
                        SELECT DISTINCT ON (document_source_id)
                            id,
                            document_source_id,
                            title,
                            metadata,
                            created_at
                        FROM parsed_documents
                        ORDER BY document_source_id, created_at DESC, id DESC
                    ),
                    official_rows AS (
                        SELECT
                            ds.id::text AS source_id,
                            NULLIF(ds.metadata ->> 'book_slug', '') AS book_slug,
                            COALESCE(ds.filename, '') AS filename,
                            COALESCE(ds.source_kind, '') AS source_kind,
                            COALESCE(ds.source_scope, '') AS source_scope,
                            COALESCE(ds.visibility, '') AS visibility,
                            COALESCE(ds.metadata::text, '') AS source_metadata,
                            COALESCE(pd.id::text, '') AS parsed_id,
                            COALESCE(pd.title, '') AS parsed_title,
                            COALESCE(pd.metadata::text, '') AS parsed_metadata,
                            count(dc.id)::bigint AS chunk_count,
                            count(DISTINCT NULLIF(dc.source_anchor, ''))::bigint AS section_count,
                            COALESCE((EXTRACT(EPOCH FROM max(dc.created_at)) * 1000000000)::bigint, 0) AS chunk_max_ns,
                            md5(COALESCE(string_agg(
                                COALESCE(dc.ordinal::text, '') || '|' ||
                                COALESCE(dc.chunk_key, '') || '|' ||
                                COALESCE(dc.source_anchor, '') || '|' ||
                                COALESCE(dc.heading_title, ''),
                                E'\\n'
                                ORDER BY dc.ordinal, dc.id::text
                            ), '')) AS chunk_shape_hash
                        FROM document_sources ds
                        LEFT JOIN latest_parsed pd ON pd.document_source_id = ds.id
                        LEFT JOIN document_chunks dc ON dc.parsed_document_id = pd.id
                        WHERE ds.source_scope = 'official_docs'
                          AND COALESCE(ds.metadata ->> 'book_slug', '') <> ''
                        GROUP BY ds.id, pd.id, pd.title, pd.metadata
                    )
                    SELECT
                        count(*)::bigint AS source_count,
                        count(NULLIF(parsed_id, ''))::bigint AS parsed_count,
                        COALESCE(sum(chunk_count), 0)::bigint AS chunk_count,
                        COALESCE((EXTRACT(EPOCH FROM max(ds.created_at)) * 1000000000)::bigint, 0) AS source_max_ns,
                        COALESCE((EXTRACT(EPOCH FROM max(pd.created_at)) * 1000000000)::bigint, 0) AS parsed_max_ns,
                        COALESCE(max(row_shape.chunk_max_ns), 0)::bigint AS chunk_max_ns,
                        md5(COALESCE(string_agg(
                            source_id || '|' ||
                            COALESCE(book_slug, '') || '|' ||
                            filename || '|' ||
                            source_kind || '|' ||
                            source_scope || '|' ||
                            visibility || '|' ||
                            source_metadata || '|' ||
                            parsed_id || '|' ||
                            parsed_title || '|' ||
                            parsed_metadata || '|' ||
                            chunk_count::text || '|' ||
                            section_count::text || '|' ||
                            chunk_shape_hash,
                            E'\\n'
                            ORDER BY COALESCE(book_slug, ''), source_id
                        ), '')) AS content_hash
                    FROM official_rows row_shape
                    JOIN document_sources ds ON ds.id::text = row_shape.source_id
                    LEFT JOIN parsed_documents pd ON pd.id::text = row_shape.parsed_id
                    """
                )
                row = cursor.fetchone()
    except Exception:  # noqa: BLE001
        return (("postgres:official_docs:fingerprint_unavailable", False, 0, 0),)
    if not row:
        return (("postgres:official_docs:empty", True, 0, 0),)
    source_count, parsed_count, chunk_count, source_max_ns, parsed_max_ns, chunk_max_ns, content_hash = row
    content_digest = str(content_hash or "").strip() or "empty"
    return (
        ("postgres:official_docs:sources", True, int(source_max_ns or 0), int(source_count or 0)),
        ("postgres:official_docs:parsed", True, int(parsed_max_ns or 0), int(parsed_count or 0)),
        ("postgres:official_docs:chunks", True, int(chunk_max_ns or 0), int(chunk_count or 0)),
        (f"postgres:official_docs:shape:{content_digest}", True, int(chunk_max_ns or 0), int(chunk_count or 0)),
    )


def _data_control_room_cache_fingerprint(root: Path) -> tuple[tuple[str, bool, int, int], ...]:
    settings = load_settings(root)
    gate_path = root / "reports" / "build_logs" / "foundry_runs" / "profiles" / "morning_gate" / "latest.json"
    watched_paths = [
        gate_path,
        settings.source_approval_report_path,
        settings.translation_lane_report_path,
        settings.retrieval_eval_report_path,
        settings.answer_eval_report_path,
        settings.ragas_eval_report_path,
        settings.runtime_report_path,
        settings.chunks_path,
        settings.customer_pack_books_dir,
        settings.customer_pack_corpus_dir,
        root / "data" / "wiki_runtime_books",
        root / "data" / "wiki_relations",
        root / "data" / "gold_candidate_books" / "full_rebuild_manifest.json",
        root / "PRODUCT_GATE_SCORECARD.yaml",
        root / "reports" / "build_logs" / "product_rehearsal_report.json",
        root / "reports" / "build_logs" / "buyer_packet_bundle_index.json",
        root / "reports" / "build_logs" / "release_candidate_freeze_packet.json",
        settings.runtime_dir / "served_viewers",
        settings.runtime_dir / "wiki_overlays",
        *settings.normalized_docs_candidates,
        *settings.retrieval_normalized_docs_candidates,
        *settings.playbook_book_dirs,
    ]
    database_url = str(settings.database_url or "").strip()
    if not database_url:
        watched_paths.insert(1, settings.source_manifest_path)
        return tuple(_path_fingerprint(path) for path in watched_paths)
    return (
        *(_path_fingerprint(path) for path in watched_paths),
        *_database_official_docs_fingerprint(database_url),
    )


@lru_cache(maxsize=8)
def _build_data_control_room_payload_cached(
    root_dir: str,
    fingerprint: tuple[tuple[str, bool, int, int], ...],
) -> dict[str, object]:
    del fingerprint
    return _build_data_control_room_payload_uncached(Path(root_dir))


def build_data_control_room_payload(root_dir: str | Path) -> dict[str, object]:
    root = Path(root_dir).resolve()
    fingerprint = _data_control_room_cache_fingerprint(root)
    return _build_data_control_room_payload_cached(str(root), fingerprint)


def _snapshot_exists(snapshot: dict[str, Any]) -> bool:
    return bool(snapshot.get("exists"))


def _build_certification_contract(
    *,
    report_snapshots: dict[str, dict[str, Any]],
    approved_wiki_runtime_books: dict[str, Any],
    canonical_grade_source: dict[str, Any],
) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    required_reports = {
        "morning_gate": "missing_morning_gate_report",
        "source_approval": "missing_source_approval_report",
        "retrieval_eval": "missing_retrieval_eval_report",
        "answer_eval": "missing_answer_eval_report",
        "ragas_eval": "missing_ragas_eval_report",
        "runtime_report": "missing_runtime_report",
    }
    for key, blocker in required_reports.items():
        if not _snapshot_exists(report_snapshots.get(key, {})):
            blockers.append(blocker)
    if not bool(canonical_grade_source.get("exists")):
        blocker = "canonical_grade_source_unavailable"
        if blocker not in blockers:
            blockers.append(blocker)
    recovery_count = int(
        approved_wiki_runtime_books.get("recovery_count")
        or approved_wiki_runtime_books.get("hidden_count")
        or len(approved_wiki_runtime_books.get("hidden_books") or [])
    )
    if recovery_count > 0:
        blockers.append("gold_recovery_items_present")
    certified_count = len(
        [
            book
            for book in approved_wiki_runtime_books.get("books", [])
            if isinstance(book, dict) and bool(book.get("certified_gold", True))
        ]
    )
    if approved_wiki_runtime_books.get("books") and certified_count != len(approved_wiki_runtime_books.get("books") or []):
        warnings.append("runtime_books_include_uncertified_gold")
    status = "certified" if not blockers else "not_certifiable"
    return {
        "status": status,
        "label": "Certified Gold Wiki" if status == "certified" else "Not Certifiable",
        "release_blocking": status != "certified",
        "blockers": blockers,
        "warnings": warnings,
        "gold_certified_count": certified_count,
        "gold_recovery_count": recovery_count,
        "required_reports": {
            key: {
                "exists": _snapshot_exists(report_snapshots.get(key, {})),
                "path": str((report_snapshots.get(key, {}) or {}).get("path") or ""),
            }
            for key in required_reports
        },
        "gold_contract": {
            "rule": "Gold is certified only when the book is readable in the viewer, has sections and chunks, passes Korean language gates, carries source provenance, and passes reader smoke. Failed candidates are Gold Recovery, not Gold.",
            "qdrant_parity_source": "runtime_health.db_corpus.qdrant_index_parity and runtime_health.qdrant_live points/indexed vectors",
        },
    }


def _build_data_control_room_payload_uncached(root_dir: str | Path) -> dict[str, object]:
    root = Path(root_dir).resolve()
    settings = load_settings(root)
    gate_path = root / "reports" / "build_logs" / "foundry_runs" / "profiles" / "morning_gate" / "latest.json"
    gate_report = _safe_read_json(gate_path)
    verdict = gate_report.get("verdict") if isinstance(gate_report.get("verdict"), dict) else {}
    verdict_summary = verdict.get("summary") if isinstance(verdict.get("summary"), dict) else {}
    manifest_entries = _approved_manifest_entries(settings)
    manifest_by_slug = {str(entry.get("book_slug") or "").strip(): entry for entry in manifest_entries if isinstance(entry, dict) and str(entry.get("book_slug") or "").strip()}
    manifest_slugs = set(manifest_by_slug)
    expected_approved_runtime_count = len(manifest_by_slug)
    source_approval_payload = _job_payload(gate_report, "source_approval")
    gate_source_approval_report_path = _resolve_report_path(str(((source_approval_payload.get("output_targets") or {}).get("approval_report_path")) or _job_report_path(gate_report, "source_approval")))
    source_approval_report_path, source_approval_report = _select_report_candidate(gate_source_approval_report_path, settings.source_approval_report_path, summary_key="approved_ko_count", rows_key="books", expected_count=expected_approved_runtime_count)
    source_summary = source_approval_report.get("summary") if isinstance(source_approval_report.get("summary"), dict) else {}
    source_book_count = _safe_int(source_summary.get("book_count") or len(source_approval_report.get("books") or []))
    selected_approved_runtime_count = _safe_int(source_summary.get("approved_ko_count") or verdict_summary.get("approved_runtime_count") or expected_approved_runtime_count)
    gate_translation_lane_path = _resolve_report_path(str(((source_approval_payload.get("output_targets") or {}).get("translation_lane_report_path")) or _job_report_path(gate_report, "synthesis_lane")))
    translation_lane_path, translation_lane_report = _select_report_candidate(gate_translation_lane_path, settings.translation_lane_report_path, summary_key="active_queue_count", rows_key="active_queue", expected_count=max(source_book_count - selected_approved_runtime_count, 0))
    source_bundle_quality_payload = _job_payload(gate_report, "source_bundle_quality")
    retrieval_report = _safe_read_json(settings.retrieval_eval_report_path)
    answer_report = _safe_read_json(settings.answer_eval_report_path)
    ragas_report = _safe_read_json(settings.ragas_eval_report_path)
    runtime_report = _safe_read_json(settings.runtime_report_path)
    runtime_smoke_payload = _job_payload(gate_report, "runtime_smoke")
    source_books = source_approval_report.get("books") if isinstance(source_approval_report.get("books"), list) else []
    known_books = {str(book.get("book_slug") or "").strip(): book for book in source_books if isinstance(book, dict) and str(book.get("book_slug") or "").strip()}
    active_queue = translation_lane_report.get("active_queue") if isinstance(translation_lane_report.get("active_queue"), list) else []
    known_book_rows = _build_known_books_section(source_books, manifest_by_slug=manifest_by_slug)
    active_queue_rows = [_simplify_book(book) for book in active_queue if isinstance(book, dict)]
    high_value_focus = _build_high_value_focus(source_bundle_quality_payload, known_books=known_books, manifest_by_slug=manifest_by_slug)
    selected_chunks_path, chunk_rows, chunk_candidates = _candidate_file_rows(settings.chunks_path, settings.chunks_path)
    selected_playbook_dir, playbook_files, playbook_candidates = _candidate_playbook_dirs(*settings.playbook_book_dirs, expected_count=len(manifest_by_slug))
    customer_pack_files = sorted(settings.customer_pack_books_dir.glob("*.json"))
    customer_pack_draft_records = {record.draft_id: record for record in CustomerPackDraftStore(root).list() if str(record.draft_id or "").strip()}
    customer_pack_corpus_rows = load_customer_pack_private_chunk_rows(root, draft_records_by_id=customer_pack_draft_records)
    all_playbook_files: list[Path] = []
    seen_playbook_paths: set[str] = set()
    for path in [*playbook_files, *customer_pack_files]:
        normalized_path = str(path)
        if normalized_path not in seen_playbook_paths:
            seen_playbook_paths.add(normalized_path)
            all_playbook_files.append(path)
    corpus_books = _aggregate_corpus_books(chunk_rows, manifest_by_slug=manifest_by_slug, known_books=known_books, grade_label=_grade_label)
    manualbooks = _aggregate_playbooks(all_playbook_files, manifest_by_slug=manifest_by_slug, known_books=known_books, grade_label=_grade_label, safe_read_json=_safe_read_json)
    manualbooks = _apply_customer_pack_runtime_truth(manualbooks, draft_records_by_id=customer_pack_draft_records)
    user_library_corpus_books = _aggregate_corpus_books(customer_pack_corpus_rows, manifest_by_slug={}, known_books={}, grade_label=_grade_label)
    user_library_corpus_books = _apply_customer_pack_runtime_truth(user_library_corpus_books, draft_records_by_id=customer_pack_draft_records)
    combined_corpus_by_slug = {
        str(book.get("book_slug") or "").strip(): book
        for book in [*corpus_books, *user_library_corpus_books]
        if str(book.get("book_slug") or "").strip()
    }
    for book in user_library_corpus_books:
        draft_id = str(book.get("draft_id") or "").strip()
        if not draft_id:
            continue
        primary_viewer_path = f"/playbooks/customer-packs/{draft_id}/index.html"
        book_viewer_path = str(book.get("viewer_path") or "").split("#", 1)[0].strip()
        if draft_id not in combined_corpus_by_slug or book_viewer_path == primary_viewer_path:
            combined_corpus_by_slug[draft_id] = book
    manualbooks = _attach_corpus_status(manualbooks, corpus_by_slug=combined_corpus_by_slug)
    derived_playbook_family_statuses = {
        family: _derived_family_status(family, [book for book in manualbooks if str(book.get("source_type") or "").strip() == family])
        for family in DATA_CONTROL_ROOM_DERIVED_PLAYBOOK_SOURCE_TYPES
    }
    derived_playbooks = [book for family in DATA_CONTROL_ROOM_DERIVED_PLAYBOOK_SOURCE_TYPES for book in derived_playbook_family_statuses[family]["books"]]
    core_corpus_books = [book for book in corpus_books if str(book.get("book_slug") or "").strip() in manifest_slugs]
    extra_corpus_books = [book for book in corpus_books if str(book.get("book_slug") or "").strip() not in manifest_slugs]
    topic_playbooks = _apply_viewer_path_fallback(list(derived_playbook_family_statuses[TOPIC_PLAYBOOK_SOURCE_TYPE]["books"]), root=root)
    operation_playbooks = _apply_viewer_path_fallback(list(derived_playbook_family_statuses[OPERATION_PLAYBOOK_SOURCE_TYPE]["books"]), root=root)
    troubleshooting_playbooks = _apply_viewer_path_fallback(list(derived_playbook_family_statuses[TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE]["books"]), root=root)
    policy_overlay_books = _apply_viewer_path_fallback(list(derived_playbook_family_statuses[POLICY_OVERLAY_BOOK_SOURCE_TYPE]["books"]), root=root)
    synthesized_playbooks = _apply_viewer_path_fallback(list(derived_playbook_family_statuses[SYNTHESIZED_PLAYBOOK_SOURCE_TYPE]["books"]), root=root)
    core_manualbooks = [book for book in manualbooks if str(book.get("source_type") or "").strip() not in DATA_CONTROL_ROOM_DERIVED_PLAYBOOK_SOURCE_TYPE_SET and str(book.get("book_slug") or "").strip() in manifest_slugs]
    extra_manualbooks = [book for book in manualbooks if str(book.get("source_type") or "").strip() not in DATA_CONTROL_ROOM_DERIVED_PLAYBOOK_SOURCE_TYPE_SET and str(book.get("book_slug") or "").strip() not in manifest_slugs]
    user_library_books = _apply_viewer_path_fallback([book for book in extra_manualbooks if str(book.get("boundary_truth") or "").strip() == "private_customer_pack_runtime" or str(book.get("source_lane") or "").strip() == "customer_source_first_pack"], root=root)
    customer_pack_runtime_books = _apply_viewer_path_fallback([book for book in manualbooks if str(book.get("boundary_truth") or "").strip() == "private_customer_pack_runtime" or str(book.get("source_lane") or "").strip() == "customer_source_first_pack"], root=root)
    user_library_corpus_chunk_count = sum(int(book.get("chunk_count") or 0) for book in user_library_corpus_books)
    grade_breakdown_counter = Counter(_grade_label(book) for book in source_books)
    gold_books = [_simplify_book(book) for slug in manifest_by_slug for book in [known_books.get(slug)] if isinstance(book, dict) and _is_gold_book(book)]
    materialized_corpus_slugs = {str(row.get("book_slug") or "").strip() for row in chunk_rows if str(row.get("book_slug") or "").strip()}
    materialized_core_corpus_slugs = materialized_corpus_slugs & manifest_slugs
    extra_materialized_corpus_slugs = materialized_corpus_slugs - manifest_slugs
    materialized_topic_playbook_slugs = set(derived_playbook_family_statuses[TOPIC_PLAYBOOK_SOURCE_TYPE]["slugs"])
    materialized_operation_playbook_slugs = set(derived_playbook_family_statuses[OPERATION_PLAYBOOK_SOURCE_TYPE]["slugs"])
    materialized_troubleshooting_playbook_slugs = set(derived_playbook_family_statuses[TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE]["slugs"])
    materialized_policy_overlay_book_slugs = set(derived_playbook_family_statuses[POLICY_OVERLAY_BOOK_SOURCE_TYPE]["slugs"])
    materialized_synthesized_playbook_slugs = set(derived_playbook_family_statuses[SYNTHESIZED_PLAYBOOK_SOURCE_TYPE]["slugs"])
    materialized_derived_playbook_slugs = materialized_topic_playbook_slugs | materialized_operation_playbook_slugs | materialized_troubleshooting_playbook_slugs | materialized_policy_overlay_book_slugs | materialized_synthesized_playbook_slugs
    materialized_manualbook_slugs = {path.stem for path in all_playbook_files if path.stem not in materialized_derived_playbook_slugs}
    materialized_core_manualbook_slugs = materialized_manualbook_slugs & manifest_slugs
    extra_materialized_manualbook_slugs = materialized_manualbook_slugs - manifest_slugs
    buyer_scope = source_bundle_quality_payload.get("buyer_scope") if isinstance(source_bundle_quality_payload.get("buyer_scope"), dict) else {}
    raw_manual_count = int(buyer_scope.get("raw_manual_count") or len(manifest_by_slug))
    playable_asset_count = len(core_manualbooks) + len(extra_manualbooks) + len(derived_playbooks)
    playable_asset_multiplication = {
        "raw_manual_count": raw_manual_count,
        "playable_asset_count": playable_asset_count,
        "delta_vs_raw_manual_count": playable_asset_count - raw_manual_count,
        "ratio_vs_raw_manual_count": round(playable_asset_count / raw_manual_count, 4) if raw_manual_count > 0 else 0.0,
    }
    manual_book_library = _build_manual_book_library(core_manualbooks, extra_manualbooks)
    playbook_library = _build_playbook_library(derived_playbook_family_statuses)
    gold_candidate_books = _build_gold_candidate_book_bucket(root)
    approved_wiki_runtime_books = _build_approved_wiki_runtime_book_bucket(
        root,
        translation_lane_report=translation_lane_report,
        approved_manifest_entries=manifest_entries,
    )
    navigation_backlog = _build_navigation_backlog_bucket(root)
    wiki_usage_signals = _build_wiki_usage_signal_bucket(root)
    product_gate = _build_product_gate_bucket(root)
    product_rehearsal = _build_product_rehearsal_summary(root)
    buyer_packet_bundle = _build_buyer_packet_bundle_bucket(root)
    release_candidate_freeze = _build_release_candidate_freeze_summary(root)
    source_approved_gold_books = gold_books
    gold_books = [
        _simplify_book(book)
        for book in approved_wiki_runtime_books.get("books", [])
        if isinstance(book, dict) and str(book.get("runtime_readable") or "").lower() in {"true", "1"}
    ]
    chunk_candidate_counts = {candidate["row_count"] for candidate in chunk_candidates if candidate.get("exists")}
    playbook_candidate_counts = {candidate["file_count"] for candidate in playbook_candidates if candidate.get("exists")}
    canonical_grade_source = {
        "name": "source_approval_report",
        "path": str(source_approval_report_path or ""),
        "exists": bool(source_approval_report_path and source_approval_report_path.exists()),
        "rule": "Source approval report is the canonical grade source. Release grade is normalized to Gold / Silver / Bronze while raw workflow states remain in content_status, review_status, and translation_status.",
        "summary": source_approval_report.get("summary") if isinstance(source_approval_report.get("summary"), dict) else {},
    }
    source_of_truth_drift = _build_source_of_truth_drift(
        gate_report=gate_report,
        source_approval_report=source_approval_report,
        translation_lane_report=translation_lane_report,
        manifest_path=settings.source_manifest_path,
        selected_chunks_path=selected_chunks_path,
        chunk_candidates=chunk_candidates,
        selected_playbook_dir=selected_playbook_dir,
        playbook_candidates=playbook_candidates,
        source_approval_report_path=source_approval_report_path,
        translation_lane_path=translation_lane_path,
    )
    answer_overall = answer_report.get("overall") if isinstance(answer_report.get("overall"), dict) else {}
    ragas_overall = ragas_report.get("overall") if isinstance(ragas_report.get("overall"), dict) else {}
    runtime_app = runtime_report.get("app") if isinstance(runtime_report.get("app"), dict) else {}
    runtime_runtime = runtime_report.get("runtime") if isinstance(runtime_report.get("runtime"), dict) else {}
    runtime_probes = runtime_report.get("probes") if isinstance(runtime_report.get("probes"), dict) else {}
    report_paths = {
        "gate": str(gate_path),
        "source_approval": str(source_approval_report_path or ""),
        "translation_lane": str(translation_lane_path or ""),
        "retrieval_eval": str(settings.retrieval_eval_report_path),
        "answer_eval": str(settings.answer_eval_report_path),
        "ragas_eval": str(settings.ragas_eval_report_path),
        "runtime": str(settings.runtime_report_path),
    }
    report_snapshots = {
        "morning_gate": _path_snapshot(gate_path),
        "source_approval": _path_snapshot_for_optional(source_approval_report_path),
        "translation_lane": _path_snapshot_for_optional(translation_lane_path),
        "retrieval_eval": _path_snapshot(settings.retrieval_eval_report_path),
        "answer_eval": _path_snapshot(settings.answer_eval_report_path),
        "ragas_eval": _path_snapshot(settings.ragas_eval_report_path),
        "runtime_report": _path_snapshot(settings.runtime_report_path),
    }
    certification = _build_certification_contract(
        report_snapshots=report_snapshots,
        approved_wiki_runtime_books=approved_wiki_runtime_books,
        canonical_grade_source=canonical_grade_source,
    )
    effective_release_blocking = bool(verdict.get("release_blocking")) or bool(certification.get("release_blocking"))
    effective_gate_status = str(verdict.get("status") or "").strip() or "unknown"
    if effective_gate_status == "unknown" and certification.get("status") != "certified":
        effective_gate_status = "not_certifiable"
    effective_gate_reasons = [
        *[str(reason) for reason in list(verdict.get("reasons") or []) if str(reason).strip()],
        *[str(reason) for reason in list(certification.get("blockers") or []) if str(reason).strip()],
    ]
    return {
        "generated_at": _iso_now(),
        "active_pack": {
            "app_id": settings.app_id,
            "app_label": settings.app_label,
            "pack_id": settings.active_pack_id,
            "pack_label": settings.active_pack_label,
            "ocp_version": settings.ocp_version,
            "docs_language": settings.docs_language,
            "viewer_path_prefix": settings.viewer_path_prefix,
        },
        "summary": {
            "gate_status": effective_gate_status,
            "certification_status": str(certification.get("status") or "unknown"),
            "certification_blocker_count": len(certification.get("blockers") or []),
            "gold_recovery_count": int(certification.get("gold_recovery_count") or 0),
            "release_blocking": effective_release_blocking,
            "approved_runtime_count": selected_approved_runtime_count,
            "known_book_count": int(source_approval_report.get("summary", {}).get("book_count") or len(source_books)),
            "gold_book_count": len(gold_books),
            "known_books_count": len(known_book_rows),
            "queue_count": len(active_queue_rows),
            "active_queue_count": len(active_queue_rows),
            "high_value_focus_count": int(high_value_focus.get("count") or 0),
            "blocked_count": int(source_approval_report.get("summary", {}).get("blocked_count") or 0),
            "raw_manual_count": raw_manual_count,
            "chunk_count": len(chunk_rows),
            "corpus_book_count": len(materialized_core_corpus_slugs),
            "core_corpus_book_count": len(materialized_core_corpus_slugs),
            "manualbook_count": len(materialized_core_manualbook_slugs),
            "core_manualbook_count": len(materialized_core_manualbook_slugs),
            "customer_pack_runtime_book_count": len(customer_pack_runtime_books),
            "user_library_book_count": len(user_library_books),
            "user_library_corpus_book_count": len(user_library_corpus_books),
            "user_library_corpus_chunk_count": user_library_corpus_chunk_count,
            "gold_candidate_book_count": len(gold_candidate_books.get("books") or []),
            "approved_wiki_runtime_book_count": len(approved_wiki_runtime_books.get("books") or []),
            "wiki_navigation_backlog_count": len(navigation_backlog.get("books") or []),
            "wiki_usage_signal_count": len(wiki_usage_signals.get("books") or []),
            "product_gate_count": len(product_gate.get("books") or []),
            "buyer_packet_bundle_count": len(buyer_packet_bundle.get("books") or []),
            "release_candidate_freeze_ready": bool(release_candidate_freeze.get("exists")),
            "product_gate_pass_rate": product_rehearsal.get("critical_scenario_pass_rate"),
            "topic_playbook_count": len(topic_playbooks),
            "operation_playbook_count": len(operation_playbooks),
            "troubleshooting_playbook_count": len(troubleshooting_playbooks),
            "policy_overlay_book_count": len(policy_overlay_books),
            "synthesized_playbook_count": len(synthesized_playbooks),
            "derived_playbook_count": len(derived_playbooks),
            "playable_asset_count": playable_asset_count,
            "extra_corpus_book_count": len(extra_materialized_corpus_slugs),
            "extra_manualbook_count": len(extra_materialized_manualbook_slugs),
            "retrieval_hit_at_1": retrieval_report.get("overall", {}).get("book_hit_at_1"),
            "answer_pass_rate": answer_overall.get("pass_rate"),
            "citation_precision": answer_overall.get("avg_citation_precision"),
            "ragas_faithfulness": ragas_overall.get("faithfulness"),
            "canonical_grade_source": canonical_grade_source["name"],
        },
        "gate": {
            "path": str(gate_path),
            "run_at": str(gate_report.get("run_at") or ""),
            "status": effective_gate_status,
            "release_blocking": effective_release_blocking,
            "reasons": effective_gate_reasons,
            "summary": {
                "approved_runtime_count": int(verdict_summary.get("approved_runtime_count") or len(manifest_by_slug)),
                "translation_ready_count": int(verdict_summary.get("translation_ready_count") or 0),
                "manual_review_ready_count": int(verdict_summary.get("manual_review_ready_count") or 0),
                "high_value_issue_count": int(verdict_summary.get("high_value_issue_count") or 0),
                "source_expansion_needed_count": int(verdict_summary.get("source_expansion_needed_count") or 0),
                "failed_validation_checks": list(verdict_summary.get("failed_validation_checks") or []),
                "failed_data_quality_checks": list(verdict_summary.get("failed_data_quality_checks") or []),
            },
        },
        "grading": {
            "summary": source_approval_report.get("summary") if isinstance(source_approval_report.get("summary"), dict) else {},
            "grade_breakdown": [{"grade": grade, "count": count} for grade, count in sorted(grade_breakdown_counter.items(), key=lambda item: (-item[1], item[0]))],
            "gold_books": gold_books,
            "source_approved_gold_books": source_approved_gold_books,
            "queue_books": active_queue_rows,
        },
        "evaluations": {
            "retrieval": {**_summarize_eval(retrieval_report), "path": str(settings.retrieval_eval_report_path)},
            "answer": {**_summarize_eval(answer_report), "path": str(settings.answer_eval_report_path)},
            "ragas": {**_summarize_eval(ragas_report), "path": str(settings.ragas_eval_report_path)},
            "runtime": {"path": str(settings.runtime_report_path), "app": runtime_app, "runtime": runtime_runtime, "probes": runtime_probes, "latest_smoke": runtime_smoke_payload},
        },
        "source_of_truth": {
            "artifacts_dir": str(settings.artifacts_dir),
            "manifest": _path_snapshot(settings.source_manifest_path),
            "chunks": {"selected_path": str(selected_chunks_path) if selected_chunks_path else "", "candidates": chunk_candidates, "drift_detected": len(chunk_candidate_counts) > 1},
            "playbooks": {"selected_dir": str(selected_playbook_dir) if selected_playbook_dir else "", "candidates": playbook_candidates, "drift_detected": len(playbook_candidate_counts) > 1},
        },
        "canonical_grade_source": canonical_grade_source,
        "certification": certification,
        "source_of_truth_drift": source_of_truth_drift,
        "corpus": {"selected_path": str(selected_chunks_path) if selected_chunks_path else "", "books": core_corpus_books},
        "manualbooks": {"selected_dir": str(selected_playbook_dir) if selected_playbook_dir else "", "books": core_manualbooks},
        "customer_pack_runtime_books": {"selected_dir": str(settings.customer_pack_books_dir.resolve()), "books": customer_pack_runtime_books},
        "user_library_books": {"selected_dir": str(settings.customer_pack_books_dir.resolve()), "books": user_library_books},
        "user_library_corpus": {"selected_dir": str(settings.customer_pack_corpus_dir.resolve()), "books": user_library_corpus_books},
        "gold_candidate_books": gold_candidate_books,
        "approved_wiki_runtime_books": approved_wiki_runtime_books,
        "wiki_navigation_backlog": navigation_backlog,
        "wiki_usage_signals": wiki_usage_signals,
        "product_gate": product_gate,
        "buyer_packet_bundle": buyer_packet_bundle,
        "release_candidate_freeze": release_candidate_freeze,
        "product_rehearsal": product_rehearsal,
        "manual_book_library": manual_book_library,
        "topic_playbooks": {"selected_dir": str(selected_playbook_dir) if selected_playbook_dir else "", "books": topic_playbooks},
        "operation_playbooks": {"selected_dir": str(selected_playbook_dir) if selected_playbook_dir else "", "books": operation_playbooks},
        "troubleshooting_playbooks": {"selected_dir": str(selected_playbook_dir) if selected_playbook_dir else "", "books": troubleshooting_playbooks},
        "policy_overlay_books": {"selected_dir": str(selected_playbook_dir) if selected_playbook_dir else "", "books": policy_overlay_books},
        "synthesized_playbooks": {"selected_dir": str(selected_playbook_dir) if selected_playbook_dir else "", "books": synthesized_playbooks},
        "derived_playbook_families": derived_playbook_family_statuses,
        "playbook_library": playbook_library,
        "materialization": {
            "manifest_book_count": len(manifest_by_slug),
            "gold_book_count": len(gold_books),
            "corpus_book_count": len(core_corpus_books),
            "core_corpus_book_count": len(core_corpus_books),
            "manualbook_book_count": len(core_manualbooks),
            "core_manualbook_book_count": len(core_manualbooks),
            "customer_pack_runtime_book_count": len(customer_pack_runtime_books),
            "user_library_book_count": len(user_library_books),
            "user_library_corpus_book_count": len(user_library_corpus_books),
            "user_library_corpus_chunk_count": user_library_corpus_chunk_count,
            "topic_playbook_book_count": len(topic_playbooks),
            "operation_playbook_book_count": len(operation_playbooks),
            "troubleshooting_playbook_book_count": len(troubleshooting_playbooks),
            "policy_overlay_book_book_count": len(policy_overlay_books),
            "synthesized_playbook_book_count": len(synthesized_playbooks),
            "derived_playbook_book_count": len(derived_playbooks),
            "playable_asset_count": playable_asset_count,
            "playable_asset_multiplication": playable_asset_multiplication,
            "extra_corpus_book_count": len(extra_corpus_books),
            "extra_manualbook_book_count": len(extra_manualbooks),
            "materialized_corpus_book_count": len(materialized_core_corpus_slugs),
            "materialized_manualbook_book_count": len(materialized_core_manualbook_slugs),
            "materialized_topic_playbook_count": len(materialized_topic_playbook_slugs),
            "materialized_operation_playbook_count": len(materialized_operation_playbook_slugs),
            "materialized_troubleshooting_playbook_count": len(materialized_troubleshooting_playbook_slugs),
            "materialized_policy_overlay_book_count": len(materialized_policy_overlay_book_slugs),
            "materialized_synthesized_playbook_count": len(materialized_synthesized_playbook_slugs),
            "materialized_derived_playbook_count": len(materialized_derived_playbook_slugs),
            "extra_corpus_books": sorted(extra_materialized_corpus_slugs),
            "extra_manualbook_books": sorted(extra_materialized_manualbook_slugs),
            "missing_corpus_books": sorted(manifest_slugs - materialized_core_corpus_slugs),
            "missing_manualbook_books": sorted(manifest_slugs - materialized_core_manualbook_slugs),
            "logical_counts_match": len(manifest_by_slug) == len(core_corpus_books) == len(core_manualbooks),
            "counts_match": len(manifest_by_slug) == len(gold_books) == len(materialized_core_corpus_slugs) == len(materialized_core_manualbook_slugs),
        },
        "known_books": known_book_rows,
        "active_queue": active_queue_rows,
        "high_value_focus": high_value_focus,
        "report_paths": report_paths,
        "gold_books": gold_books,
        "corpus_book_status": core_corpus_books,
        "extra_corpus_book_status": extra_corpus_books,
        "manualbook_status": core_manualbooks,
        "extra_manualbook_status": extra_manualbooks,
        "user_library_corpus_status": user_library_corpus_books,
        "topic_playbook_status": topic_playbooks,
        "operation_playbook_status": operation_playbooks,
        "troubleshooting_playbook_status": troubleshooting_playbooks,
        "policy_overlay_book_status": policy_overlay_books,
        "synthesized_playbook_status": synthesized_playbooks,
        "recent_report_paths": report_snapshots,
        "reports": {
            "gate": {"status": effective_gate_status, "summary": verdict_summary},
            "source_approval": {"path": str(source_approval_report_path or ""), "summary": source_approval_report.get("summary") if isinstance(source_approval_report.get("summary"), dict) else {}},
            "translation_lane": {"path": str(translation_lane_path or ""), "summary": translation_lane_report.get("summary") if isinstance(translation_lane_report.get("summary"), dict) else {}},
            "retrieval": _summarize_eval(retrieval_report),
            "answer": _summarize_eval(answer_report),
            "ragas": _summarize_eval(ragas_report),
            "runtime": runtime_smoke_payload,
        },
    }


def _approved_manifest_entries(settings: object) -> list[dict[str, object]]:
    database_url = str(getattr(settings, "database_url", "") or "").strip()
    if database_url:
        return load_official_manifest_entries(database_url)
    manifest = _safe_read_json(settings.source_manifest_path)
    entries = manifest.get("entries") if isinstance(manifest.get("entries"), list) else []
    return [entry for entry in entries if isinstance(entry, dict)]


__all__ = ["build_data_control_room_payload"]
