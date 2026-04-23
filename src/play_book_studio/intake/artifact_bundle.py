from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import CustomerPackDraftRecord


CUSTOMER_PACK_ARTIFACT_BUNDLE_VERSION = "customer_pack_artifact_bundle_v1"
CUSTOMER_PACK_RELATIONS_VERSION = "customer_pack_relations_v1"
CUSTOMER_PACK_FIGURE_ASSETS_VERSION = "customer_pack_figure_assets_v1"
CUSTOMER_PACK_CITATIONS_VERSION = "customer_pack_citations_v1"

_SIDECAR_SUFFIXES = (
    ".manifest.json",
    ".relations.json",
    ".figure_assets.json",
    ".citations.json",
)


def customer_pack_bundle_manifest_path(books_dir: Path, asset_slug: str) -> Path:
    return books_dir / f"{asset_slug}.manifest.json"


def customer_pack_relations_path(books_dir: Path, asset_slug: str) -> Path:
    return books_dir / f"{asset_slug}.relations.json"


def customer_pack_figure_assets_path(books_dir: Path, asset_slug: str) -> Path:
    return books_dir / f"{asset_slug}.figure_assets.json"


def customer_pack_citations_path(books_dir: Path, asset_slug: str) -> Path:
    return books_dir / f"{asset_slug}.citations.json"


def is_customer_pack_bundle_sidecar_path(path: Path) -> bool:
    name = path.name.lower()
    return any(name.endswith(suffix) for suffix in _SIDECAR_SUFFIXES)


def is_customer_pack_book_payload_path(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == ".json" and not is_customer_pack_bundle_sidecar_path(path)


def iter_customer_pack_book_payload_paths(books_dir: Path) -> list[Path]:
    if not books_dir.exists():
        return []
    return sorted(path for path in books_dir.glob("*.json") if is_customer_pack_book_payload_path(path))


def write_json_payload(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_customer_pack_artifact_bundle(
    *,
    record: CustomerPackDraftRecord,
    payload: dict[str, Any],
    book_path: Path,
    corpus_manifest: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    asset_slug = str(payload.get("asset_slug") or payload.get("book_slug") or record.draft_id).strip() or record.draft_id
    books_dir = book_path.parent
    manifest_path = customer_pack_bundle_manifest_path(books_dir, asset_slug)
    relations_path = customer_pack_relations_path(books_dir, asset_slug)
    figure_assets_path = customer_pack_figure_assets_path(books_dir, asset_slug)
    citations_path = customer_pack_citations_path(books_dir, asset_slug)

    relations_payload = build_customer_pack_relations_payload(record=record, payload=payload, asset_slug=asset_slug)
    figure_assets_payload = build_customer_pack_figure_assets_payload(
        record=record,
        payload=payload,
        asset_slug=asset_slug,
    )
    citations_payload = build_customer_pack_citations_payload(record=record, payload=payload, asset_slug=asset_slug)
    manifest_payload = build_customer_pack_artifact_manifest(
        record=record,
        payload=payload,
        asset_slug=asset_slug,
        book_path=book_path,
        manifest_path=manifest_path,
        relations_path=relations_path,
        figure_assets_path=figure_assets_path,
        citations_path=citations_path,
        corpus_manifest=corpus_manifest,
        relation_count=len(relations_payload.get("section_relation_index") or []),
        figure_count=len(figure_assets_payload.get("figure_assets") or []),
        citation_count=len(citations_payload.get("citations") or []),
    )

    enriched_payload = dict(payload)
    enriched_payload["artifact_bundle"] = {
        "truth_owner": "canonical_json_bundle",
        "asset_slug": asset_slug,
        "asset_kind": str(payload.get("asset_kind") or "").strip(),
        "book_path": str(book_path),
        "manifest_path": str(manifest_path),
        "relations_path": str(relations_path),
        "figure_assets_path": str(figure_assets_path),
        "citations_path": str(citations_path),
        "corpus_manifest_path": str(corpus_manifest.get("manifest_path") or ""),
        "playable_asset_count": int(payload.get("playable_asset_count") or 1),
        "derived_asset_count": int(payload.get("derived_asset_count") or 0),
        "source_lane": str(payload.get("source_lane") or record.source_lane or "customer_source_first_pack").strip(),
        "runtime_truth_label": str(payload.get("runtime_truth_label") or "Customer Source-First Pack").strip(),
        "shared_grade": str(payload.get("shared_grade") or ""),
        "read_ready": bool(((payload.get("grade_gate") or {}).get("promotion_gate") or {}).get("read_ready")),
        "publish_ready": bool(((payload.get("grade_gate") or {}).get("promotion_gate") or {}).get("publish_ready")),
    }
    enriched_payload["artifact_manifest_path"] = str(manifest_path)

    return {
        "book": enriched_payload,
        "manifest": manifest_payload,
        "relations": relations_payload,
        "figure_assets": figure_assets_payload,
        "citations": citations_payload,
    }


def build_customer_pack_artifact_manifest(
    *,
    record: CustomerPackDraftRecord,
    payload: dict[str, Any],
    asset_slug: str,
    book_path: Path,
    manifest_path: Path,
    relations_path: Path,
    figure_assets_path: Path,
    citations_path: Path,
    corpus_manifest: dict[str, Any],
    relation_count: int,
    figure_count: int,
    citation_count: int,
) -> dict[str, Any]:
    sections = _sections(payload)
    evidence = dict(payload.get("customer_pack_evidence") or {})
    return {
        "artifact_version": CUSTOMER_PACK_ARTIFACT_BUNDLE_VERSION,
        "truth_owner": "canonical_json_bundle",
        "draft_id": str(record.draft_id),
        "asset_slug": asset_slug,
        "asset_kind": str(payload.get("asset_kind") or "customer_pack_manual_book").strip() or "customer_pack_manual_book",
        "book_slug": str(payload.get("book_slug") or asset_slug).strip() or asset_slug,
        "title": str(payload.get("title") or asset_slug).strip() or asset_slug,
        "source_type": str(payload.get("playbook_family") or payload.get("source_type") or "customer_pack").strip(),
        "source_lane": str(payload.get("source_lane") or record.source_lane or "customer_source_first_pack").strip()
        or "customer_source_first_pack",
        "source_collection": str(payload.get("source_collection") or "uploaded").strip() or "uploaded",
        "runtime_truth_label": str(payload.get("runtime_truth_label") or "Customer Source-First Pack").strip()
        or "Customer Source-First Pack",
        "boundary_truth": str(payload.get("boundary_truth") or "private_customer_pack_runtime").strip()
        or "private_customer_pack_runtime",
        "boundary_badge": str(payload.get("boundary_badge") or "Private Pack Runtime").strip() or "Private Pack Runtime",
        "tenant_id": str(record.tenant_id or "").strip() or "default-tenant",
        "workspace_id": str(record.workspace_id or "").strip() or "default-workspace",
        "pack_id": str(record.plan.pack_id or "").strip() or f"customer-pack:{record.draft_id}",
        "pack_version": str(record.draft_id),
        "classification": str(record.classification or "").strip() or "private",
        "access_groups": list(record.access_groups or ()),
        "provider_egress_policy": str(record.provider_egress_policy or "").strip() or "local_only",
        "approval_state": str(record.approval_state or "").strip() or "unreviewed",
        "publication_state": str(record.publication_state or "").strip() or "draft",
        "redaction_state": str(record.redaction_state or "").strip() or "raw",
        "runtime_eligible": bool(corpus_manifest.get("runtime_eligible")),
        "boundary_fail_reasons": list(corpus_manifest.get("boundary_fail_reasons") or []),
        "quality_status": str(payload.get("quality_status") or corpus_manifest.get("quality_status") or "review"),
        "quality_score": int(payload.get("quality_score") or corpus_manifest.get("quality_score") or 0),
        "quality_flags": list(payload.get("quality_flags") or corpus_manifest.get("quality_flags") or []),
        "quality_summary": str(payload.get("quality_summary") or corpus_manifest.get("quality_summary") or ""),
        "shared_grade": str(payload.get("shared_grade") or corpus_manifest.get("shared_grade") or "blocked"),
        "grade_gate": dict(payload.get("grade_gate") or corpus_manifest.get("grade_gate") or {}),
        "read_ready": bool(corpus_manifest.get("read_ready")),
        "publish_ready": bool(corpus_manifest.get("publish_ready")),
        "citation_landing_status": str(corpus_manifest.get("citation_landing_status") or "missing"),
        "retrieval_ready": bool(corpus_manifest.get("retrieval_ready")),
        "book_path": str(book_path),
        "manifest_path": str(manifest_path),
        "relations_path": str(relations_path),
        "figure_assets_path": str(figure_assets_path),
        "citations_path": str(citations_path),
        "corpus_manifest_path": str(corpus_manifest.get("manifest_path") or ""),
        "section_count": len(sections),
        "relation_count": int(relation_count),
        "figure_asset_count": int(figure_count),
        "citation_count": int(citation_count),
        "playable_asset_count": int(payload.get("playable_asset_count") or 1),
        "derived_asset_count": int(payload.get("derived_asset_count") or 0),
        "parser_backend": str(payload.get("parser_backend") or evidence.get("parser_backend") or "").strip(),
        "parser_route": str(payload.get("parser_route") or evidence.get("parser_route") or "").strip(),
        "primary_parse_strategy": str(payload.get("primary_parse_strategy") or evidence.get("primary_parse_strategy") or "").strip(),
        "updated_at": str(corpus_manifest.get("updated_at") or ""),
    }


def build_customer_pack_relations_payload(
    *,
    record: CustomerPackDraftRecord,
    payload: dict[str, Any],
    asset_slug: str,
) -> dict[str, Any]:
    sections = _sections(payload)
    section_relation_index = [
        {
            "section_key": str(section.get("section_key") or section.get("anchor") or section.get("ordinal") or "").strip(),
            "heading": str(section.get("heading") or "").strip(),
            "anchor": str(section.get("anchor") or "").strip(),
            "viewer_path": str(section.get("viewer_path") or "").strip(),
            "source_url": str(section.get("source_url") or "").strip(),
            "section_path": [str(item).strip() for item in (section.get("section_path") or []) if str(item).strip()],
            "ordinal": int(section.get("ordinal") or 0),
        }
        for section in sections
    ]
    playable_assets = [
        dict(item)
        for item in (payload.get("playable_assets") or [])
        if isinstance(item, dict)
    ]
    backlinks = [
        {
            "asset_slug": str(item.get("asset_slug") or "").strip(),
            "viewer_path": str(item.get("viewer_path") or "").strip(),
            "family_label": str(item.get("family_label") or "").strip(),
        }
        for item in playable_assets
        if str(item.get("asset_slug") or "").strip() and str(item.get("asset_slug") or "").strip() != asset_slug
    ]
    aliases = [entry["heading"] for entry in section_relation_index if entry["heading"]][:16]
    figure_assets = [
        dict(item)
        for item in (payload.get("figure_assets") or [])
        if isinstance(item, dict)
    ]
    return {
        "artifact_version": CUSTOMER_PACK_RELATIONS_VERSION,
        "draft_id": str(record.draft_id),
        "asset_slug": asset_slug,
        "book_slug": str(payload.get("book_slug") or asset_slug).strip() or asset_slug,
        "related_sections": section_relation_index,
        "section_relation_index": section_relation_index,
        "entity_hubs": [],
        "chat_navigation_aliases": aliases,
        "backlinks": backlinks,
        "runtime_anchor_map": {
            entry["section_key"]: {
                "anchor": entry["anchor"],
                "viewer_path": entry["viewer_path"],
            }
            for entry in section_relation_index
            if entry["section_key"]
        },
        "candidate_relations": [],
        "figure_entity_index": [],
        "figure_section_index": [
            {
                "asset_ref": str(item.get("asset_ref") or "").strip(),
                "viewer_path": str(item.get("viewer_path") or "").strip(),
                "source_page_or_slide": str(item.get("source_page_or_slide") or "").strip(),
            }
            for item in figure_assets
            if str(item.get("asset_ref") or "").strip()
        ],
    }


def build_customer_pack_figure_assets_payload(
    *,
    record: CustomerPackDraftRecord,
    payload: dict[str, Any],
    asset_slug: str,
) -> dict[str, Any]:
    figure_assets = [
        dict(item)
        for item in (payload.get("figure_assets") or [])
        if isinstance(item, dict)
    ]
    return {
        "artifact_version": CUSTOMER_PACK_FIGURE_ASSETS_VERSION,
        "draft_id": str(record.draft_id),
        "asset_slug": asset_slug,
        "book_slug": str(payload.get("book_slug") or asset_slug).strip() or asset_slug,
        "figure_assets": figure_assets,
    }


def build_customer_pack_citations_payload(
    *,
    record: CustomerPackDraftRecord,
    payload: dict[str, Any],
    asset_slug: str,
) -> dict[str, Any]:
    citations: list[dict[str, Any]] = []
    for section in _sections(payload):
        section_id = str(section.get("section_key") or section.get("anchor") or section.get("ordinal") or "").strip()
        anchor = str(section.get("anchor") or "").strip()
        viewer_path = str(section.get("viewer_path") or "").strip()
        source_url = str(section.get("source_url") or "").strip()
        text = str(section.get("text") or "").strip()
        excerpt = text[:240].strip()
        citations.append(
            {
                "doc_id": str(payload.get("book_slug") or asset_slug).strip() or asset_slug,
                "section_id": section_id,
                "block_id": "",
                "anchor_id": anchor,
                "viewer_path": viewer_path,
                "source_url": source_url,
                "citation_excerpt": excerpt,
                "section_heading": str(section.get("heading") or "").strip(),
            }
        )
    return {
        "artifact_version": CUSTOMER_PACK_CITATIONS_VERSION,
        "draft_id": str(record.draft_id),
        "asset_slug": asset_slug,
        "book_slug": str(payload.get("book_slug") or asset_slug).strip() or asset_slug,
        "citations": citations,
    }


def _sections(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(section)
        for section in (payload.get("sections") or [])
        if isinstance(section, dict)
    ]


__all__ = [
    "CUSTOMER_PACK_ARTIFACT_BUNDLE_VERSION",
    "build_customer_pack_artifact_bundle",
    "customer_pack_bundle_manifest_path",
    "customer_pack_citations_path",
    "customer_pack_figure_assets_path",
    "customer_pack_relations_path",
    "is_customer_pack_book_payload_path",
    "iter_customer_pack_book_payload_paths",
    "write_json_payload",
]
