"""ingestion 전체를 오케스트레이션하는 진입점.

ingestion 순서는 여기서 고정된다:
manifest -> collect -> normalize -> chunk -> embed -> qdrant
"""

from __future__ import annotations

import json
from pathlib import Path

from play_book_studio.canonical import project_playbook_document
from .audit_rules import (
    LANGUAGE_FALLBACK_RE,
    body_language_guess,
    classify_content_status,
    hangul_ratio,
    is_english_like_title,
    resolve_final_content_status,
)
from .chunking import chunk_sections
from .collector import collect_entry, entry_with_collected_metadata, raw_html_path
from .embedding import EmbeddingClient
from .graph_sidecar import refresh_active_runtime_graph_artifacts
from .manifest import (
    build_source_catalog_entries,
    build_manifest_update_report,
    read_manifest,
    runtime_catalog_entries,
    write_manifest,
)
from .models import (
    CONTENT_STATUS_APPROVED_KO,
    CONTENT_STATUS_EN_ONLY,
    CONTENT_STATUS_MIXED,
    CONTENT_STATUS_TRANSLATED_KO_DRAFT,
    ChunkRecord,
    NormalizedSection,
    PipelineLog,
    SourceManifestEntry,
)
from .normalize import extract_document_ast, project_normalized_sections
from .playbook_materialization import (
    load_approved_playbook_payload,
    project_playbook_payload_sections,
)
from .qdrant_store import ensure_collection, upsert_chunks
from play_book_studio.config.settings import HIGH_VALUE_SLUGS, Settings


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_jsonl_targets(paths: tuple[Path, ...], rows: list[dict]) -> None:
    for path in paths:
        _write_jsonl(path, rows)


def _write_playbook_payloads(path: Path, books_dir: Path, payloads: list[dict]) -> None:
    books_dir.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    sorted_payloads = sorted(
        (dict(payload) for payload in payloads if str(payload.get("book_slug") or "").strip()),
        key=lambda payload: str(payload.get("book_slug") or ""),
    )
    expected_filenames = {f"{payload['book_slug']}.json" for payload in sorted_payloads}
    with path.open("w", encoding="utf-8") as handle:
        for payload in sorted_payloads:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            (books_dir / f"{payload['book_slug']}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    for stale_path in books_dir.glob("*.json"):
        if stale_path.name not in expected_filenames:
            stale_path.unlink()


def _runtime_source_lane(entry: SourceManifestEntry, content_status: str) -> str:
    explicit = (entry.source_lane or "").strip()
    if explicit:
        return explicit
    if entry.source_type in {
        "official_issue",
        "official_pr",
        "community_issue",
        "community_blog",
        "internal_runbook",
        "manual_synthesis",
    }:
        return "applied_playbook"
    if content_status in {CONTENT_STATUS_EN_ONLY, CONTENT_STATUS_MIXED, CONTENT_STATUS_TRANSLATED_KO_DRAFT}:
        return "official_en_fallback"
    return "official_ko"


def _runtime_review_status(entry: SourceManifestEntry, approval_status: str) -> str:
    current = (entry.review_status or "").strip()
    if current == "rejected":
        return current
    if approval_status == "needs_review":
        return "needs_review"
    if current in {"", "unreviewed"}:
        return approval_status
    return current


def _entry_with_inferred_runtime_status(
    entry: SourceManifestEntry,
    *,
    html: str,
    sections: list[NormalizedSection],
) -> SourceManifestEntry:
    fallback_detected = entry.fallback_detected or bool(LANGUAGE_FALLBACK_RE.search(html))
    hangul_section_ratio = hangul_ratio([section.text for section in sections])
    hangul_chunk_ratio = hangul_section_ratio
    auto_status, auto_reason = classify_content_status(
        section_count=len(sections),
        chunk_count=len(sections),
        hangul_section_ratio=hangul_section_ratio,
        hangul_chunk_ratio=hangul_chunk_ratio,
        title_english_like=is_english_like_title(entry.title),
        fallback_detected=fallback_detected,
    )
    content_status, citation_eligible, citation_block_reason, approval_status = (
        resolve_final_content_status(
            entry,
            auto_status=auto_status,
            auto_reason=auto_reason,
        )
    )
    return SourceManifestEntry(
        **{
            **entry.to_dict(),
            "content_status": content_status,
            "citation_eligible": citation_eligible,
            "citation_block_reason": citation_block_reason,
            "review_status": _runtime_review_status(entry, approval_status),
            "approval_status": approval_status,
            "body_language_guess": body_language_guess(
                hangul_chunk_ratio=hangul_chunk_ratio,
                fallback_detected=fallback_detected,
            ),
            "hangul_section_ratio": hangul_section_ratio,
            "hangul_chunk_ratio": hangul_chunk_ratio,
            "fallback_detected": fallback_detected,
            "source_lane": _runtime_source_lane(entry, content_status),
        }
    )


def _save_log(settings: Settings, log: PipelineLog) -> None:
    settings.preprocessing_log_path.write_text(
        json.dumps(log.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _progress(message: str) -> None:
    print(message, flush=True)


def ensure_manifest(settings: Settings, refresh: bool = False) -> list[SourceManifestEntry]:
    if refresh or not settings.source_catalog_path.exists():
        previous_entries = (
            read_manifest(settings.source_catalog_path)
            if settings.source_catalog_path.exists()
            else []
        )
        entries = build_source_catalog_entries(settings)
        write_manifest(settings.source_catalog_path, entries)
        report = build_manifest_update_report(previous_entries, entries)
        settings.source_manifest_update_report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return entries
    return read_manifest(settings.source_catalog_path)


def load_runtime_manifest_entries(settings: Settings) -> list[SourceManifestEntry]:
    if settings.source_manifest_path.exists():
        return read_manifest(settings.source_manifest_path)
    raise FileNotFoundError(
        f"approved runtime manifest not found: {settings.source_manifest_path}"
    )


def _select_entries(
    entries: list[SourceManifestEntry], subset: str, limit: int | None
) -> list[SourceManifestEntry]:
    if subset == "high-value":
        selected = [entry for entry in entries if entry.book_slug in HIGH_VALUE_SLUGS]
    else:
        selected = list(entries)
    return selected[:limit] if limit is not None else selected


def run_ingestion_pipeline(
    settings: Settings,
    *,
    refresh_manifest: bool = False,
    collect_subset: str = "all",
    process_subset: str = "high-value",
    collect_limit: int | None = None,
    process_limit: int | None = None,
    force_collect: bool = False,
    skip_embeddings: bool = False,
    skip_qdrant: bool = False,
) -> PipelineLog:
    log = PipelineLog()
    # 1단계: source manifest를 확정한다.
    log.stage = "manifest"
    if refresh_manifest:
        ensure_manifest(settings, refresh=True)
    entries = load_runtime_manifest_entries(settings)
    log.manifest_count = len(entries)
    _progress(f"[manifest] entries={len(entries)}")
    _save_log(settings, log)

    collect_entries = _select_entries(entries, collect_subset, collect_limit)
    _progress(f"[collect] target_books={len(collect_entries)} subset={collect_subset}")
    # 2단계: 원본 HTML을 로컬 artifact cache로 수집한다.
    log.stage = "collect"
    for index, entry in enumerate(collect_entries, start=1):
        try:
            collect_entry(entry, settings, force=force_collect)
            log.collected_count += 1
            log.collected_sources.append(entry.book_slug)
            log.upsert_book_stat(entry.book_slug, collected=True, source_url=entry.source_url)
            _progress(f"[collect {index}/{len(collect_entries)}] {entry.book_slug}")
            _save_log(settings, log)
        except Exception as exc:  # noqa: BLE001
            log.add_error("collect", entry.book_slug, str(exc))
            _save_log(settings, log)

    process_entries = _select_entries(entries, process_subset, process_limit)
    all_sections: list[NormalizedSection] = []
    playbook_documents: list[dict[str, object]] = []
    _progress(f"[normalize] target_books={len(process_entries)} subset={process_subset}")
    # 3단계: raw HTML을 canonical section으로 바꾼다.
    log.stage = "normalize"
    for index, entry in enumerate(process_entries, start=1):
        try:
            runtime_entry = entry_with_collected_metadata(settings, entry)
            approved_playbook_payload = None
            if runtime_entry.source_type == "manual_synthesis":
                approved_playbook_payload = load_approved_playbook_payload(
                    settings,
                    entry.book_slug,
                    source_type="manual_synthesis",
                )
            if approved_playbook_payload is not None:
                sections = project_playbook_payload_sections(approved_playbook_payload)
                inferred_entry = _entry_with_inferred_runtime_status(
                    runtime_entry,
                    html="",
                    sections=sections,
                )
                playbook_documents.append(approved_playbook_payload)
            else:
                html_path = raw_html_path(settings, entry.book_slug)
                if not html_path.exists():
                    collect_entry(entry, settings, force=False)
                    log.collected_count += 1
                    log.collected_sources.append(entry.book_slug)
                html = html_path.read_text(encoding="utf-8")
                document = extract_document_ast(html, runtime_entry, settings=settings)
                sections = project_normalized_sections(document)
                inferred_entry = _entry_with_inferred_runtime_status(
                    runtime_entry,
                    html=html,
                    sections=sections,
                )
                if inferred_entry.to_dict() != runtime_entry.to_dict():
                    document = extract_document_ast(html, inferred_entry, settings=settings)
                    sections = project_normalized_sections(document)
                playbook_documents.append(project_playbook_document(document).to_dict())
            all_sections.extend(sections)
            log.processed_sources.append(entry.book_slug)
            log.upsert_book_stat(
                entry.book_slug,
                processed=True,
                section_count=len(sections),
                title=inferred_entry.title or entry.title,
                high_value=entry.high_value,
                content_status=inferred_entry.content_status,
                source_lane=inferred_entry.source_lane,
                review_status=inferred_entry.review_status,
            )
            _progress(
                f"[normalize {index}/{len(process_entries)}] "
                f"{entry.book_slug} sections={len(sections)}"
            )
            _save_log(settings, log)
        except Exception as exc:  # noqa: BLE001
            log.add_error("normalize", entry.book_slug, str(exc))
            _save_log(settings, log)

    log.stage = "write_normalized"
    log.normalized_count = len(all_sections)
    _progress(f"[normalize] total_sections={len(all_sections)}")
    normalized_rows = [section.to_dict() for section in all_sections]
    _write_jsonl_targets(
        settings.normalized_docs_candidates,
        normalized_rows,
    )
    _write_playbook_payloads(
        settings.playbook_documents_path,
        settings.playbook_books_dir,
        playbook_documents,
    )
    _save_log(settings, log)

    log.stage = "chunk"
    # 4단계: section을 BM25/vector 양쪽에서 쓰는 chunk record로 나눈다.
    chunks: list[ChunkRecord] = chunk_sections(all_sections, settings)
    log.chunk_count = len(chunks)
    chunk_counts: dict[str, int] = {}
    for chunk in chunks:
        chunk_counts[chunk.book_slug] = chunk_counts.get(chunk.book_slug, 0) + 1
    for book_slug, count in chunk_counts.items():
        log.upsert_book_stat(book_slug, chunk_count=count)
    _progress(f"[chunk] total_chunks={len(chunks)}")
    chunk_rows = [chunk.to_dict() for chunk in chunks]
    _write_jsonl_targets(
        (settings.chunks_path,),
        chunk_rows,
    )
    bm25_rows = [
        {
            "chunk_id": chunk.chunk_id,
            "book_slug": chunk.book_slug,
            "chapter": chunk.chapter,
            "section": chunk.section,
            "anchor": chunk.anchor,
            "source_url": chunk.source_url,
            "viewer_path": chunk.viewer_path,
            "text": chunk.text,
            "section_path": list(chunk.section_path),
            "chunk_type": chunk.chunk_type,
            "source_id": chunk.source_id,
            "source_lane": chunk.source_lane,
            "source_type": chunk.source_type,
            "source_collection": chunk.source_collection,
            "product": chunk.product,
            "version": chunk.version,
            "locale": chunk.locale,
            "translation_status": chunk.translation_status,
            "review_status": chunk.review_status,
            "trust_score": chunk.trust_score,
            "semantic_role": "procedure" if chunk.chunk_type in {"procedure", "command"} else (
                "concept" if chunk.chunk_type == "concept" else "reference"
            ),
            "cli_commands": list(chunk.cli_commands),
            "error_strings": list(chunk.error_strings),
            "k8s_objects": list(chunk.k8s_objects),
            "operator_names": list(chunk.operator_names),
            "verification_hints": list(chunk.verification_hints),
        }
        for chunk in chunks
    ]
    _write_jsonl_targets(
        (settings.bm25_corpus_path,),
        bm25_rows,
    )
    log.stage = "graph"
    graph_refresh = refresh_active_runtime_graph_artifacts(
        settings,
        refresh_full_sidecar=True,
    )
    full_sidecar = dict(graph_refresh.get("full_sidecar", {}))
    log.graph_book_count = int(full_sidecar.get("book_count", 0) or 0)
    log.graph_relation_count = int(full_sidecar.get("relation_count", 0) or 0)
    _progress(
        "[graph] "
        f"books={log.graph_book_count} relations={log.graph_relation_count}"
    )
    _save_log(settings, log)

    if chunks and not skip_embeddings:
        try:
            # 5/6단계: embedding을 만들고, 그 결과를 Qdrant에 적재한다.
            log.stage = "embed"
            client = EmbeddingClient(settings)
            vectors = client.embed_texts(
                (chunk.text for chunk in chunks),
                progress_callback=lambda done, total: (
                    _progress(f"[embed {done}/{total}]"),
                    _save_log(settings, log),
                ),
            )
            log.embedded_count = len(vectors)
            _progress(f"[embed] total_vectors={len(vectors)}")
            _save_log(settings, log)
            if not skip_qdrant:
                log.stage = "qdrant"
                ensure_collection(settings)
                log.qdrant_upserted_count = upsert_chunks(
                    settings,
                    chunks,
                    vectors,
                    progress_callback=lambda done, total: (
                        _progress(f"[qdrant {done}/{total}]"),
                        _save_log(settings, log),
                    ),
                )
                _progress(f"[qdrant] upserted={log.qdrant_upserted_count}")
        except Exception as exc:  # noqa: BLE001
            log.add_error("embed_or_qdrant", "pipeline", str(exc))
            _save_log(settings, log)

    log.stage = "done"
    _save_log(settings, log)
    return log
