from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from .models import CustomerPackDraftRecord
from .pptx_slide_packets import (
    build_customer_pack_slide_packets_payload,
    customer_pack_slide_packets_path,
)


CUSTOMER_PACK_ARTIFACT_BUNDLE_VERSION = "customer_pack_artifact_bundle_v1"
CUSTOMER_PACK_RELATIONS_VERSION = "customer_pack_relations_v1"
CUSTOMER_PACK_FIGURE_ASSETS_VERSION = "customer_pack_figure_assets_v1"
CUSTOMER_PACK_CITATIONS_VERSION = "customer_pack_citations_v1"

_SIDECAR_SUFFIXES = (
    ".manifest.json",
    ".relations.json",
    ".figure_assets.json",
    ".citations.json",
    ".slide_packets.json",
)
_FIGURE_HEADING_HINTS = ("프로세스", "예시", "구조", "아키텍처", "플로우", "흐름")
_DIAGRAM_ENTITY_SPLIT_RE = re.compile(r"\s*\|\s*")
_ENTITY_SLUG_RE = re.compile(r"[^a-z0-9가-힣]+")
_DOC_CODE_RE = re.compile(r"^[A-Z]{2,}(?:-[A-Z0-9]{2,}){2,}$")
_DATE_ONLY_RE = re.compile(r"^\d{4}[./-]\s*\d{1,2}[./-]\s*\d{1,2}\.?$")
_SYSTEM_HINTS = ("tekton", "argocd", "gitlab", "quay", "itsm", "openshift", "webhook", "cli")
_ROLE_HINTS = ("개발자", "개발리드", "qa", "배포관리자", "운영자", "현업")
_PHASE_HINTS = ("환경", "개발", "검증", "운영", "테스트", "배포", "완료", "형상")
_ACTION_HINTS = ("push", "pull", "sync", "생성", "승인", "적용", "빌드", "반영", "감지", "테스트", "배포", "체크아웃")


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
    slide_packets_path = customer_pack_slide_packets_path(books_dir, asset_slug)
    semantic_payload = _figure_semantic_payload(payload=payload, asset_slug=asset_slug)
    slide_packets_payload = build_customer_pack_slide_packets_payload(
        record=record,
        payload=payload,
        asset_slug=asset_slug,
        book_path=book_path,
    )

    relations_payload = build_customer_pack_relations_payload(
        record=record,
        payload=payload,
        asset_slug=asset_slug,
        semantic_payload=semantic_payload,
    )
    figure_assets_payload = build_customer_pack_figure_assets_payload(
        record=record,
        payload=payload,
        asset_slug=asset_slug,
        semantic_payload=semantic_payload,
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
        slide_packets_path=slide_packets_path if slide_packets_payload else None,
        corpus_manifest=corpus_manifest,
        relation_count=_relation_record_count(relations_payload),
        figure_count=len(figure_assets_payload.get("figure_assets") or []),
        citation_count=len(citations_payload.get("citations") or []),
        slide_packet_count=len(slide_packets_payload.get("slides") or []),
        embedded_asset_count=len(slide_packets_payload.get("embedded_assets") or []),
    )

    enriched_payload = dict(payload)
    if slide_packets_payload:
        enriched_payload["surface_kind"] = "slide_deck"
        enriched_payload["source_unit_kind"] = "slide"
        enriched_payload["source_unit_count"] = int(slide_packets_payload.get("slide_count") or 0)
        enriched_payload["slide_packet_count"] = int(slide_packets_payload.get("slide_count") or 0)
        enriched_payload["slide_asset_count"] = int(slide_packets_payload.get("embedded_asset_count") or 0)
    enriched_payload["artifact_bundle"] = {
        "truth_owner": "canonical_json_bundle",
        "asset_slug": asset_slug,
        "asset_kind": str(payload.get("asset_kind") or "").strip(),
        "book_path": str(book_path),
        "manifest_path": str(manifest_path),
        "relations_path": str(relations_path),
        "figure_assets_path": str(figure_assets_path),
        "citations_path": str(citations_path),
        "slide_packets_path": str(slide_packets_path) if slide_packets_payload else "",
        "corpus_manifest_path": str(corpus_manifest.get("manifest_path") or ""),
        "playable_asset_count": int(payload.get("playable_asset_count") or 1),
        "derived_asset_count": int(payload.get("derived_asset_count") or 0),
        "source_lane": str(payload.get("source_lane") or record.source_lane or "customer_source_first_pack").strip(),
        "runtime_truth_label": str(payload.get("runtime_truth_label") or "Customer Source-First Pack").strip(),
        "shared_grade": str(payload.get("shared_grade") or ""),
        "read_ready": bool(((payload.get("grade_gate") or {}).get("promotion_gate") or {}).get("read_ready")),
        "publish_ready": bool(((payload.get("grade_gate") or {}).get("promotion_gate") or {}).get("publish_ready")),
        "relation_count": _relation_record_count(relations_payload),
        "figure_asset_count": len(figure_assets_payload.get("figure_assets") or []),
        "slide_packet_count": len(slide_packets_payload.get("slides") or []),
        "slide_asset_count": len(slide_packets_payload.get("embedded_assets") or []),
    }
    enriched_payload["artifact_manifest_path"] = str(manifest_path)

    return {
        "book": enriched_payload,
        "manifest": manifest_payload,
        "relations": relations_payload,
        "figure_assets": figure_assets_payload,
        "citations": citations_payload,
        "slide_packets": slide_packets_payload,
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
    slide_packets_path: Path | None,
    corpus_manifest: dict[str, Any],
    relation_count: int,
    figure_count: int,
    citation_count: int,
    slide_packet_count: int,
    embedded_asset_count: int,
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
        "slide_packets_path": str(slide_packets_path) if slide_packets_path is not None else "",
        "corpus_manifest_path": str(corpus_manifest.get("manifest_path") or ""),
        "section_count": len(sections),
        "relation_count": int(relation_count),
        "figure_asset_count": int(figure_count),
        "citation_count": int(citation_count),
        "slide_packet_count": int(slide_packet_count),
        "embedded_asset_count": int(embedded_asset_count),
        "playable_asset_count": int(payload.get("playable_asset_count") or 1),
        "derived_asset_count": int(payload.get("derived_asset_count") or 0),
        "surface_kind": str(payload.get("surface_kind") or "document").strip() or "document",
        "source_unit_kind": str(payload.get("source_unit_kind") or "section").strip() or "section",
        "source_unit_count": int(
            payload.get("source_unit_count")
            or slide_packet_count
            or len(sections)
            or 0
        ),
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
    semantic_payload: dict[str, Any] | None = None,
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
            "href": str(section.get("viewer_path") or "").strip(),
            "label": str(section.get("heading") or "").strip(),
            "summary": str(section.get("heading") or "").strip(),
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
    semantic = dict(semantic_payload or _figure_semantic_payload(payload=payload, asset_slug=asset_slug))
    figure_assets = [dict(item) for item in (semantic.get("figure_assets") or []) if isinstance(item, dict)]
    entity_hubs = dict(semantic.get("entity_hubs") or {})
    candidate_relations = dict(semantic.get("candidate_relations") or {})
    figure_entity_index = dict(semantic.get("figure_entity_index") or {})
    figure_section_index = dict(semantic.get("figure_section_index") or {})
    section_by_entity = dict(semantic.get("section_by_entity") or {})
    chat_navigation_aliases = dict(semantic.get("chat_navigation_aliases") or {})
    book_slug = str(payload.get("book_slug") or asset_slug).strip() or asset_slug
    return {
        "artifact_version": CUSTOMER_PACK_RELATIONS_VERSION,
        "draft_id": str(record.draft_id),
        "asset_slug": asset_slug,
        "book_slug": book_slug,
        "related_sections": section_relation_index,
        "section_relation_index": {
            "entries": section_relation_index,
            "by_book": {book_slug: section_relation_index},
            "by_entity": section_by_entity,
        },
        "entity_hubs": entity_hubs,
        "chat_navigation_aliases": chat_navigation_aliases or {
            book_slug: [
                {
                    "label": alias,
                    "href": str(entry.get("viewer_path") or "").strip(),
                    "kind": "book",
                    "summary": str(entry.get("heading") or "").strip(),
                }
                for alias, entry in zip(aliases, section_relation_index, strict=False)
                if alias and str(entry.get("viewer_path") or "").strip()
            ]
        },
        "backlinks": backlinks,
        "runtime_anchor_map": {
            entry["section_key"]: {
                "anchor": entry["anchor"],
                "viewer_path": entry["viewer_path"],
            }
            for entry in section_relation_index
            if entry["section_key"]
        },
        "candidate_relations": candidate_relations,
        "figure_entity_index": figure_entity_index,
        "figure_section_index": figure_section_index or {
            "by_slug": {
                book_slug: [
                    {
                        "asset_name": str(item.get("asset_name") or "").strip(),
                        "asset_ref": str(item.get("asset_ref") or "").strip(),
                        "viewer_path": str(item.get("viewer_path") or "").strip(),
                        "section_href": str(item.get("viewer_path") or "").strip(),
                        "section_anchor": str(item.get("source_anchor") or "").strip(),
                        "section_key": str(item.get("source_section_key") or "").strip(),
                        "caption": str(item.get("caption") or "").strip(),
                        "section_path": str(item.get("section_hint") or "").strip(),
                        "source_page_or_slide": str(item.get("source_page_or_slide") or "").strip(),
                    }
                    for item in figure_assets
                    if str(item.get("asset_ref") or "").strip()
                ]
            }
        },
    }


def build_customer_pack_figure_assets_payload(
    *,
    record: CustomerPackDraftRecord,
    payload: dict[str, Any],
    asset_slug: str,
    semantic_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    semantic = dict(semantic_payload or _figure_semantic_payload(payload=payload, asset_slug=asset_slug))
    figure_assets = [dict(item) for item in (semantic.get("figure_assets") or []) if isinstance(item, dict)]
    book_slug = str(payload.get("book_slug") or asset_slug).strip() or asset_slug
    return {
        "artifact_version": CUSTOMER_PACK_FIGURE_ASSETS_VERSION,
        "draft_id": str(record.draft_id),
        "asset_slug": asset_slug,
        "book_slug": book_slug,
        "entries": {book_slug: figure_assets},
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


def _relation_record_count(relations_payload: dict[str, Any]) -> int:
    section_payload = relations_payload.get("section_relation_index")
    if isinstance(section_payload, dict):
        section_count = len(section_payload.get("entries") or [])
    else:
        section_count = len(section_payload or [])
    candidate_relations = relations_payload.get("candidate_relations")
    if isinstance(candidate_relations, dict):
        relation_count = len(candidate_relations)
    else:
        relation_count = len(candidate_relations or [])
    return section_count + relation_count


def _figure_semantic_payload(*, payload: dict[str, Any], asset_slug: str) -> dict[str, Any]:
    sections = _figure_sections(payload)
    book_slug = str(payload.get("book_slug") or asset_slug).strip() or asset_slug
    figure_assets = _resolved_figure_assets(payload=payload, asset_slug=asset_slug)
    figure_by_section = {
        str(item.get("source_section_key") or "").strip(): dict(item)
        for item in figure_assets
        if str(item.get("source_section_key") or "").strip()
    }
    entity_hubs: dict[str, dict[str, Any]] = {}
    candidate_relations: dict[str, dict[str, Any]] = {}
    figure_by_entity: dict[str, list[dict[str, Any]]] = {}
    by_figure: dict[str, list[dict[str, str]]] = {}
    section_by_entity: dict[str, list[dict[str, Any]]] = {}
    alias_items: list[dict[str, str]] = []

    for section in sections:
        section_key = str(section.get("section_key") or section.get("anchor") or section.get("ordinal") or "").strip()
        if not section_key:
            continue
        heading = str(section.get("heading") or "").strip()
        viewer_path = str(section.get("viewer_path") or "").strip()
        figure_asset = dict(figure_by_section.get(section_key) or {})
        asset_name = str(figure_asset.get("asset_name") or "").strip()
        asset_ref = str(figure_asset.get("asset_ref") or "").strip()
        groups = _figure_groups(str(section.get("text") or ""))
        for group_index, group in enumerate(groups, start=1):
            if len(group) < 1:
                continue
            entity_slugs: list[str] = []
            for label in group:
                entity = _ensure_entity_hub(
                    entity_hubs,
                    label=label,
                    book_slug=book_slug,
                    section=section,
                    asset_ref=asset_ref,
                )
                entity_slugs.append(str(entity.get("entity_slug") or "").strip())
                if asset_name:
                    by_figure.setdefault(asset_name, [])
                    if all(str(item.get("entity_slug") or "").strip() != entity["entity_slug"] for item in by_figure[asset_name]):
                        by_figure[asset_name].append(
                            {
                                "entity_slug": entity["entity_slug"],
                                "label": entity["title"],
                                "entity_type": str(entity.get("entity_type") or "").strip(),
                            }
                        )
                    figure_by_entity.setdefault(entity["entity_slug"], [])
                    entry = {
                        "asset_name": asset_name,
                        "asset_ref": asset_ref,
                        "viewer_path": viewer_path,
                        "book_slug": book_slug,
                    }
                    if entry not in figure_by_entity[entity["entity_slug"]]:
                        figure_by_entity[entity["entity_slug"]].append(entry)
                section_by_entity.setdefault(entity["entity_slug"], [])
                section_entry = {
                    "href": viewer_path,
                    "label": heading,
                    "summary": heading,
                    "section_key": section_key,
                    "anchor": str(section.get("anchor") or "").strip(),
                }
                if section_entry not in section_by_entity[entity["entity_slug"]]:
                    section_by_entity[entity["entity_slug"]].append(section_entry)
            for relation_index, (source_label, target_label) in enumerate(zip(group, group[1:], strict=False), start=1):
                source_entity = _ensure_entity_hub(
                    entity_hubs,
                    label=source_label,
                    book_slug=book_slug,
                    section=section,
                    asset_ref=asset_ref,
                )
                target_entity = _ensure_entity_hub(
                    entity_hubs,
                    label=target_label,
                    book_slug=book_slug,
                    section=section,
                    asset_ref=asset_ref,
                )
                relation_id = _relation_slug(
                    book_slug=book_slug,
                    section_key=section_key,
                    source_slug=source_entity["entity_slug"],
                    target_slug=target_entity["entity_slug"],
                    ordinal=relation_index,
                )
                candidate_relations[relation_id] = {
                    "relation_id": relation_id,
                    "book_slug": book_slug,
                    "heading": heading,
                    "relation_type": _relation_type(source_label, target_label),
                    "source_entity_slug": source_entity["entity_slug"],
                    "target_entity_slug": target_entity["entity_slug"],
                    "source_label": source_entity["title"],
                    "target_label": target_entity["title"],
                    "summary": f"{source_entity['title']} -> {target_entity['title']}",
                    "figure_asset_ref": asset_ref,
                    "figure_asset_name": asset_name,
                    "section_key": section_key,
                    "anchor": str(section.get("anchor") or "").strip(),
                    "viewer_path": viewer_path,
                    "source_url": str(section.get("source_url") or "").strip(),
                    "group_index": group_index,
                    "entity_slugs": entity_slugs,
                }
        if viewer_path and heading:
            alias_items.append(
                {
                    "label": heading,
                    "href": viewer_path,
                    "kind": "book",
                    "summary": heading,
                }
            )

    figure_section_entries = [
        {
            "asset_name": str(item.get("asset_name") or "").strip(),
            "asset_ref": str(item.get("asset_ref") or "").strip(),
            "viewer_path": str(item.get("viewer_path") or "").strip(),
            "section_href": str(item.get("viewer_path") or "").strip(),
            "section_anchor": str(item.get("source_anchor") or "").strip(),
            "section_key": str(item.get("source_section_key") or "").strip(),
            "caption": str(item.get("caption") or "").strip(),
            "section_path": str(item.get("section_hint") or "").strip(),
            "source_page_or_slide": str(item.get("source_page_or_slide") or "").strip(),
        }
        for item in figure_assets
        if str(item.get("asset_ref") or "").strip()
    ]

    return {
        "figure_assets": figure_assets,
        "entity_hubs": entity_hubs,
        "candidate_relations": candidate_relations,
        "figure_entity_index": {
            "by_figure": by_figure,
            "by_entity": figure_by_entity,
        },
        "figure_section_index": {
            "by_slug": {book_slug: figure_section_entries},
            "by_figure": {
                str(item.get("asset_name") or "").strip(): item
                for item in figure_section_entries
                if str(item.get("asset_name") or "").strip()
            },
        },
        "section_by_entity": section_by_entity,
        "chat_navigation_aliases": {book_slug: alias_items[:12]},
    }


def _figure_sections(payload: dict[str, Any]) -> list[dict[str, Any]]:
    sections = _sections(payload)
    figure_sections = [
        section
        for section in sections
        if _is_figure_section(section)
    ]
    return figure_sections


def _is_figure_section(section: dict[str, Any]) -> bool:
    block_kinds = [str(item).strip().lower() for item in (section.get("block_kinds") or []) if str(item).strip()]
    if "figure" in block_kinds:
        return True
    heading = str(section.get("heading") or "").strip()
    if not any(hint in heading for hint in _FIGURE_HEADING_HINTS):
        return False
    return _has_relation_like_body(str(section.get("text") or ""))


def _resolved_figure_assets(*, payload: dict[str, Any], asset_slug: str) -> list[dict[str, Any]]:
    explicit_assets = [
        dict(item)
        for item in (payload.get("figure_assets") or [])
        if isinstance(item, dict)
    ]
    if explicit_assets:
        return explicit_assets
    figure_assets: list[dict[str, Any]] = []
    for section in _figure_sections(payload):
        section_key = str(section.get("section_key") or section.get("anchor") or section.get("ordinal") or "").strip()
        if not section_key:
            continue
        heading = str(section.get("heading") or section_key).strip() or section_key
        anchor = str(section.get("anchor") or "").strip()
        asset_name = _slugify(anchor or heading or section_key) or f"figure-{len(figure_assets) + 1}"
        figure_assets.append(
            {
                "asset_ref": f"{asset_slug}::{asset_name}",
                "asset_name": asset_name,
                "caption": heading,
                "alt": heading,
                "viewer_path": str(section.get("viewer_path") or "").strip(),
                "section_hint": " > ".join(str(item).strip() for item in (section.get("section_path") or []) if str(item).strip()) or heading,
                "source_page_or_slide": heading,
                "source_section_key": section_key,
                "source_anchor": anchor,
                "source_url": str(section.get("source_url") or "").strip(),
            }
        )
    return figure_assets


def _figure_groups(text: str) -> list[list[str]]:
    groups: list[list[str]] = []
    for paragraph in re.split(r"\n\s*\n", str(text or "").strip()):
        normalized = paragraph.strip()
        if not normalized or normalized.startswith("[TABLE") or _DATE_ONLY_RE.fullmatch(normalized):
            continue
        parts = _DIAGRAM_ENTITY_SPLIT_RE.split(normalized) if "|" in normalized else normalized.splitlines()
        cleaned: list[str] = []
        for part in parts:
            value = " ".join(str(part or "").split()).strip()
            if not value or _DOC_CODE_RE.fullmatch(value) or _DATE_ONLY_RE.fullmatch(value):
                continue
            if cleaned and cleaned[-1] == value:
                continue
            cleaned.append(value)
        if cleaned:
            groups.append(cleaned)
    return groups


def _has_relation_like_body(text: str) -> bool:
    groups = _figure_groups(text)
    if not groups:
        return False
    if len(groups) >= 2:
        return True
    return any(len(group) >= 2 for group in groups)


def _ensure_entity_hub(
    entity_hubs: dict[str, dict[str, Any]],
    *,
    label: str,
    book_slug: str,
    section: dict[str, Any],
    asset_ref: str,
) -> dict[str, Any]:
    title = " ".join(str(label or "").split()).strip()
    entity_slug = _slugify(title)
    if not entity_slug:
        entity_slug = f"{book_slug}-entity"
    existing = entity_hubs.get(entity_slug)
    section_ref = {
        "href": str(section.get("viewer_path") or "").strip(),
        "label": str(section.get("heading") or "").strip() or title,
        "summary": str(section.get("heading") or "").strip() or title,
    }
    if existing is None:
        existing = {
            "entity_slug": entity_slug,
            "title": title,
            "entity_type": _entity_type(title),
            "aliases": [title],
            "overview": [f"`{title}` 는 `{book_slug}` 문서의 도식형 섹션에서 추출된 semantic entity 다."],
            "books": [book_slug],
            "sections": [section_ref],
            "figure_refs": [asset_ref] if asset_ref else [],
        }
        entity_hubs[entity_slug] = existing
        return existing
    aliases = [str(item).strip() for item in (existing.get("aliases") or []) if str(item).strip()]
    if title not in aliases:
        aliases.append(title)
    existing["aliases"] = aliases
    books = [str(item).strip() for item in (existing.get("books") or []) if str(item).strip()]
    if book_slug not in books:
        books.append(book_slug)
    existing["books"] = books
    sections = [dict(item) for item in (existing.get("sections") or []) if isinstance(item, dict)]
    if section_ref not in sections:
        sections.append(section_ref)
    existing["sections"] = sections
    figure_refs = [str(item).strip() for item in (existing.get("figure_refs") or []) if str(item).strip()]
    if asset_ref and asset_ref not in figure_refs:
        figure_refs.append(asset_ref)
    existing["figure_refs"] = figure_refs
    return existing


def _entity_type(label: str) -> str:
    lowered = str(label or "").strip().lower()
    if any(token in lowered for token in _ROLE_HINTS):
        return "role"
    if any(token in lowered for token in _SYSTEM_HINTS):
        return "system"
    if any(token in lowered for token in _ACTION_HINTS):
        return "action"
    if any(token in lowered for token in _PHASE_HINTS):
        return "phase"
    return "entity"


def _relation_type(source_label: str, target_label: str) -> str:
    combined = f"{source_label} {target_label}".lower()
    if "승인" in combined or "gate" in combined or "mr" in combined:
        return "gate"
    if any(token in combined for token in ("push", "pull", "sync", "webhook")):
        return "flow"
    if any(token in combined for token in ("환경", "개발", "검증", "운영", "테스트", "배포")):
        return "phase_sequence"
    return "sequence"


def _relation_slug(
    *,
    book_slug: str,
    section_key: str,
    source_slug: str,
    target_slug: str,
    ordinal: int,
) -> str:
    return "--".join(
        part
        for part in (
            _slugify(book_slug),
            _slugify(section_key),
            _slugify(source_slug),
            "to",
            _slugify(target_slug),
            str(ordinal),
        )
        if part
    )


def _slugify(value: str) -> str:
    normalized = _ENTITY_SLUG_RE.sub("-", str(value or "").strip().lower())
    return re.sub(r"-{2,}", "-", normalized).strip("-")


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
