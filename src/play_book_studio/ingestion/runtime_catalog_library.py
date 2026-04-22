from __future__ import annotations

from dataclasses import fields, replace
import json
from pathlib import Path
from typing import Any

from play_book_studio.canonical import project_playbook_document
from play_book_studio.config.settings import Settings

from .chunking import chunk_sections
from .collector import collect_entry, entry_with_collected_metadata, raw_html_path
from .embedding import EmbeddingClient
from .graph_sidecar import refresh_active_runtime_graph_artifacts
from .manifest import read_manifest, runtime_catalog_entries
from .metadata_extraction import extract_section_metadata
from .models import ChunkRecord, NormalizedSection, SourceManifestEntry
from .normalize import extract_document_ast, project_normalized_sections
from .pipeline import _entry_with_inferred_runtime_status
from .qdrant_store import ensure_collection, upsert_chunks
from .topic_playbooks import (
    DERIVED_PLAYBOOK_SOURCE_TYPES,
    approved_materialized_derived_playbooks,
    materialize_derived_playbooks,
)
from .validation import read_jsonl


OFFICIAL_SOURCE_TYPE = "official_doc"


def _read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [dict(row) for row in read_jsonl(path)]


def _write_jsonl_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _playbook_source_type(row: dict[str, Any]) -> str:
    source_metadata = row.get("source_metadata") if isinstance(row.get("source_metadata"), dict) else {}
    return str(source_metadata.get("source_type") or "").strip()


def _row_source_type(row: dict[str, Any]) -> str:
    direct = str(row.get("source_type") or "").strip()
    return direct or _playbook_source_type(row)


def _retain_non_official_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in rows
        if _row_source_type(row) not in ({OFFICIAL_SOURCE_TYPE} | DERIVED_PLAYBOOK_SOURCE_TYPES)
    ]


def _retain_non_official_non_derived_playbook_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in rows
        if _playbook_source_type(row) not in ({OFFICIAL_SOURCE_TYPE} | DERIVED_PLAYBOOK_SOURCE_TYPES)
    ]


def _cleanup_stale_official_book_files(books_dir: Path, *, expected_slugs: set[str]) -> None:
    if not books_dir.exists():
        return
    for path in books_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if _playbook_source_type(payload) != OFFICIAL_SOURCE_TYPE:
            continue
        if path.stem not in expected_slugs:
            path.unlink()


def _write_official_playbook_payloads(
    books_dir: Path,
    payloads: list[dict[str, Any]],
) -> None:
    books_dir.mkdir(parents=True, exist_ok=True)
    for payload in payloads:
        slug = str(payload.get("book_slug") or "").strip()
        if not slug:
            continue
        (books_dir / f"{slug}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _bm25_row(chunk_row: dict[str, Any]) -> dict[str, Any]:
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


def _chunk_records(rows: list[dict[str, Any]]) -> list[ChunkRecord]:
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


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _derived_code_marker(block: dict[str, Any]) -> str:
    code = str(block.get("code") or "").strip()
    if not code:
        return ""
    language = str(block.get("language") or "shell").strip() or "shell"
    caption = str(block.get("caption") or "").strip()
    attrs: list[str] = [f'language="{language}"']
    if caption:
        attrs.append(f'caption="{caption}"')
    return "[CODE {attrs}]\n{code}\n[/CODE]".format(
        attrs=" ".join(attrs),
        code=code,
    )


def _derived_table_marker(block: dict[str, Any]) -> str:
    headers = [str(item).strip() for item in (block.get("headers") or []) if str(item).strip()]
    rows = [
        [str(cell).strip() for cell in row if str(cell).strip()]
        for row in (block.get("rows") or [])
        if isinstance(row, list)
    ]
    lines: list[str] = []
    if headers:
        lines.append(" | ".join(headers))
    for row in rows:
        if row:
            lines.append(" | ".join(row))
    table_text = "\n".join(line for line in lines if line.strip()).strip()
    if not table_text:
        return ""
    caption = str(block.get("caption") or "").strip()
    attrs = f' caption="{caption}"' if caption else ""
    return "[TABLE{attrs}]\n{table}\n[/TABLE]".format(attrs=attrs, table=table_text)


def _derived_block_text(block: dict[str, Any]) -> str:
    kind = str(block.get("kind") or "").strip().lower()
    if kind == "paragraph":
        return str(block.get("text") or "").strip()
    if kind == "prerequisite":
        return "\n".join(
            f"- {item.strip()}"
            for item in (str(value) for value in (block.get("items") or []))
            if item.strip()
        )
    if kind == "procedure":
        lines: list[str] = []
        for step in block.get("steps") or []:
            if not isinstance(step, dict):
                continue
            text = str(step.get("text") or "").strip()
            if not text:
                continue
            ordinal = step.get("ordinal")
            prefix = f"{ordinal}. " if ordinal not in (None, "") else ""
            lines.append(f"{prefix}{text}".strip())
            for substep in step.get("substeps") or []:
                substep_text = str(substep).strip()
                if substep_text:
                    lines.append(f"- {substep_text}")
        return "\n".join(lines)
    if kind == "code":
        return _derived_code_marker(block)
    if kind == "table":
        return _derived_table_marker(block)
    if kind == "note":
        title = str(block.get("title") or "").strip()
        text = str(block.get("text") or "").strip()
        if title and text:
            return f"{title}\n{text}"
        return title or text
    if kind == "anchor":
        return ""
    parts: list[str] = []
    for key in ("title", "text", "caption", "code"):
        value = str(block.get(key) or "").strip()
        if value:
            parts.append(value)
    return "\n".join(parts).strip()


def _derived_section_text(section: dict[str, Any]) -> str:
    fragments = [
        _derived_block_text(block)
        for block in (section.get("blocks") or [])
        if isinstance(block, dict)
    ]
    return "\n\n".join(fragment for fragment in fragments if fragment).strip()


def _project_materialized_derived_sections(settings: Settings) -> list[NormalizedSection]:
    sections: list[NormalizedSection] = []
    for row in approved_materialized_derived_playbooks(settings):
        source_metadata = row.get("source_metadata") if isinstance(row.get("source_metadata"), dict) else {}
        access_groups = tuple(
            str(group).strip()
            for group in (source_metadata.get("access_groups") or [])
            if str(group).strip()
        )
        for section in row.get("sections") or []:
            if not isinstance(section, dict):
                continue
            text = _derived_section_text(section)
            if not text:
                continue
            section_path = [
                str(item).strip()
                for item in (section.get("section_path") or section.get("path") or [])
                if str(item).strip()
            ]
            block_kinds = tuple(
                str(block.get("kind") or "").strip()
                for block in (section.get("blocks") or [])
                if isinstance(block, dict) and str(block.get("kind") or "").strip()
            )
            section_seed = NormalizedSection(
                book_slug=str(row.get("book_slug") or "").strip(),
                book_title=str(row.get("title") or "").strip() or str(row.get("book_slug") or "").strip(),
                heading=str(section.get("heading") or "").strip() or str(row.get("title") or "").strip(),
                section_level=int(section.get("level") or 2),
                section_path=section_path,
                anchor=str(section.get("anchor") or "").strip(),
                source_url=(
                    str(row.get("source_uri") or "").strip()
                    or str(source_metadata.get("original_url") or "").strip()
                ),
                viewer_path=str(section.get("viewer_path") or "").strip(),
                text=text,
                section_id=str(section.get("section_id") or "").strip(),
                semantic_role=str(section.get("semantic_role") or "reference").strip() or "reference",
                block_kinds=block_kinds,
                source_language=str(row.get("source_language") or "ko").strip() or "ko",
                display_language=str(row.get("language_hint") or row.get("locale") or "ko").strip() or "ko",
                translation_status=str(row.get("translation_status") or "approved_ko").strip() or "approved_ko",
                translation_stage=str(row.get("translation_stage") or row.get("translation_status") or "approved_ko").strip() or "approved_ko",
                translation_source_language=str(row.get("translation_source_language") or source_metadata.get("translation_source_language") or "").strip(),
                translation_source_url=str(row.get("translation_source_uri") or source_metadata.get("translation_source_url") or "").strip(),
                translation_source_fingerprint=str(row.get("translation_source_fingerprint") or source_metadata.get("translation_source_fingerprint") or "").strip(),
                source_id=str(source_metadata.get("source_id") or "").strip(),
                source_lane=str(source_metadata.get("source_lane") or "applied_playbook").strip() or "applied_playbook",
                source_type=str(source_metadata.get("source_type") or "").strip(),
                source_collection=str(source_metadata.get("source_collection") or "core").strip() or "core",
                product=str(source_metadata.get("product") or "openshift").strip() or "openshift",
                version=str(row.get("version") or source_metadata.get("version") or "4.20").strip() or "4.20",
                locale=str(row.get("locale") or source_metadata.get("locale") or "ko").strip() or "ko",
                original_title=str(source_metadata.get("original_title") or row.get("title") or "").strip(),
                legal_notice_url=str(row.get("legal_notice_url") or source_metadata.get("legal_notice_url") or "").strip(),
                license_or_terms=str(source_metadata.get("license_or_terms") or "").strip(),
                review_status=str(row.get("review_status") or source_metadata.get("review_status") or "approved").strip() or "approved",
                trust_score=float(source_metadata.get("trust_score") or 1.0),
                verifiability=str(source_metadata.get("verifiability") or "anchor_backed").strip() or "anchor_backed",
                updated_at=str(source_metadata.get("updated_at") or "").strip(),
                parsed_artifact_id=str(source_metadata.get("parsed_artifact_id") or "").strip(),
                tenant_id=str(source_metadata.get("tenant_id") or "public").strip() or "public",
                workspace_id=str(source_metadata.get("workspace_id") or "core").strip() or "core",
                parent_pack_id=str(source_metadata.get("pack_id") or row.get("pack_id") or "").strip(),
                pack_version=str(source_metadata.get("pack_version") or row.get("inferred_version") or row.get("version") or "").strip(),
                bundle_scope=str(source_metadata.get("bundle_scope") or "official").strip() or "official",
                classification=str(source_metadata.get("classification") or "public").strip() or "public",
                access_groups=access_groups or ("public",),
                provider_egress_policy=str(source_metadata.get("provider_egress_policy") or "unspecified").strip() or "unspecified",
                approval_state=str(source_metadata.get("approval_state") or "").strip(),
                publication_state=str(source_metadata.get("publication_state") or "").strip(),
                redaction_state=str(source_metadata.get("redaction_state") or "not_required").strip() or "not_required",
            )
            metadata = extract_section_metadata(section_seed)
            sections.append(
                NormalizedSection(
                    book_slug=section_seed.book_slug,
                    book_title=section_seed.book_title,
                    heading=section_seed.heading,
                    section_level=section_seed.section_level,
                    section_path=section_seed.section_path,
                    anchor=section_seed.anchor,
                    source_url=section_seed.source_url,
                    viewer_path=section_seed.viewer_path,
                    text=section_seed.text,
                    section_id=section_seed.section_id,
                    semantic_role=section_seed.semantic_role,
                    block_kinds=section_seed.block_kinds,
                    source_language=section_seed.source_language,
                    display_language=section_seed.display_language,
                    translation_status=section_seed.translation_status,
                    translation_stage=section_seed.translation_stage,
                    translation_source_language=section_seed.translation_source_language,
                    translation_source_url=section_seed.translation_source_url,
                    translation_source_fingerprint=section_seed.translation_source_fingerprint,
                    source_id=section_seed.source_id,
                    source_lane=section_seed.source_lane,
                    source_type=section_seed.source_type,
                    source_collection=section_seed.source_collection,
                    product=section_seed.product,
                    version=section_seed.version,
                    locale=section_seed.locale,
                    original_title=section_seed.original_title,
                    legal_notice_url=section_seed.legal_notice_url,
                    license_or_terms=section_seed.license_or_terms,
                    review_status=section_seed.review_status,
                    trust_score=section_seed.trust_score,
                    verifiability=section_seed.verifiability,
                    updated_at=section_seed.updated_at,
                    parsed_artifact_id=section_seed.parsed_artifact_id,
                    tenant_id=section_seed.tenant_id,
                    workspace_id=section_seed.workspace_id,
                    parent_pack_id=section_seed.parent_pack_id,
                    pack_version=section_seed.pack_version,
                    bundle_scope=section_seed.bundle_scope,
                    classification=section_seed.classification,
                    access_groups=section_seed.access_groups,
                    provider_egress_policy=section_seed.provider_egress_policy,
                    approval_state=section_seed.approval_state,
                    publication_state=section_seed.publication_state,
                    redaction_state=section_seed.redaction_state,
                    cli_commands=metadata.cli_commands,
                    error_strings=metadata.error_strings,
                    k8s_objects=metadata.k8s_objects,
                    operator_names=metadata.operator_names,
                    verification_hints=metadata.verification_hints,
                )
            )
    return sections


def _runtime_catalog_entries(settings: Settings) -> list[SourceManifestEntry]:
    return runtime_catalog_entries(read_manifest(settings.source_catalog_path), settings)


def materialize_runtime_corpus_from_playbooks(
    settings: Settings,
    *,
    sync_qdrant: bool = False,
    recreate_qdrant: bool = False,
) -> dict[str, Any]:
    official_normalized_rows = [
        dict(row)
        for row in _read_jsonl_rows(settings.normalized_docs_path)
        if _row_source_type(row) == OFFICIAL_SOURCE_TYPE
    ]
    official_chunk_rows = [
        dict(row)
        for row in _read_jsonl_rows(settings.chunks_path)
        if _row_source_type(row) == OFFICIAL_SOURCE_TYPE
    ]
    retained_normalized_rows = _retain_non_official_rows(_read_jsonl_rows(settings.normalized_docs_path))
    retained_chunk_rows = _retain_non_official_rows(_read_jsonl_rows(settings.chunks_path))

    derived_summary = materialize_derived_playbooks(settings)
    derived_sections = _project_materialized_derived_sections(settings)
    derived_normalized_rows = [section.to_dict() for section in derived_sections]
    derived_chunk_rows = [chunk.to_dict() for chunk in chunk_sections(derived_sections, settings)]

    merged_normalized_rows = retained_normalized_rows + official_normalized_rows + derived_normalized_rows
    merged_chunk_rows = retained_chunk_rows + official_chunk_rows + derived_chunk_rows

    _write_jsonl_rows(settings.normalized_docs_path, merged_normalized_rows)
    _write_jsonl_rows(settings.chunks_path, merged_chunk_rows)
    _write_jsonl_rows(settings.bm25_corpus_path, [_bm25_row(row) for row in merged_chunk_rows])

    graph_refresh = refresh_active_runtime_graph_artifacts(
        settings,
        refresh_full_sidecar=True,
    )
    full_sidecar = dict(graph_refresh.get("full_sidecar", {}))

    qdrant_upserted_count = 0
    if sync_qdrant and merged_chunk_rows:
        chunk_records = _chunk_records(merged_chunk_rows)
        embedding_settings = replace(
            settings,
            qdrant_recreate_collection=(recreate_qdrant or settings.qdrant_recreate_collection),
        )
        vectors = EmbeddingClient(embedding_settings).embed_texts(
            (chunk.text for chunk in chunk_records),
        )
        ensure_collection(embedding_settings)
        qdrant_upserted_count = upsert_chunks(
            embedding_settings,
            chunk_records,
            vectors,
        )

    return {
        "official_section_count": len(official_normalized_rows),
        "official_chunk_count": len(official_chunk_rows),
        "derived_playbook_count": int(derived_summary.get("generated_count", 0) or 0),
        "derived_section_count": len(derived_normalized_rows),
        "derived_chunk_count": len(derived_chunk_rows),
        "runtime_book_count": len(
            {
                str(row.get("book_slug") or "").strip()
                for row in merged_chunk_rows
                if str(row.get("book_slug") or "").strip()
            }
        ),
        "runtime_chunk_count": len(merged_chunk_rows),
        "qdrant_upserted_count": qdrant_upserted_count,
        "derived_summary": derived_summary,
        "graph_book_count": int(full_sidecar.get("book_count", 0) or 0),
        "graph_relation_count": int(full_sidecar.get("relation_count", 0) or 0),
    }


def materialize_runtime_catalog_library(
    settings: Settings,
    *,
    force_collect: bool = False,
) -> dict[str, Any]:
    entries = _runtime_catalog_entries(settings)

    all_sections = []
    playbook_payloads: list[dict[str, Any]] = []
    processed_slugs: list[str] = []
    collected_slugs: list[str] = []
    errors: list[dict[str, str]] = []
    content_status_counts: dict[str, int] = {}

    for entry in entries:
        try:
            html_path = raw_html_path(settings, entry.book_slug)
            if force_collect or not html_path.exists():
                collect_entry(entry, settings, force=force_collect)
                collected_slugs.append(entry.book_slug)
            runtime_entry = entry_with_collected_metadata(settings, entry)
            html = raw_html_path(settings, entry.book_slug).read_text(encoding="utf-8")
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
            all_sections.extend(sections)
            playbook_payloads.append(project_playbook_document(document).to_dict())
            processed_slugs.append(entry.book_slug)
            status = str(inferred_entry.content_status or "unknown")
            content_status_counts[status] = content_status_counts.get(status, 0) + 1
        except Exception as exc:  # noqa: BLE001
            errors.append({"book_slug": entry.book_slug, "message": str(exc)})

    official_normalized_rows = [section.to_dict() for section in all_sections]
    official_chunk_rows = [chunk.to_dict() for chunk in chunk_sections(all_sections, settings)]

    retained_normalized_rows = _retain_non_official_rows(_read_jsonl_rows(settings.normalized_docs_path))
    retained_chunk_rows = _retain_non_official_rows(_read_jsonl_rows(settings.chunks_path))
    retained_playbook_rows = _retain_non_official_non_derived_playbook_rows(
        _read_jsonl_rows(settings.playbook_documents_path)
    )

    merged_normalized_rows = retained_normalized_rows + official_normalized_rows
    merged_chunk_rows = retained_chunk_rows + official_chunk_rows
    merged_playbook_rows = retained_playbook_rows + sorted(
        playbook_payloads,
        key=lambda row: str(row.get("book_slug") or ""),
    )

    _write_jsonl_rows(settings.playbook_documents_path, merged_playbook_rows)

    official_slugs = {
        str(payload.get("book_slug") or "").strip()
        for payload in playbook_payloads
        if str(payload.get("book_slug") or "").strip()
    }
    _cleanup_stale_official_book_files(settings.playbook_books_dir, expected_slugs=official_slugs)
    _write_official_playbook_payloads(settings.playbook_books_dir, playbook_payloads)

    derived_summary = materialize_derived_playbooks(settings)
    derived_sections = _project_materialized_derived_sections(settings)
    derived_normalized_rows = [section.to_dict() for section in derived_sections]
    derived_chunk_rows = [chunk.to_dict() for chunk in chunk_sections(derived_sections, settings)]

    merged_normalized_rows = retained_normalized_rows + official_normalized_rows + derived_normalized_rows
    merged_chunk_rows = retained_chunk_rows + official_chunk_rows + derived_chunk_rows

    _write_jsonl_rows(settings.normalized_docs_path, merged_normalized_rows)
    _write_jsonl_rows(settings.chunks_path, merged_chunk_rows)
    _write_jsonl_rows(settings.bm25_corpus_path, [_bm25_row(row) for row in merged_chunk_rows])

    graph_refresh = refresh_active_runtime_graph_artifacts(
        settings,
        refresh_full_sidecar=True,
    )
    full_sidecar = dict(graph_refresh.get("full_sidecar", {}))

    return {
        "runtime_catalog_count": len(entries),
        "processed_count": len(processed_slugs),
        "collected_count": len(collected_slugs),
        "official_playbook_count": len(playbook_payloads),
        "official_section_count": len(official_normalized_rows),
        "official_chunk_count": len(official_chunk_rows),
        "derived_playbook_count": int(derived_summary.get("generated_count", 0) or 0),
        "derived_section_count": len(derived_normalized_rows),
        "derived_chunk_count": len(derived_chunk_rows),
        "content_status_counts": dict(sorted(content_status_counts.items())),
        "derived_summary": derived_summary,
        "graph_book_count": int(full_sidecar.get("book_count", 0) or 0),
        "graph_relation_count": int(full_sidecar.get("relation_count", 0) or 0),
        "errors": errors,
    }
