from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from play_book_studio.config.settings import Settings, load_settings
from play_book_studio.ingestion.chunking import chunk_sections
from play_book_studio.ingestion.models import NormalizedSection
from play_book_studio.ingestion.sentence_model import load_sentence_model
from play_book_studio.intake.artifact_bundle import build_customer_pack_relations_payload
from play_book_studio.intake.models import CustomerPackDraftRecord
from play_book_studio.intake.private_boundary import summarize_private_runtime_boundary
from play_book_studio.intake.service import evaluate_canonical_book_quality


PRIVATE_CORPUS_VERSION = "customer_private_corpus_v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def customer_pack_private_corpus_dir(settings: Settings, draft_id: str) -> Path:
    return settings.customer_pack_corpus_dir / str(draft_id).strip()


def customer_pack_private_chunks_path(settings: Settings, draft_id: str) -> Path:
    return customer_pack_private_corpus_dir(settings, draft_id) / "chunks.jsonl"


def customer_pack_private_bm25_path(settings: Settings, draft_id: str) -> Path:
    return customer_pack_private_corpus_dir(settings, draft_id) / "bm25_corpus.jsonl"


def customer_pack_private_vector_path(settings: Settings, draft_id: str) -> Path:
    return customer_pack_private_corpus_dir(settings, draft_id) / "vector_store.jsonl"


def customer_pack_private_relations_path(settings: Settings, draft_id: str) -> Path:
    return customer_pack_private_corpus_dir(settings, draft_id) / "relations.jsonl"


def customer_pack_private_manifest_path(settings: Settings, draft_id: str) -> Path:
    return customer_pack_private_corpus_dir(settings, draft_id) / "manifest.json"


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _review_status(record: CustomerPackDraftRecord) -> str:
    approval_state = str(record.approval_state or "").strip()
    if approval_state == "approved":
        return "approved"
    if approval_state == "rejected":
        return "rejected"
    if approval_state == "review_required":
        return "needs_review"
    return "unreviewed"


def _record_access_groups(record: CustomerPackDraftRecord) -> tuple[str, ...]:
    explicit = tuple(str(item).strip() for item in (record.access_groups or ()) if str(item).strip())
    if explicit:
        return explicit
    fallback = (
        str(record.workspace_id or "").strip() or "default-workspace",
        str(record.tenant_id or "").strip() or "default-tenant",
    )
    return tuple(item for item in fallback if item)


def _section_to_normalized_section(
    payload: dict[str, Any],
    section: dict[str, Any],
    *,
    record: CustomerPackDraftRecord,
) -> NormalizedSection:
    title = str(payload.get("title") or payload.get("book_slug") or record.draft_id).strip() or record.draft_id
    heading = str(section.get("heading") or title).strip() or title
    language_hint = str(payload.get("language_hint") or "ko").strip() or "ko"
    section_path = [
        str(item).strip()
        for item in (section.get("section_path") or [])
        if str(item).strip()
    ]
    provider_egress_policy = str(record.provider_egress_policy or "").strip() or "local_only"
    source_type = str(payload.get("playbook_family") or payload.get("source_type") or "customer_pack").strip()
    return NormalizedSection(
        book_slug=str(payload.get("book_slug") or record.draft_id).strip() or record.draft_id,
        book_title=title,
        heading=heading,
        section_level=int(section.get("section_level") or 2),
        section_path=section_path,
        anchor=str(section.get("anchor") or "").strip(),
        source_url=str(section.get("source_url") or payload.get("source_uri") or "").strip(),
        viewer_path=str(section.get("viewer_path") or "").strip(),
        text=str(section.get("text") or "").strip(),
        section_id=str(section.get("section_key") or section.get("anchor") or "").strip(),
        semantic_role=str(section.get("semantic_role") or "unknown").strip() or "unknown",
        block_kinds=tuple(str(item) for item in (section.get("block_kinds") or []) if str(item).strip()),
        source_language=language_hint,
        display_language=language_hint,
        translation_status="approved_ko" if language_hint == "ko" else "original",
        translation_stage="approved_ko" if language_hint == "ko" else "original",
        source_id=f"customer_pack:{record.draft_id}",
        source_lane=str(record.source_lane or "customer_source_first_pack").strip() or "customer_source_first_pack",
        source_type=source_type,
        source_collection="uploaded",
        product=str(payload.get("inferred_product") or "customer_pack").strip() or "customer_pack",
        version=str(payload.get("inferred_version") or record.draft_id).strip() or record.draft_id,
        locale=language_hint,
        original_title=title,
        review_status=_review_status(record),
        trust_score=1.0,
        verifiability="anchor_backed",
        updated_at=str(record.updated_at or ""),
        parsed_artifact_id=f"customer-pack:{record.draft_id}",
        tenant_id=str(record.tenant_id or "").strip() or "default-tenant",
        workspace_id=str(record.workspace_id or "").strip() or "default-workspace",
        parent_pack_id=str(record.plan.pack_id or "").strip() or f"customer-pack:{record.draft_id}",
        pack_version=str(record.draft_id),
        bundle_scope="customer_pack",
        classification=str(record.classification or "").strip() or "private",
        access_groups=_record_access_groups(record),
        provider_egress_policy=provider_egress_policy,
        approval_state=str(record.approval_state or "").strip() or "unreviewed",
        publication_state=str(record.publication_state or "").strip() or "draft",
        redaction_state=str(record.redaction_state or "").strip() or "raw",
        cli_commands=tuple(str(item) for item in (section.get("cli_commands") or []) if str(item).strip()),
        error_strings=tuple(str(item) for item in (section.get("error_strings") or []) if str(item).strip()),
        k8s_objects=tuple(str(item) for item in (section.get("k8s_objects") or []) if str(item).strip()),
        operator_names=tuple(str(item) for item in (section.get("operator_names") or []) if str(item).strip()),
        verification_hints=tuple(str(item) for item in (section.get("verification_hints") or []) if str(item).strip()),
    )


def _bm25_row(chunk_row: dict[str, Any]) -> dict[str, Any]:
    chunk_type = str(chunk_row.get("chunk_type", "reference"))
    semantic_role = str(chunk_row.get("semantic_role") or "").strip()
    if not semantic_role:
        semantic_role = (
            "procedure"
            if chunk_type in {"procedure", "command"}
            else ("concept" if chunk_type == "concept" else "reference")
        )
    return {
        "chunk_id": chunk_row["chunk_id"],
        "book_slug": chunk_row["book_slug"],
        "chapter": chunk_row["chapter"],
        "section": chunk_row["section"],
        "anchor": chunk_row["anchor"],
        "source_url": chunk_row["source_url"],
        "viewer_path": chunk_row["viewer_path"],
        "text": chunk_row["text"],
        "section_path": list(chunk_row.get("section_path") or []),
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
        "semantic_role": semantic_role,
        "block_kinds": list(chunk_row.get("block_kinds") or []),
        "cli_commands": list(chunk_row.get("cli_commands") or []),
        "error_strings": list(chunk_row.get("error_strings") or []),
        "k8s_objects": list(chunk_row.get("k8s_objects") or []),
        "operator_names": list(chunk_row.get("operator_names") or []),
        "verification_hints": list(chunk_row.get("verification_hints") or []),
        "graph_relations": list(chunk_row.get("graph_relations") or []),
        "relation_question_classes": list(chunk_row.get("relation_question_classes") or []),
        "relation_id": str(chunk_row.get("relation_id") or "").strip(),
        "relation_type": str(chunk_row.get("relation_type") or "").strip(),
        "source_entity_slug": str(chunk_row.get("source_entity_slug") or "").strip(),
        "target_entity_slug": str(chunk_row.get("target_entity_slug") or "").strip(),
        "source_label": str(chunk_row.get("source_label") or "").strip(),
        "target_label": str(chunk_row.get("target_label") or "").strip(),
        "truth_owner": str(chunk_row.get("truth_owner") or "").strip(),
        "canonical_book_slug": str(chunk_row.get("canonical_book_slug") or "").strip(),
        "canonical_title": str(chunk_row.get("canonical_title") or "").strip(),
        "asset_slug": str(chunk_row.get("asset_slug") or "").strip(),
        "asset_kind": str(chunk_row.get("asset_kind") or "").strip(),
        "derived_from_book_slug": str(chunk_row.get("derived_from_book_slug") or "").strip(),
        "runtime_truth_label": str(chunk_row.get("runtime_truth_label") or "").strip(),
        "boundary_truth": str(chunk_row.get("boundary_truth") or "").strip(),
        "boundary_badge": str(chunk_row.get("boundary_badge") or "").strip(),
        "lineage_section_key": str(chunk_row.get("lineage_section_key") or "").strip(),
        "lineage_anchor": str(chunk_row.get("lineage_anchor") or "").strip(),
        "lineage_viewer_path": str(chunk_row.get("lineage_viewer_path") or "").strip(),
    }


def _chunk_semantic_role(chunk_type: str) -> str:
    if chunk_type in {"procedure", "command"}:
        return "procedure"
    if chunk_type == "concept":
        return "concept"
    if chunk_type == "troubleshooting":
        return "troubleshooting"
    return "reference"


def _section_lineage_key(*, book_slug: str, section_id: str, anchor: str) -> tuple[str, str]:
    identifier = str(section_id or "").strip() or str(anchor or "").strip()
    return str(book_slug or "").strip(), identifier


def _relation_question_classes(relation: dict[str, Any]) -> list[str]:
    relation_type = str(relation.get("relation_type") or "").strip().lower()
    heading = str(relation.get("heading") or "").strip().lower()
    summary = str(relation.get("summary") or "").strip().lower()
    source_label = str(relation.get("source_label") or "").strip().lower()
    target_label = str(relation.get("target_label") or "").strip().lower()
    blob = " ".join((relation_type, heading, summary, source_label, target_label))
    classes: list[str] = []

    if relation_type == "gate" or any(token in blob for token in ("승인", "gate", "approval", "mr ")):
        classes.append("gate")
    if relation_type in {"flow", "phase_sequence", "sequence"} or any(
        token in blob
        for token in ("flow", "흐름", "순서", "sync", "push", "pull", "배포", "이동")
    ):
        classes.append("flow")
    if any(token in blob for token in ("차이", "비교", "difference", "versus", "vs")):
        classes.append("difference")
    if relation_type == "sequence" or any(
        token in blob for token in ("의존", "dependency", "연계", "연동", "연결", "requires")
    ):
        classes.append("dependency")
    if any(
        token in blob
        for token in ("ownership", "owner", "담당", "주체", "관리자", "운영자", "개발자", "책임")
    ):
        classes.append("ownership")
    if not classes:
        classes.append("dependency")
    deduped: list[str] = []
    for item in classes:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _relation_semantic_role(relation: dict[str, Any]) -> str:
    classes = _relation_question_classes(relation)
    priority = ("gate", "flow", "difference", "dependency", "ownership")
    for item in priority:
        if item in classes:
            return item
    return classes[0] if classes else "dependency"


def _relation_excerpt_text(relation: dict[str, Any]) -> str:
    relation_type = str(relation.get("relation_type") or "").strip() or "sequence"
    source_label = str(relation.get("source_label") or "").strip()
    target_label = str(relation.get("target_label") or "").strip()
    heading = str(relation.get("heading") or "").strip()
    summary = str(relation.get("summary") or "").strip() or f"{source_label} -> {target_label}"
    classes = _relation_question_classes(relation)
    lines = [
        heading,
        summary,
        f"relation_type: {relation_type}",
        f"question_classes: {', '.join(classes)}",
    ]
    if source_label:
        lines.append(f"source_entity: {source_label}")
    if target_label:
        lines.append(f"target_entity: {target_label}")
    figure_asset_name = str(relation.get("figure_asset_name") or "").strip()
    if figure_asset_name:
        lines.append(f"figure_asset: {figure_asset_name}")
    return "\n".join(line for line in lines if line).strip()


def _relation_rows(
    *,
    record: CustomerPackDraftRecord,
    canonical_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    asset_slug = str(canonical_payload.get("asset_slug") or canonical_payload.get("book_slug") or record.draft_id).strip() or record.draft_id
    relation_payload = build_customer_pack_relations_payload(
        record=record,
        payload=canonical_payload,
        asset_slug=asset_slug,
    )
    relation_index = dict(relation_payload.get("candidate_relations") or {})
    if not relation_index:
        return []

    book_slug = str(canonical_payload.get("book_slug") or asset_slug).strip() or asset_slug
    title = str(canonical_payload.get("title") or book_slug).strip() or book_slug
    source_type = str(canonical_payload.get("playbook_family") or canonical_payload.get("source_type") or "customer_pack").strip() or "customer_pack"
    product = str(canonical_payload.get("inferred_product") or "customer_pack").strip() or "customer_pack"
    version = str(canonical_payload.get("inferred_version") or record.draft_id).strip() or record.draft_id
    language_hint = str(canonical_payload.get("language_hint") or "ko").strip() or "ko"
    translation_status = "approved_ko" if language_hint == "ko" else "original"
    asset_kind = str(canonical_payload.get("asset_kind") or "").strip()
    derived_from_book_slug = str(canonical_payload.get("derived_from_book_slug") or "").strip()
    runtime_truth_label = str(canonical_payload.get("runtime_truth_label") or "Customer Source-First Pack").strip() or "Customer Source-First Pack"
    boundary_truth = str(canonical_payload.get("boundary_truth") or "private_customer_pack_runtime").strip() or "private_customer_pack_runtime"
    boundary_badge = str(canonical_payload.get("boundary_badge") or "Private Pack Runtime").strip() or "Private Pack Runtime"

    rows: list[dict[str, Any]] = []
    for ordinal, relation in enumerate(relation_index.values(), start=1):
        relation_id = str(relation.get("relation_id") or "").strip()
        if not relation_id:
            continue
        heading = str(relation.get("heading") or title).strip() or title
        anchor = str(relation.get("anchor") or "").strip()
        viewer_path = str(relation.get("viewer_path") or "").strip()
        semantic_role = _relation_semantic_role(relation)
        question_classes = _relation_question_classes(relation)
        rows.append(
            {
                "chunk_id": f"{record.draft_id}:relation:{relation_id}",
                "book_slug": book_slug,
                "chapter": title,
                "section": heading,
                "section_id": relation_id,
                "section_path": [heading, semantic_role],
                "anchor": anchor,
                "source_url": str(relation.get("source_url") or "").strip(),
                "viewer_path": viewer_path,
                "text": _relation_excerpt_text(relation),
                "chunk_type": "relation",
                "source_id": f"customer_pack:{record.draft_id}",
                "source_lane": str(record.source_lane or "customer_source_first_pack").strip() or "customer_source_first_pack",
                "source_type": source_type,
                "source_collection": "uploaded",
                "product": product,
                "version": version,
                "locale": language_hint,
                "translation_status": translation_status,
                "review_status": _review_status(record),
                "trust_score": 1.0,
                "parsed_artifact_id": f"customer-pack:{record.draft_id}",
                "semantic_role": semantic_role,
                "block_kinds": ["relation", *question_classes],
                "cli_commands": [],
                "error_strings": [],
                "k8s_objects": [],
                "operator_names": [],
                "verification_hints": [],
                "graph_relations": question_classes,
                "relation_id": relation_id,
                "relation_type": str(relation.get("relation_type") or "").strip(),
                "relation_question_classes": question_classes,
                "source_entity_slug": str(relation.get("source_entity_slug") or "").strip(),
                "target_entity_slug": str(relation.get("target_entity_slug") or "").strip(),
                "source_label": str(relation.get("source_label") or "").strip(),
                "target_label": str(relation.get("target_label") or "").strip(),
                "group_index": int(relation.get("group_index") or ordinal),
                "truth_owner": "canonical_json_bundle",
                "canonical_book_slug": book_slug,
                "canonical_title": title,
                "asset_slug": asset_slug,
                "asset_kind": asset_kind,
                "derived_from_book_slug": derived_from_book_slug,
                "runtime_truth_label": runtime_truth_label,
                "boundary_truth": boundary_truth,
                "boundary_badge": boundary_badge,
                "lineage_section_key": str(relation.get("section_key") or "").strip(),
                "lineage_anchor": anchor,
                "lineage_viewer_path": viewer_path,
            }
        )
    return rows


def _lineage_indexes(
    *,
    canonical_payload: dict[str, Any],
    derived_payloads: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    payloads = [dict(canonical_payload), *[dict(item) for item in derived_payloads]]
    canonical_book_slug = str(canonical_payload.get("book_slug") or "").strip()
    canonical_title = str(canonical_payload.get("title") or "").strip()
    asset_index: dict[str, dict[str, Any]] = {}
    section_index: dict[tuple[str, str], dict[str, Any]] = {}
    for payload in payloads:
        book_slug = str(payload.get("book_slug") or "").strip()
        if not book_slug:
            continue
        asset_index[book_slug] = {
            "truth_owner": "canonical_json_bundle",
            "canonical_book_slug": canonical_book_slug or book_slug,
            "canonical_title": canonical_title or str(payload.get("title") or book_slug).strip(),
            "asset_slug": str(payload.get("asset_slug") or book_slug).strip() or book_slug,
            "asset_kind": str(payload.get("asset_kind") or "").strip(),
            "derived_from_book_slug": str(payload.get("derived_from_book_slug") or "").strip(),
            "runtime_truth_label": str(payload.get("runtime_truth_label") or "Customer Source-First Pack").strip(),
            "boundary_truth": str(payload.get("boundary_truth") or "private_customer_pack_runtime").strip(),
            "boundary_badge": str(payload.get("boundary_badge") or "Private Pack Runtime").strip(),
        }
        sections = [
            dict(section)
            for section in (payload.get("sections") or [])
            if isinstance(section, dict)
        ]
        for section in sections:
            key = _section_lineage_key(
                book_slug=book_slug,
                section_id=str(section.get("section_key") or section.get("section_id") or "").strip(),
                anchor=str(section.get("anchor") or "").strip(),
            )
            if not key[1]:
                continue
            section_index[key] = {
                "semantic_role": str(section.get("semantic_role") or "").strip(),
                "block_kinds": list(section.get("block_kinds") or []),
                "lineage_section_key": str(section.get("section_key") or section.get("section_id") or "").strip(),
                "lineage_anchor": str(section.get("anchor") or "").strip(),
                "lineage_viewer_path": str(section.get("viewer_path") or "").strip(),
            }
    return asset_index, section_index


def _enrich_chunk_rows_with_lineage(
    chunk_rows: list[dict[str, Any]],
    *,
    canonical_payload: dict[str, Any],
    derived_payloads: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    asset_index, section_index = _lineage_indexes(
        canonical_payload=canonical_payload,
        derived_payloads=derived_payloads,
    )
    enriched_rows: list[dict[str, Any]] = []
    for row in chunk_rows:
        book_slug = str(row.get("book_slug") or "").strip()
        section_key = _section_lineage_key(
            book_slug=book_slug,
            section_id=str(row.get("section_id") or "").strip(),
            anchor=str(row.get("anchor") or "").strip(),
        )
        asset_payload = dict(asset_index.get(book_slug) or {})
        section_payload = dict(section_index.get(section_key) or {})
        semantic_role = str(section_payload.get("semantic_role") or row.get("semantic_role") or "").strip()
        if not semantic_role:
            semantic_role = _chunk_semantic_role(str(row.get("chunk_type") or "reference").strip())
        block_kinds = [
            str(item).strip()
            for item in (
                section_payload.get("block_kinds")
                or row.get("block_kinds")
                or []
            )
            if str(item).strip()
        ]
        enriched_rows.append(
            {
                **row,
                **asset_payload,
                **section_payload,
                "semantic_role": semantic_role,
                "block_kinds": block_kinds,
            }
        )
    return enriched_rows


def _encode_texts_locally(
    settings: Settings,
    texts: list[str],
) -> list[list[float]]:
    if not texts:
        return []
    model = load_sentence_model(settings.embedding_model, settings.embedding_device)
    encoded = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    return [list(map(float, row.tolist())) for row in encoded]


def _failed_private_corpus_payload(
    *,
    error: str,
    book_count: int,
) -> dict[str, Any]:
    return {
        "normalized_sections": [],
        "chunk_rows": [],
        "relation_rows": [],
        "bm25_rows": [],
        "vector_rows": [],
        "materialization_status": "failed",
        "materialization_error": str(error or "").strip(),
        "vector_status": "materialization_failed",
        "vector_error": "",
        "book_count": int(book_count),
    }


def build_customer_pack_private_corpus_rows(
    *,
    settings: Settings,
    record: CustomerPackDraftRecord,
    canonical_payload: dict[str, Any],
    derived_payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    payloads = [dict(canonical_payload), *[dict(item) for item in derived_payloads]]
    normalized_sections: list[NormalizedSection] = []
    for payload in payloads:
        sections = [
            dict(section)
            for section in (payload.get("sections") or [])
            if isinstance(section, dict)
        ]
        for section in sections:
            text = str(section.get("text") or "").strip()
            if not text:
                continue
            normalized_sections.append(
                _section_to_normalized_section(payload, section, record=record)
            )
    materialization_status = "empty"
    materialization_error = ""
    chunks = []
    chunk_rows: list[dict[str, Any]] = []
    relation_rows: list[dict[str, Any]] = _relation_rows(
        record=record,
        canonical_payload=canonical_payload,
    )
    bm25_rows: list[dict[str, Any]] = []
    if normalized_sections:
        try:
            chunks = chunk_sections(normalized_sections, settings)
            chunk_rows = [chunk.to_dict() for chunk in chunks]
            chunk_rows = _enrich_chunk_rows_with_lineage(
                chunk_rows,
                canonical_payload=canonical_payload,
                derived_payloads=derived_payloads,
            )
            materialization_status = "ready" if chunk_rows or relation_rows else "empty"
        except Exception as exc:  # noqa: BLE001
            materialization_status = "failed"
            materialization_error = str(exc)
    retrieval_rows = [*chunk_rows, *relation_rows]
    if retrieval_rows and materialization_status == "empty":
        materialization_status = "ready"
    if retrieval_rows:
        bm25_rows = [_bm25_row(row) for row in retrieval_rows]
    vector_rows: list[dict[str, Any]] = []
    vector_status = "skipped"
    vector_error = ""
    if retrieval_rows:
        try:
            vectors = _encode_texts_locally(settings, [str(row.get("text") or "") for row in retrieval_rows])
            vector_rows = [
                {
                    **row,
                    "vector": vector,
                }
                for row, vector in zip(retrieval_rows, vectors, strict=False)
            ]
            vector_status = "ready"
        except Exception as exc:  # noqa: BLE001
            vector_status = "skipped"
            vector_error = str(exc)
    return {
        "normalized_sections": [section.to_dict() for section in normalized_sections],
        "chunk_rows": chunk_rows,
        "relation_rows": relation_rows,
        "bm25_rows": bm25_rows,
        "vector_rows": vector_rows,
        "materialization_status": materialization_status,
        "materialization_error": materialization_error,
        "vector_status": vector_status,
        "vector_error": vector_error,
        "book_count": len(payloads),
    }


def materialize_customer_pack_private_corpus(
    root_dir: str | Path,
    *,
    record: CustomerPackDraftRecord,
    canonical_payload: dict[str, Any],
    derived_payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    settings = load_settings(root_dir)
    draft_id = str(record.draft_id).strip()
    corpus_dir = customer_pack_private_corpus_dir(settings, draft_id)
    manifest_path = customer_pack_private_manifest_path(settings, draft_id)
    corpus_dir.mkdir(parents=True, exist_ok=True)
    try:
        payload = build_customer_pack_private_corpus_rows(
            settings=settings,
            record=record,
            canonical_payload=canonical_payload,
            derived_payloads=derived_payloads,
        )
    except Exception as exc:  # noqa: BLE001
        payload = _failed_private_corpus_payload(
            error=str(exc),
            book_count=1 + len(derived_payloads),
        )
    chunk_rows = payload["chunk_rows"]
    relation_rows = payload["relation_rows"]
    bm25_rows = payload["bm25_rows"]
    vector_rows = payload["vector_rows"]
    _write_jsonl(customer_pack_private_chunks_path(settings, draft_id), chunk_rows)
    _write_jsonl(customer_pack_private_relations_path(settings, draft_id), relation_rows)
    _write_jsonl(customer_pack_private_bm25_path(settings, draft_id), bm25_rows)
    if vector_rows:
        _write_jsonl(customer_pack_private_vector_path(settings, draft_id), vector_rows)
    else:
        customer_pack_private_vector_path(settings, draft_id).unlink(missing_ok=True)
    manifest = {
        "artifact_version": PRIVATE_CORPUS_VERSION,
        "truth_owner": "canonical_json_bundle",
        "draft_id": draft_id,
        "tenant_id": str(record.tenant_id or "").strip() or "default-tenant",
        "workspace_id": str(record.workspace_id or "").strip() or "default-workspace",
        "pack_id": str(record.plan.pack_id or "").strip() or f"customer-pack:{draft_id}",
        "pack_version": draft_id,
        "classification": str(record.classification or "").strip() or "private",
        "access_groups": list(_record_access_groups(record)),
        "provider_egress_policy": str(record.provider_egress_policy or "").strip() or "local_only",
        "approval_state": str(record.approval_state or "").strip() or "unreviewed",
        "publication_state": str(record.publication_state or "").strip() or "draft",
        "redaction_state": str(record.redaction_state or "").strip() or "raw",
        "source_lane": str(record.source_lane or "customer_source_first_pack").strip() or "customer_source_first_pack",
        "source_collection": "uploaded",
        "boundary_truth": "private_customer_pack_runtime",
        "runtime_truth_label": "Customer Source-First Pack",
        "boundary_badge": "Private Pack Runtime",
        "canonical_book_slug": str(canonical_payload.get("book_slug") or draft_id).strip() or draft_id,
        "canonical_title": str(canonical_payload.get("title") or draft_id).strip() or draft_id,
        "asset_slugs": [
            str(item.get("asset_slug") or item.get("book_slug") or draft_id).strip() or draft_id
            for item in [dict(canonical_payload), *[dict(item) for item in derived_payloads]]
        ],
        "book_slugs": [
            str(item.get("book_slug") or item.get("asset_slug") or draft_id).strip() or draft_id
            for item in [dict(canonical_payload), *[dict(item) for item in derived_payloads]]
        ],
        "playable_asset_count": int(canonical_payload.get("playable_asset_count") or 1 + len(derived_payloads)),
        "derived_asset_count": int(canonical_payload.get("derived_asset_count") or len(derived_payloads)),
        "book_count": int(payload["book_count"]),
        "section_count": len(payload["normalized_sections"]),
        "materialization_status": str(payload["materialization_status"]),
        "materialization_error": str(payload["materialization_error"] or ""),
        "chunk_count": len(chunk_rows),
        "relation_rows_path": str(customer_pack_private_relations_path(settings, draft_id)),
        "relation_row_count": len(relation_rows),
        "relation_truth_owner": "canonical_json_bundle",
        "relation_bm25_ready": bool(relation_rows),
        "anchor_lineage_count": sum(1 for row in chunk_rows if str(row.get("anchor") or "").strip()),
        "bm25_ready": bool(bm25_rows),
        "vector_status": str(payload["vector_status"]),
        "vector_chunk_count": len(vector_rows),
        "vector_error": str(payload["vector_error"] or ""),
        "manifest_path": str(manifest_path),
        "updated_at": _utc_now(),
    }
    quality = evaluate_canonical_book_quality(canonical_payload, corpus_manifest=manifest)
    grade_gate = dict(quality.get("grade_gate") or {})
    promotion_gate = dict(grade_gate.get("promotion_gate") or {})
    citation_gate = dict(grade_gate.get("citation_gate") or {})
    retrieval_gate = dict(grade_gate.get("retrieval_gate") or {})
    manifest["quality_status"] = str(quality.get("quality_status") or "review")
    manifest["quality_score"] = int(quality.get("quality_score") or 0)
    manifest["quality_flags"] = list(quality.get("quality_flags") or [])
    manifest["quality_summary"] = str(quality.get("quality_summary") or "")
    manifest["shared_grade"] = str(quality.get("shared_grade") or "blocked")
    manifest["grade_gate"] = grade_gate
    manifest["read_ready"] = bool(promotion_gate.get("read_ready"))
    manifest["publish_ready"] = bool(promotion_gate.get("publish_ready"))
    manifest["citation_landing_status"] = str(citation_gate.get("status") or "missing")
    manifest["retrieval_ready"] = bool(retrieval_gate.get("ready"))
    boundary_summary = summarize_private_runtime_boundary(manifest)
    manifest["runtime_eligible"] = bool(boundary_summary["runtime_eligible"])
    manifest["boundary_fail_reasons"] = list(boundary_summary["fail_reasons"])
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def delete_customer_pack_private_corpus(root_dir: str | Path, draft_id: str) -> None:
    settings = load_settings(root_dir)
    corpus_dir = customer_pack_private_corpus_dir(settings, draft_id)
    if not corpus_dir.exists():
        return
    for path in sorted(corpus_dir.glob("*")):
        path.unlink(missing_ok=True)
    corpus_dir.rmdir()


__all__ = [
    "PRIVATE_CORPUS_VERSION",
    "build_customer_pack_private_corpus_rows",
    "customer_pack_private_bm25_path",
    "customer_pack_private_chunks_path",
    "customer_pack_private_corpus_dir",
    "customer_pack_private_manifest_path",
    "customer_pack_private_relations_path",
    "customer_pack_private_vector_path",
    "delete_customer_pack_private_corpus",
    "materialize_customer_pack_private_corpus",
]
