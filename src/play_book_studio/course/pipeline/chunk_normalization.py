from __future__ import annotations

import re
from typing import Any

from .common import normalize_text


TECH_TERMS = [
    "OpenShift Container Platform",
    "OpenShift Data Foundation",
    "RedHat Service Mesh",
    "Tekton Pipelines",
    "IngressController",
    "Service Mesh",
    "ODF Storage",
    "Envoy Proxy",
    "Prometheus",
    "Monitoring",
    "Grafana",
    "Logging",
    "ArgoCD",
    "GitOps",
    "Jenkins",
    "GitLab",
    "Oracle",
    "Vertica",
    "HAProxy",
    "Istio",
    "Redis",
    "Quay",
    "Loki",
    "ETCD",
    "HPA",
    "PVC",
    "NFS",
    "CDC",
]

NETWORK_ZONE_TERMS = [
    "Service Network",
    "Storage Network",
    "Mgmt Network",
    "Data Base",
    "Database",
    "외부 Solution",
    "내부망",
    "DMZ",
    "외부",
    "내부",
    "DB",
]


def _ordered_unique(values: list[str]) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = normalize_text(str(value or ""))
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        rows.append(text)
        seen.add(key)
    return rows


def _list_value(value: Any) -> list[str]:
    if isinstance(value, bool):
        return []
    if isinstance(value, list):
        return [normalize_text(str(item or "")) for item in value if normalize_text(str(item or ""))]
    text = normalize_text(str(value or ""))
    return [text] if text else []


def _contains_term(blob: str, term: str) -> bool:
    if not term:
        return False
    if re.search(r"[A-Za-z]", term):
        pattern = rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])"
        return bool(re.search(pattern, blob, flags=re.IGNORECASE))
    return term in blob


def _extract_terms(blob: str, terms: list[str]) -> list[str]:
    return _ordered_unique([term for term in terms if _contains_term(blob, term)])


def _first_sentence(text: str, *, max_length: int = 420) -> str:
    normalized = normalize_text(text)
    if not normalized:
        return ""
    split = re.split(r"(?<=[.!?。])\s+|\n+", normalized, maxsplit=1)[0]
    if len(split) > max_length:
        return f"{split[:max_length].rstrip()}..."
    return split


def _slide_ref_map(chunk: dict[str, Any]) -> dict[int, dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = {}
    slide_refs = chunk.get("slide_refs") if isinstance(chunk.get("slide_refs"), list) else []
    for slide_ref in slide_refs:
        if not isinstance(slide_ref, dict):
            continue
        slide_no = int(slide_ref.get("slide_no") or 0)
        if slide_no:
            rows[slide_no] = slide_ref
    return rows


def _single_slide_ref(chunk: dict[str, Any]) -> dict[str, Any] | None:
    slide_refs = chunk.get("slide_refs") if isinstance(chunk.get("slide_refs"), list) else []
    usable = [item for item in slide_refs if isinstance(item, dict) and int(item.get("slide_no") or 0)]
    return usable[0] if len(usable) == 1 else None


def _zone_index(chunk: dict[str, Any]) -> dict[int, dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = {}
    zones = chunk.get("semantic_zones") if isinstance(chunk.get("semantic_zones"), list) else []
    for zone in zones:
        if not isinstance(zone, dict):
            continue
        source_shape_ids = zone.get("source_shape_ids")
        if isinstance(source_shape_ids, list):
            for shape_id in source_shape_ids:
                try:
                    rows[int(shape_id)] = zone
                except (TypeError, ValueError):
                    continue
        else:
            try:
                shape_id = int(zone.get("shape_index") or 0)
            except (TypeError, ValueError):
                shape_id = 0
            if shape_id:
                rows[shape_id] = zone
    return rows


def _attachment_text(attachment: dict[str, Any]) -> str:
    return "\n".join(
        part
        for part in [
            str(attachment.get("caption_text") or ""),
            str(attachment.get("visual_summary") or ""),
            str(attachment.get("ocr_text") or ""),
        ]
        if part
    )


def _chunk_text_blob(chunk: dict[str, Any]) -> str:
    attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
    attachment_text = "\n".join(_attachment_text(item) for item in attachments if isinstance(item, dict))
    facets = chunk.get("facets") if isinstance(chunk.get("facets"), dict) else {}
    facet_text: list[str] = []
    for value in facets.values():
        facet_text.extend(_list_value(value))
    return "\n".join(
        part
        for part in [
            str(chunk.get("title") or ""),
            str(chunk.get("native_id") or ""),
            str(chunk.get("body_md") or ""),
            str(chunk.get("visual_text") or ""),
            attachment_text,
            "\n".join(facet_text),
        ]
        if part
    )


def _normalize_role(*, chunk: dict[str, Any], attachment: dict[str, Any], zone: dict[str, Any] | None, role_counts: dict[str, int]) -> str:
    raw_role = normalize_text(str(attachment.get("role") or ""))
    zone_role = normalize_text(str((zone or {}).get("role") or ""))
    zone_type = normalize_text(str((zone or {}).get("zone_type") or ""))
    if zone_role == "title":
        return "title"
    if zone_role == "label":
        return "design_id" if str(chunk.get("stage_id") or "") == "architecture" else "label"
    if raw_role == "diagram" or zone_type == "image":
        role_counts["diagram"] = role_counts.get("diagram", 0) + 1
        if str(chunk.get("stage_id") or "") == "architecture" and role_counts["diagram"] == 1:
            return "main_diagram"
        if str(chunk.get("stage_id") or "") == "architecture":
            return "sub_diagram"
        return raw_role or "diagram"
    return raw_role or zone_role or str(attachment.get("kind") or attachment.get("type") or "slide_image")


def _asset_id(chunk_id: str, attachment: dict[str, Any], index: int) -> str:
    existing = normalize_text(str(attachment.get("asset_id") or ""))
    if existing:
        return existing
    slide_no = int(attachment.get("slide_no") or attachment.get("_slide_no") or 0)
    attachment_id = normalize_text(str(attachment.get("attachment_id") or ""))
    shape_index = int(attachment.get("shape_index") or 0)
    if slide_no and attachment_id:
        return f"{chunk_id}::slide:{slide_no:03d}::{attachment_id}"
    if slide_no and shape_index:
        return f"{chunk_id}::slide:{slide_no:03d}::shape:{shape_index:03d}"
    return f"{chunk_id}::asset:{index:02d}"


def _normalize_attachments(chunk: dict[str, Any], notes: list[str]) -> list[dict[str, Any]]:
    chunk_id = str(chunk.get("chunk_id") or "chunk")
    attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
    slide_refs_by_no = _slide_ref_map(chunk)
    single_ref = _single_slide_ref(chunk)
    zones_by_shape = _zone_index(chunk)
    role_counts: dict[str, int] = {}
    rows: list[dict[str, Any]] = []

    for index, attachment in enumerate(attachments, start=1):
        if not isinstance(attachment, dict):
            continue
        normalized = dict(attachment)
        slide_no = int(normalized.get("slide_no") or normalized.get("_slide_no") or 0)
        shape_index = int(normalized.get("shape_index") or 0)
        zone = zones_by_shape.get(shape_index) if shape_index else None
        zone_id = normalize_text(str(normalized.get("zone_id") or (zone or {}).get("zone_id") or ""))
        source_ref = slide_refs_by_no.get(slide_no) or single_ref
        source_pptx = normalize_text(str(normalized.get("source_pptx") or ""))
        if not source_pptx and isinstance(source_ref, dict):
            source_pptx = normalize_text(str(source_ref.get("pptx") or ""))
        if not source_pptx:
            source_pptx = normalize_text(str(chunk.get("source_pptx") or ""))
        if not slide_no and isinstance(source_ref, dict):
            slide_no = int(source_ref.get("slide_no") or 0)

        if not slide_no:
            notes.append("attachment_slide_ref_unresolved")
        if not zone_id:
            notes.append("asset_zone_link_missing")

        asset_id = _asset_id(chunk_id, {**normalized, "slide_no": slide_no}, index)
        normalized["asset_id"] = asset_id
        normalized["attachment_id"] = normalize_text(str(normalized.get("attachment_id") or asset_id))
        normalized["source_pptx"] = source_pptx
        normalized["slide_no"] = slide_no
        normalized["shape_index"] = shape_index
        normalized["zone_id"] = zone_id
        normalized["type"] = normalize_text(str(normalized.get("type") or normalized.get("kind") or "slide_image"))
        normalized["kind"] = normalize_text(str(normalized.get("kind") or normalized.get("type") or "slide_image"))
        normalized["role"] = _normalize_role(chunk=chunk, attachment=normalized, zone=zone, role_counts=role_counts)
        if zone and not normalized.get("bbox_norm"):
            normalized["bbox_norm"] = zone.get("bbox_norm") if isinstance(zone.get("bbox_norm"), list) else []
        rows.append(normalized)
    return rows


def _normalize_related_official_docs(chunk: dict[str, Any]) -> list[dict[str, Any]]:
    docs = chunk.get("related_official_docs") if isinstance(chunk.get("related_official_docs"), list) else []
    rows: list[dict[str, Any]] = []
    title = normalize_text(str(chunk.get("title") or ""))
    native_id = normalize_text(str(chunk.get("native_id") or ""))
    reason_seed = ", ".join(part for part in [native_id, title] if part)
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        item = dict(doc)
        if not normalize_text(str(item.get("match_reason") or "")):
            item["match_reason"] = f"score>=0.65; matched against course chunk identifiers and text: {reason_seed}"
        rows.append(item)
    return rows


def _normalize_facets(chunk: dict[str, Any], *, technologies: list[str], network_zones: list[str], has_ocr: bool, has_image: bool) -> dict[str, Any]:
    facets = dict(chunk.get("facets") if isinstance(chunk.get("facets"), dict) else {})
    stage_id = normalize_text(str(chunk.get("stage_id") or "unknown"))
    chunk_kind = normalize_text(str(chunk.get("chunk_kind") or "unknown"))
    source_kind = normalize_text(str(chunk.get("source_kind") or "project_artifact"))
    facets["stage_ids"] = _ordered_unique([*_list_value(facets.get("stage_ids")), stage_id])
    facets["chunk_kinds"] = _ordered_unique([*_list_value(facets.get("chunk_kinds")), chunk_kind])
    facets["source_types"] = _ordered_unique([*_list_value(facets.get("source_types")), source_kind])
    facets["technologies"] = _ordered_unique([*_list_value(facets.get("technologies")), *technologies])
    facets["network_zones"] = _ordered_unique([*_list_value(facets.get("network_zones")), *network_zones])
    facets["has_image"] = has_image
    facets["has_ocr"] = has_ocr
    return facets


def _build_search_text(chunk: dict[str, Any], *, technologies: list[str], network_zones: list[str]) -> str:
    title = normalize_text(str(chunk.get("title") or ""))
    native_id = normalize_text(str(chunk.get("native_id") or ""))
    stage_id = normalize_text(str(chunk.get("stage_id") or ""))
    chunk_kind = normalize_text(str(chunk.get("chunk_kind") or ""))
    body_summary = _first_sentence(str(chunk.get("body_md") or ""))
    structured = chunk.get("structured") if isinstance(chunk.get("structured"), dict) else {}
    components: list[str] = []
    for key in ("components", "component", "systems", "system", "service", "services"):
        components.extend(_list_value(structured.get(key)))
    parts = [
        normalize_text(f"{native_id} {title}.") if native_id or title else "",
        normalize_text(f"{stage_id} 단계의 {chunk_kind} 청크."),
        body_summary,
        f"주요 기술: {', '.join(technologies)}." if technologies else "",
        f"네트워크/영역: {', '.join(network_zones)}." if network_zones else "",
        f"주요 구성요소: {', '.join(_ordered_unique(components))}." if components else "",
    ]
    return "\n".join(part for part in parts if part).strip()


def _normalize_index_texts(chunk: dict[str, Any], *, search_text: str, technologies: list[str], network_zones: list[str]) -> dict[str, str]:
    attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
    visual_parts = _ordered_unique(
        [
            str(chunk.get("visual_text") or ""),
            *[
                str(attachment.get("visual_summary") or attachment.get("caption_text") or "")
                for attachment in attachments
                if isinstance(attachment, dict)
            ],
        ]
    )
    facets = chunk.get("facets") if isinstance(chunk.get("facets"), dict) else {}
    facet_terms: list[str] = []
    for value in facets.values():
        facet_terms.extend(_list_value(value))
    sparse_parts = [
        str(chunk.get("native_id") or ""),
        str(chunk.get("chunk_id") or ""),
        str(chunk.get("semantic_chunk_id") or ""),
        *technologies,
        *network_zones,
        *facet_terms,
    ]
    return {
        "dense_text": "\n".join(
            part
            for part in [
                search_text,
                _first_sentence(str(chunk.get("body_md") or ""), max_length=1000),
                "\n".join(visual_parts),
            ]
            if part
        ).strip(),
        "sparse_text": "\n".join(_ordered_unique(sparse_parts)).strip(),
        "title_text": normalize_text(str(chunk.get("title") or "")),
        "visual_text": "\n".join(visual_parts).strip(),
    }


def normalize_course_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
    chunk["canonical_model"] = str(chunk.get("canonical_model") or "course_chunk_v1")
    chunk["schema_version"] = str(chunk.get("schema_version") or "ppt_chunk_v1")
    chunk["source_kind"] = str(chunk.get("source_kind") or "project_artifact")
    notes = _ordered_unique(_list_value(chunk.get("review_notes")))

    chunk["image_attachments"] = _normalize_attachments(chunk, notes)
    blob = _chunk_text_blob(chunk)
    technologies = _extract_terms(blob, TECH_TERMS)
    network_zones = _extract_terms(blob, NETWORK_ZONE_TERMS)
    attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
    has_image = bool(attachments)
    has_ocr = any(isinstance(item, dict) and normalize_text(str(item.get("ocr_text") or "")) for item in attachments)
    chunk["facets"] = _normalize_facets(
        chunk,
        technologies=technologies,
        network_zones=network_zones,
        has_ocr=has_ocr,
        has_image=has_image,
    )
    search_text = _build_search_text(chunk, technologies=technologies, network_zones=network_zones)
    if not search_text:
        search_text = "\n".join(
            part
            for part in [
                normalize_text(str(chunk.get("title") or "")),
                normalize_text(str(chunk.get("native_id") or "")),
                _first_sentence(str(chunk.get("body_md") or "")),
            ]
            if part
        ).strip()
    chunk["search_text"] = search_text
    chunk["index_texts"] = _normalize_index_texts(
        chunk,
        search_text=search_text,
        technologies=technologies,
        network_zones=network_zones,
    )
    chunk["related_official_docs"] = _normalize_related_official_docs(chunk)

    provenance = chunk.get("provenance") if isinstance(chunk.get("provenance"), dict) else {}
    linked_asset_ids = [str(item.get("asset_id") or "") for item in attachments if isinstance(item, dict)]
    linked_zone_ids = [str(item.get("zone_id") or "") for item in attachments if isinstance(item, dict) and str(item.get("zone_id") or "").strip()]
    zone_roles = [
        str(zone.get("role") or "")
        for zone in (chunk.get("semantic_zones") if isinstance(chunk.get("semantic_zones"), list) else [])
        if isinstance(zone, dict) and str(zone.get("role") or "").strip()
    ]
    chunk["provenance"] = {
        **provenance,
        "linked_asset_ids": _ordered_unique(linked_asset_ids),
        "linked_zone_ids": _ordered_unique(linked_zone_ids),
        "semantic_zone_roles": _ordered_unique(zone_roles),
    }

    notes = _ordered_unique(notes)
    chunk["review_notes"] = notes
    if notes:
        chunk["review_status"] = "needs_review"
        try:
            current_score = float(chunk.get("quality_score") or 0.77)
        except (TypeError, ValueError):
            current_score = 0.77
        chunk["quality_score"] = round(min(current_score, max(0.35, 0.95 - (0.12 * len(notes)))), 2)
    else:
        chunk["review_status"] = str(chunk.get("review_status") or "approved")
        chunk["quality_score"] = float(chunk.get("quality_score") or 0.98)
    return chunk


def normalize_course_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [normalize_course_chunk(chunk) for chunk in chunks]


__all__ = ["normalize_course_chunk", "normalize_course_chunks"]
