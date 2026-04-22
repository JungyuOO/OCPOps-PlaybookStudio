"""번역 draft 산출물을 Gold manual_synthesis로 승격한다."""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from play_book_studio.config.settings import Settings
from play_book_studio.ingestion.validation import (
    REQUIRED_PLAYBOOK_SOURCE_METADATA_FIELDS,
    REQUIRED_ROW_METADATA_FIELDS,
    read_jsonl,
)

from .audit_rules import hangul_ratio
from .data_quality import build_playbook_reader_grade_audit_for_dirs
from .embedding import EmbeddingClient
from .graph_sidecar import (
    graph_sidecar_compact_artifact_status,
    refresh_active_runtime_graph_artifacts,
)
from .manifest import read_manifest, write_manifest
from .models import ChunkRecord, SourceManifestEntry
from .qdrant_store import upsert_chunks
from .synthesis_lane import synthesis_lane_report_path, write_synthesis_lane_outputs
from .translation_draft_generation import generate_translation_drafts


TRANSLATED_GOLD_PROMOTION_STRATEGY = "translated_gold_manual_synthesis"
TRANSLATED_GOLD_PROMOTION_NOTE = (
    "approved translated Korean manual synthesis promoted into active gold dataset"
)
TRANSLATED_GOLD_TRUST_SCORE = 0.98


def _emit_progress(stage: str, **payload: object) -> None:
    print(
        json.dumps(
            {
                "stage": stage,
                **payload,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


def _draft_root(settings: Settings) -> Path:
    return settings.silver_ko_dir / "translation_drafts"


def _draft_normalized_docs_path(settings: Settings) -> Path:
    return _draft_root(settings) / "normalized_docs.jsonl"


def _draft_chunks_path(settings: Settings) -> Path:
    return _draft_root(settings) / "chunks.jsonl"


def _draft_playbook_documents_path(settings: Settings) -> Path:
    return _draft_root(settings) / "playbook_documents.jsonl"


def _draft_playbook_books_dir(settings: Settings) -> Path:
    return _draft_root(settings) / "playbooks"


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_jsonl_safe(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [dict(row) for row in read_jsonl(path)]


def _rows_by_slug(rows: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        slug = str(row.get("book_slug", "")).strip()
        if not slug:
            continue
        grouped.setdefault(slug, []).append(dict(row))
    return grouped


def _playbooks_by_slug(path: Path) -> dict[str, dict[str, object]]:
    return {
        str(row.get("book_slug", "")).strip(): dict(row)
        for row in _read_jsonl_safe(path)
        if str(row.get("book_slug", "")).strip()
    }


def _upsert_book_rows(
    existing: list[dict[str, object]],
    new_rows: list[dict[str, object]],
    *,
    slugs: set[str],
) -> list[dict[str, object]]:
    kept = [
        dict(row)
        for row in existing
        if str(row.get("book_slug", "")).strip() not in slugs
    ]
    return kept + [dict(row) for row in new_rows]


def _write_playbook_payloads(
    path: Path,
    books_dir: Path,
    payloads: list[dict[str, object]],
    *,
    slugs: set[str],
) -> None:
    rows = _upsert_book_rows(_read_jsonl_safe(path), payloads, slugs=slugs)
    _write_jsonl(path, rows)
    books_dir.mkdir(parents=True, exist_ok=True)
    for payload in payloads:
        slug = str(payload.get("book_slug", "")).strip()
        if not slug:
            continue
        (books_dir / f"{slug}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _bm25_row(chunk_row: dict[str, object]) -> dict[str, object]:
    chunk_type = str(chunk_row.get("chunk_type", "reference"))
    return {
        "chunk_id": chunk_row["chunk_id"],
        "book_slug": chunk_row["book_slug"],
        "chapter": chunk_row["chapter"],
        "section": chunk_row["section"],
        "anchor": chunk_row["anchor"],
        "source_url": chunk_row["source_url"],
        "viewer_path": chunk_row["viewer_path"],
        "text": chunk_row["text"],
        "section_path": list(chunk_row.get("section_path", [])),
        "chunk_type": chunk_type,
        "source_id": chunk_row["source_id"],
        "source_lane": chunk_row["source_lane"],
        "source_type": chunk_row["source_type"],
        "source_collection": chunk_row["source_collection"],
        "product": chunk_row["product"],
        "version": chunk_row["version"],
        "locale": chunk_row["locale"],
        "translation_status": chunk_row["translation_status"],
        "review_status": chunk_row["review_status"],
        "trust_score": chunk_row["trust_score"],
        "semantic_role": (
            "procedure"
            if chunk_type in {"procedure", "command"}
            else ("concept" if chunk_type == "concept" else "reference")
        ),
        "cli_commands": list(chunk_row.get("cli_commands", [])),
        "error_strings": list(chunk_row.get("error_strings", [])),
        "k8s_objects": list(chunk_row.get("k8s_objects", [])),
        "operator_names": list(chunk_row.get("operator_names", [])),
        "verification_hints": list(chunk_row.get("verification_hints", [])),
    }


def _chunk_records(rows: list[dict[str, object]]) -> list[ChunkRecord]:
    allowed = {field.name for field in fields(ChunkRecord)}
    records: list[ChunkRecord] = []
    for row in rows:
        payload = {key: value for key, value in row.items() if key in allowed}
        payload["section_path"] = tuple(payload.get("section_path", []))
        payload["cli_commands"] = tuple(payload.get("cli_commands", []))
        payload["error_strings"] = tuple(payload.get("error_strings", []))
        payload["k8s_objects"] = tuple(payload.get("k8s_objects", []))
        payload["operator_names"] = tuple(payload.get("operator_names", []))
        payload["verification_hints"] = tuple(payload.get("verification_hints", []))
        records.append(ChunkRecord(**payload))
    return records


def _missing_fields(row: dict[str, object], required_fields: tuple[str, ...]) -> list[str]:
    missing: list[str] = []
    for field_name in required_fields:
        value = row.get(field_name)
        if value is None:
            missing.append(field_name)
            continue
        if isinstance(value, str) and not value.strip():
            missing.append(field_name)
    return missing


def _draft_metadata_errors(
    *,
    normalized_rows: list[dict[str, object]],
    chunk_rows: list[dict[str, object]],
    playbook_payload: dict[str, object],
) -> list[str]:
    issues: list[str] = []
    for index, row in enumerate(normalized_rows, start=1):
        missing = _missing_fields(row, REQUIRED_ROW_METADATA_FIELDS)
        if missing:
            issues.append(f"normalized_row_{index}_missing:{','.join(missing)}")
            break
    for index, row in enumerate(chunk_rows, start=1):
        missing = _missing_fields(row, REQUIRED_ROW_METADATA_FIELDS)
        if missing:
            issues.append(f"chunk_row_{index}_missing:{','.join(missing)}")
            break
    playbook_top_missing = _missing_fields(
        playbook_payload,
        ("legal_notice_url", "review_status"),
    )
    if playbook_top_missing:
        issues.append("playbook_top_missing:" + ",".join(playbook_top_missing))
    source_metadata = dict(playbook_payload.get("source_metadata", {}))
    playbook_source_missing = _missing_fields(
        source_metadata,
        REQUIRED_PLAYBOOK_SOURCE_METADATA_FIELDS,
    )
    if playbook_source_missing:
        issues.append("playbook_source_missing:" + ",".join(playbook_source_missing))
    if any(not str(row.get("text", "")).strip() for row in chunk_rows):
        issues.append("empty_chunk_text")
    return issues


def _approved_source_id(slug: str) -> str:
    return f"translated_gold_manual_synthesis:{slug}"


def _approved_section_rows(
    slug: str,
    rows: list[dict[str, object]],
    *,
    title: str,
    source_id: str,
) -> list[dict[str, object]]:
    updated: list[dict[str, object]] = []
    for row in rows:
        payload = dict(row)
        payload.update(
            {
                "book_slug": slug,
                "book_title": title,
                "source_id": source_id,
                "source_lane": "applied_playbook",
                "source_type": "manual_synthesis",
                "translation_status": "approved_ko",
                "translation_stage": "approved_ko",
                "review_status": "approved",
                "trust_score": float(payload.get("trust_score") or TRANSLATED_GOLD_TRUST_SCORE),
            }
        )
        updated.append(payload)
    return updated


def _approved_chunk_rows(
    slug: str,
    rows: list[dict[str, object]],
    *,
    title: str,
    source_id: str,
) -> list[dict[str, object]]:
    updated: list[dict[str, object]] = []
    for row in rows:
        payload = dict(row)
        payload.update(
            {
                "book_slug": slug,
                "book_title": title,
                "source_id": source_id,
                "source_lane": "applied_playbook",
                "source_type": "manual_synthesis",
                "translation_status": "approved_ko",
                "translation_stage": "approved_ko",
                "review_status": "approved",
                "trust_score": float(payload.get("trust_score") or TRANSLATED_GOLD_TRUST_SCORE),
            }
        )
        updated.append(payload)
    return updated


def _approved_playbook_payload(
    slug: str,
    payload: dict[str, object],
    *,
    source_id: str,
) -> dict[str, object]:
    updated = json.loads(json.dumps(payload, ensure_ascii=False))
    title = str(updated.get("title") or slug)
    updated.update(
        {
            "book_slug": slug,
            "title": title,
            "translation_status": "approved_ko",
            "translation_stage": "approved_ko",
            "review_status": "approved",
            "quality_status": "ready",
            "quality_score": max(
                float(updated.get("quality_score") or 0.0),
                TRANSLATED_GOLD_TRUST_SCORE,
            ),
            "quality_flags": [],
        }
    )
    source_metadata = dict(updated.get("source_metadata", {}))
    source_metadata.update(
        {
            "source_id": source_id,
            "source_type": "manual_synthesis",
            "source_lane": "applied_playbook",
            "review_status": "approved",
            "trust_score": max(
                float(source_metadata.get("trust_score") or 0.0),
                TRANSLATED_GOLD_TRUST_SCORE,
            ),
        }
    )
    updated["source_metadata"] = source_metadata
    return updated


def _approved_manifest_entry(
    entry: SourceManifestEntry,
    *,
    normalized_rows: list[dict[str, object]],
    chunk_rows: list[dict[str, object]],
    playbook_payload: dict[str, object],
    source_id: str,
) -> SourceManifestEntry:
    source_metadata = dict(playbook_payload.get("source_metadata", {}))
    title = str(playbook_payload.get("title") or entry.title or entry.book_slug)
    source_url = str(playbook_payload.get("source_uri") or source_metadata.get("original_url") or entry.source_url)
    translation_source_url = str(
        playbook_payload.get("translation_source_uri")
        or entry.translation_source_url
        or source_url
    )
    source_fingerprint = str(
        playbook_payload.get("translation_source_fingerprint")
        or entry.translation_source_fingerprint
        or hashlib.sha256(
            "|".join((entry.book_slug, source_url, translation_source_url, source_id)).encode("utf-8")
        ).hexdigest()
    )
    return SourceManifestEntry(
        product_slug=entry.product_slug or "openshift_container_platform",
        ocp_version=entry.ocp_version,
        docs_language=entry.docs_language,
        source_kind=entry.source_kind or "html-single",
        book_slug=entry.book_slug,
        title=title,
        index_url=entry.index_url or source_url,
        source_url=source_url,
        resolved_source_url=source_url,
        resolved_language=entry.docs_language,
        source_state="published_native",
        source_state_reason="promoted_from_translation_draft_manual_synthesis",
        catalog_source_label="generated gold translation manual synthesis",
        viewer_path=entry.viewer_path,
        high_value=entry.high_value,
        vendor_title=str(source_metadata.get("original_title") or entry.vendor_title or entry.title),
        content_status="approved_ko",
        citation_eligible=True,
        citation_block_reason="",
        viewer_strategy="internal_text",
        body_language_guess="ko",
        hangul_section_ratio=hangul_ratio([str(row.get("text", "")) for row in normalized_rows]),
        hangul_chunk_ratio=hangul_ratio([str(row.get("text", "")) for row in chunk_rows]),
        fallback_detected=False,
        source_fingerprint=source_fingerprint,
        approval_status="approved",
        approval_notes=TRANSLATED_GOLD_PROMOTION_NOTE,
        source_id=source_id,
        source_lane="applied_playbook",
        source_type="manual_synthesis",
        source_collection=str(source_metadata.get("source_collection") or entry.source_collection or "core"),
        legal_notice_url=str(source_metadata.get("legal_notice_url") or playbook_payload.get("legal_notice_url") or entry.legal_notice_url),
        original_title=str(source_metadata.get("original_title") or entry.original_title or entry.title),
        license_or_terms=str(source_metadata.get("license_or_terms") or entry.license_or_terms),
        review_status="approved",
        trust_score=max(float(source_metadata.get("trust_score") or 0.0), TRANSLATED_GOLD_TRUST_SCORE),
        verifiability=str(source_metadata.get("verifiability") or entry.verifiability or "anchor_backed"),
        updated_at=str(source_metadata.get("updated_at") or entry.updated_at),
        translation_source_language=str(playbook_payload.get("translation_source_language") or entry.translation_source_language or "en"),
        translation_target_language=entry.docs_language,
        translation_source_url=translation_source_url,
        translation_source_fingerprint=str(
            playbook_payload.get("translation_source_fingerprint")
            or entry.translation_source_fingerprint
            or source_fingerprint
        ),
        translation_stage="approved_ko",
    )


def _promote_bundle_dossier(
    settings: Settings,
    entry: SourceManifestEntry,
    *,
    title: str,
    source_id: str,
) -> bool:
    dossier_path = settings.bronze_dir / "source_bundles" / entry.book_slug / "dossier.json"
    if not dossier_path.exists():
        return False
    dossier = json.loads(dossier_path.read_text(encoding="utf-8"))
    current_status = dict(dossier.get("current_status", {}))
    approved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    current_status.update(
        {
            "content_status": "approved_ko",
            "gap_lane": "approved",
            "gap_action": TRANSLATED_GOLD_PROMOTION_NOTE,
            "fallback_detected": False,
            "hangul_chunk_ratio": 1.0,
            "title": title,
            "promotion_strategy": TRANSLATED_GOLD_PROMOTION_STRATEGY,
            "review_status": "approved",
            "source_lane": "applied_playbook",
            "source_type": "manual_synthesis",
            "source_id": source_id,
            "updated_at": entry.updated_at,
            "approved_at": approved_at,
        }
    )
    dossier["current_status"] = current_status
    dossier["promotion"] = {
        "strategy": TRANSLATED_GOLD_PROMOTION_STRATEGY,
        "status": "approved_ko",
        "note": TRANSLATED_GOLD_PROMOTION_NOTE,
        "approved_at": approved_at,
        "source_manifest_path": str(settings.source_manifest_path),
        "source_id": source_id,
        "source_url": entry.source_url,
        "translation_source_url": entry.translation_source_url,
    }
    dossier_path.write_text(json.dumps(dossier, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def promote_translation_gold(
    settings: Settings,
    *,
    slugs: list[str] | None = None,
    generate_first: bool = False,
    force_collect: bool = False,
    force_regenerate: bool = False,
    refresh_synthesis_report: bool = True,
    sync_qdrant: bool = False,
    manifest_path: Path | None = None,
) -> dict[str, object]:
    generation_report = None
    draft_manifest_path = manifest_path or settings.translation_draft_manifest_path
    if generate_first:
        _emit_progress("gold_generate_first_start")
        generation_report = generate_translation_drafts(
            settings,
            slugs=slugs,
            force_collect=force_collect,
            force_regenerate=force_regenerate,
            manifest_path=draft_manifest_path,
        )
        _emit_progress(
            "gold_generate_first_complete",
            summary=generation_report.get("summary"),
        )

    entries = read_manifest(draft_manifest_path)
    selected_entries = [
        entry for entry in entries
        if not slugs or entry.book_slug in set(slugs)
    ]
    selected_slugs = {entry.book_slug for entry in selected_entries}

    draft_normalized_by_slug = _rows_by_slug(_read_jsonl_safe(_draft_normalized_docs_path(settings)))
    draft_chunks_by_slug = _rows_by_slug(_read_jsonl_safe(_draft_chunks_path(settings)))
    draft_playbooks_by_slug = _playbooks_by_slug(_draft_playbook_documents_path(settings))
    audit = build_playbook_reader_grade_audit_for_dirs((_draft_playbook_books_dir(settings),))
    audit_by_slug = {
        str(row.get("book_slug", "")): dict(row)
        for row in audit.get("books", [])
        if str(row.get("book_slug", "")).strip()
    }

    promoted_sections: list[dict[str, object]] = []
    promoted_chunks: list[dict[str, object]] = []
    promoted_bm25_rows: list[dict[str, object]] = []
    promoted_playbooks: list[dict[str, object]] = []
    promoted_entries: list[SourceManifestEntry] = []
    reports: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []
    graph_compact_refresh: dict[str, object] = {"status": "skipped"}

    total_entries = len(selected_entries)
    for index, entry in enumerate(selected_entries, start=1):
        slug = entry.book_slug
        _emit_progress(
            "gold_promote",
            index=index,
            total=total_entries,
            book_slug=slug,
        )
        normalized_rows = draft_normalized_by_slug.get(slug, [])
        chunk_rows = draft_chunks_by_slug.get(slug, [])
        playbook_payload = draft_playbooks_by_slug.get(slug)
        if not normalized_rows or not chunk_rows or playbook_payload is None:
            errors.append({"book_slug": slug, "error": "draft_artifacts_missing"})
            _emit_progress(
                "gold_promote_error",
                index=index,
                total=total_entries,
                book_slug=slug,
                error="draft_artifacts_missing",
            )
            continue

        audit_row = audit_by_slug.get(slug, {})
        if not bool(audit_row.get("semantic_role_coverage_ok", True)):
            errors.append({"book_slug": slug, "error": "draft_manualbook_semantic_role_failed"})
            _emit_progress(
                "gold_promote_error",
                index=index,
                total=total_entries,
                book_slug=slug,
                error="draft_manualbook_semantic_role_failed",
            )
            continue
        if not bool(audit_row.get("heading_language_ok", True)):
            errors.append({"book_slug": slug, "error": "draft_manualbook_heading_language_failed"})
            _emit_progress(
                "gold_promote_error",
                index=index,
                total=total_entries,
                book_slug=slug,
                error="draft_manualbook_heading_language_failed",
            )
            continue

        metadata_errors = _draft_metadata_errors(
            normalized_rows=normalized_rows,
            chunk_rows=chunk_rows,
            playbook_payload=playbook_payload,
        )
        if metadata_errors:
            errors.append(
                {
                    "book_slug": slug,
                    "error": "draft_metadata_incomplete",
                    "details": metadata_errors,
                }
            )
            _emit_progress(
                "gold_promote_error",
                index=index,
                total=total_entries,
                book_slug=slug,
                error="draft_metadata_incomplete",
                details=metadata_errors,
            )
            continue

        source_id = _approved_source_id(slug)
        approved_playbook = _approved_playbook_payload(slug, playbook_payload, source_id=source_id)
        title = str(approved_playbook.get("title") or entry.title or slug)
        approved_section_rows = _approved_section_rows(
            slug,
            normalized_rows,
            title=title,
            source_id=source_id,
        )
        approved_chunk_rows = _approved_chunk_rows(
            slug,
            chunk_rows,
            title=title,
            source_id=source_id,
        )
        approved_entry = _approved_manifest_entry(
            entry,
            normalized_rows=approved_section_rows,
            chunk_rows=approved_chunk_rows,
            playbook_payload=approved_playbook,
            source_id=source_id,
        )

        promoted_sections.extend(approved_section_rows)
        promoted_chunks.extend(approved_chunk_rows)
        promoted_bm25_rows.extend(_bm25_row(row) for row in approved_chunk_rows)
        promoted_playbooks.append(approved_playbook)
        promoted_entries.append(approved_entry)
        reports.append(
            {
                "book_slug": slug,
                "title": title,
                "section_count": len(approved_section_rows),
                "chunk_count": len(approved_chunk_rows),
                "translation_source_url": approved_entry.translation_source_url,
                "promotion_strategy": TRANSLATED_GOLD_PROMOTION_STRATEGY,
            }
        )
        _emit_progress(
            "gold_promote_complete",
            index=index,
            total=total_entries,
            book_slug=slug,
            section_count=len(approved_section_rows),
            chunk_count=len(approved_chunk_rows),
        )

    promoted_slugs = {entry.book_slug for entry in promoted_entries}
    if promoted_entries:
        _emit_progress(
            "gold_materialize_start",
            promoted_count=len(promoted_entries),
            error_count=len(errors),
        )
        for path in settings.normalized_docs_candidates:
            rows = _upsert_book_rows(_read_jsonl_safe(path), promoted_sections, slugs=promoted_slugs)
            _write_jsonl(path, rows)

        for path in (settings.chunks_path,):
            rows = _upsert_book_rows(_read_jsonl_safe(path), promoted_chunks, slugs=promoted_slugs)
            _write_jsonl(path, rows)

        for path in (settings.bm25_corpus_path,):
            rows = _upsert_book_rows(_read_jsonl_safe(path), promoted_bm25_rows, slugs=promoted_slugs)
            _write_jsonl(path, rows)

        for path in (settings.playbook_documents_path,):
            books_dir = settings.playbook_books_dir
            _write_playbook_payloads(path, books_dir, promoted_playbooks, slugs=promoted_slugs)

        existing_manifest_entries = (
            read_manifest(settings.source_manifest_path)
            if settings.source_manifest_path.exists()
            else []
        )
        manifest_entries = [
            item for item in existing_manifest_entries if item.book_slug not in promoted_slugs
        ] + promoted_entries
        manifest_entries.sort(
            key=lambda item: (item.ocp_version, item.docs_language, item.source_kind, item.book_slug)
        )
        write_manifest(settings.source_manifest_path, manifest_entries)
        graph_refresh = refresh_active_runtime_graph_artifacts(
            settings,
            refresh_full_sidecar=False,
            allow_compact_degrade=True,
        )
        graph_compact_refresh = dict(graph_refresh.get("compact_sidecar", {}))
        _emit_progress(
            "gold_materialize_complete",
            promoted_count=len(promoted_entries),
            approved_manifest_path=str(settings.source_manifest_path),
            graph_compact_status=graph_compact_refresh.get("status"),
        )

    dossier_promoted_count = 0
    for entry in promoted_entries:
        if _promote_bundle_dossier(
            settings,
            entry,
            title=entry.title,
            source_id=entry.source_id,
        ):
            dossier_promoted_count += 1
    if promoted_entries:
        _emit_progress(
            "gold_dossier_complete",
            dossier_promoted_count=dossier_promoted_count,
        )

    qdrant_upserted_count = 0
    if sync_qdrant and promoted_chunks:
        _emit_progress(
            "gold_qdrant_start",
            chunk_count=len(promoted_chunks),
        )
        chunk_records = _chunk_records(promoted_chunks)
        client = EmbeddingClient(settings)
        vectors = client.embed_texts(
            (chunk.text for chunk in chunk_records),
            progress_callback=lambda done, total: _emit_progress(
                "gold_embed_progress",
                completed_batches=done,
                total_batches=total,
            ),
        )
        qdrant_upserted_count = upsert_chunks(
            settings,
            chunk_records,
            vectors,
            progress_callback=lambda done, total: _emit_progress(
                "gold_qdrant_progress",
                completed_batches=done,
                total_batches=total,
            ),
        )
        _emit_progress(
            "gold_qdrant_complete",
            qdrant_upserted_count=qdrant_upserted_count,
        )

    synthesis_report = None
    if refresh_synthesis_report and settings.source_catalog_path.exists():
        synthesis_report_path = synthesis_lane_report_path(settings)
        synthesis_report = write_synthesis_lane_outputs(settings)
        _emit_progress(
            "gold_synthesis_complete",
            synthesis_report_path=str(synthesis_report_path),
            summary=synthesis_report.get("summary"),
        )
    else:
        synthesis_report_path = None

    report: dict[str, object] = {
        "summary": {
            "requested_count": len(selected_entries),
            "promoted_count": len(promoted_entries),
            "error_count": len(errors),
            "dossier_promoted_count": dossier_promoted_count,
            "qdrant_upserted_count": qdrant_upserted_count,
            "graph_compact_ready": bool(graph_sidecar_compact_artifact_status(settings).get("ready")),
        },
        "books": reports,
        "errors": errors,
        "graph_compact_refresh": graph_compact_refresh,
        "graph_compact_artifact": graph_sidecar_compact_artifact_status(settings),
        "output_targets": {
            "translation_draft_manifest_path": str(draft_manifest_path),
            "approved_manifest_path": str(settings.source_manifest_path),
            "normalized_docs": [str(path) for path in settings.normalized_docs_candidates],
            "chunks": [
                str(path)
                for path in (settings.chunks_path,)
            ],
            "bm25_corpus": [
                str(path)
                for path in (settings.bm25_corpus_path,)
            ],
            "playbook_documents": [
                str(path)
                for path in (settings.playbook_documents_path,)
            ],
            "playbook_books": [str(path) for path in settings.playbook_book_dirs],
            "graph_sidecar_compact_path": str(settings.graph_sidecar_compact_path),
        },
    }
    if generation_report is not None:
        report["generation_summary"] = generation_report.get("summary")
    if synthesis_report is not None and synthesis_report_path is not None:
        report["synthesis_report_path"] = str(synthesis_report_path)
        report["synthesis_summary"] = synthesis_report.get("summary")
    _emit_progress(
        "gold_summary",
        summary=report.get("summary"),
    )
    return report
