from __future__ import annotations

# intake 품질 판정과 공통 service helper를 모아둔 모듈.

import math
import re
from typing import Any
from urllib.parse import urlparse

from play_book_studio.ingestion.topic_playbooks import (
    OPERATION_PLAYBOOK_SOURCE_TYPE,
    POLICY_OVERLAY_BOOK_SOURCE_TYPE,
    SYNTHESIZED_PLAYBOOK_SOURCE_TYPE,
    TOPIC_PLAYBOOK_SOURCE_TYPE,
    TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE,
)

CUSTOMER_PACK_DERIVED_FAMILIES: tuple[str, ...] = (
    TOPIC_PLAYBOOK_SOURCE_TYPE,
    OPERATION_PLAYBOOK_SOURCE_TYPE,
    TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE,
    POLICY_OVERLAY_BOOK_SOURCE_TYPE,
    SYNTHESIZED_PLAYBOOK_SOURCE_TYPE,
)

CUSTOMER_PACK_FAMILY_LABELS = {
    TOPIC_PLAYBOOK_SOURCE_TYPE: "Topic Playbook",
    OPERATION_PLAYBOOK_SOURCE_TYPE: "Operation Playbook",
    TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE: "Troubleshooting Playbook",
    POLICY_OVERLAY_BOOK_SOURCE_TYPE: "Policy Overlay Book",
    SYNTHESIZED_PLAYBOOK_SOURCE_TYPE: "Synthesized Playbook",
}

CUSTOMER_PACK_FAMILY_SUMMARIES = {
    TOPIC_PLAYBOOK_SOURCE_TYPE: "업로드 문서에서 핵심 토픽 절차와 개념만 추린 파생 플레이북입니다.",
    OPERATION_PLAYBOOK_SOURCE_TYPE: "업로드 문서에서 day-2 운영 절차와 검증 흐름만 다시 묶은 파생 플레이북입니다.",
    TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE: "업로드 문서에서 실패 징후와 복구 분기를 중심으로 다시 묶은 트러블슈팅 자산입니다.",
    POLICY_OVERLAY_BOOK_SOURCE_TYPE: "업로드 문서에서 요구 사항, 제한, 검증 조건을 다시 묶은 정책 오버레이 자산입니다.",
    SYNTHESIZED_PLAYBOOK_SOURCE_TYPE: "업로드 문서에서 설명, 절차, 검증을 한 권으로 압축한 합성 플레이북입니다.",
}

CUSTOMER_PACK_FAMILY_KEYWORDS = {
    TOPIC_PLAYBOOK_SOURCE_TYPE: ("절차", "워크플로", "구성", "설치", "백업", "복구", "운영", "확인"),
    OPERATION_PLAYBOOK_SOURCE_TYPE: ("운영", "점검", "실행", "검증", "명령", "절차", "runbook"),
    TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE: ("장애", "실패", "복구", "오류", "트러블슈팅", "debug", "fail", "error"),
    POLICY_OVERLAY_BOOK_SOURCE_TYPE: ("필수", "요구", "제한", "지원", "권장", "금지", "보안", "사전", "must", "should"),
    SYNTHESIZED_PLAYBOOK_SOURCE_TYPE: ("개요", "설명", "절차", "검증", "참조", "요약", "guide"),
}

CUSTOMER_PACK_FAMILY_MAX_SECTIONS = {
    TOPIC_PLAYBOOK_SOURCE_TYPE: 24,
    OPERATION_PLAYBOOK_SOURCE_TYPE: 24,
    TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE: 18,
    POLICY_OVERLAY_BOOK_SOURCE_TYPE: 18,
    SYNTHESIZED_PLAYBOOK_SOURCE_TYPE: 28,
}

CUSTOMER_PACK_FAMILY_BASELINE_SECTIONS = {
    TOPIC_PLAYBOOK_SOURCE_TYPE: 12,
    OPERATION_PLAYBOOK_SOURCE_TYPE: 12,
    TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE: 10,
    POLICY_OVERLAY_BOOK_SOURCE_TYPE: 10,
    SYNTHESIZED_PLAYBOOK_SOURCE_TYPE: 14,
}

CUSTOMER_PACK_FAMILY_SECTION_RATIOS = {
    TOPIC_PLAYBOOK_SOURCE_TYPE: 0.6,
    OPERATION_PLAYBOOK_SOURCE_TYPE: 0.6,
    TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE: 0.5,
    POLICY_OVERLAY_BOOK_SOURCE_TYPE: 0.5,
    SYNTHESIZED_PLAYBOOK_SOURCE_TYPE: 0.7,
}

_STRUCTURED_KEY_VALUE_RE = re.compile(r"^[A-Za-z0-9_.-]+:\s*\S")
_STRUCTURED_MANIFEST_KEY_RE = re.compile(
    r"^(?:apiVersion|kind|metadata|spec|data|stringData|targetRevision|server|path|namespace|image|tag):",
    re.IGNORECASE,
)
_STRUCTURED_COMMAND_RE = re.compile(r"^(?:oc|kubectl|helm|argocd|podman|docker)\s+\S", re.IGNORECASE)

GRADE_GATE_VERSION = "customer_pack_grade_gate_v1"


def _customer_pack_asset_slug(draft_id: str, family: str) -> str:
    return f"{draft_id}--{family}"


def _customer_pack_asset_viewer_path(*, draft_id: str, asset_slug: str = "") -> str:
    if asset_slug:
        return f"/playbooks/customer-packs/{draft_id}/assets/{asset_slug}/index.html"
    return f"/playbooks/customer-packs/{draft_id}/index.html"


def _customer_pack_evidence(payload: dict[str, object]) -> dict[str, Any]:
    evidence = payload.get("customer_pack_evidence")
    return dict(evidence) if isinstance(evidence, dict) else {}


def _payload_or_evidence_value(payload: dict[str, object], field_name: str) -> Any:
    value = payload.get(field_name)
    if value not in ("", None, [], {}):
        return value
    return _customer_pack_evidence(payload).get(field_name)


def _normalized_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "ready", "approved"}
    return bool(value)


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _viewer_path_has_exact_anchor(viewer_path: str, anchor: str) -> bool:
    normalized_viewer_path = str(viewer_path or "").strip()
    normalized_anchor = str(anchor or "").strip()
    if not normalized_viewer_path or not normalized_anchor or "#" not in normalized_viewer_path:
        return False
    parsed = urlparse(normalized_viewer_path)
    return parsed.fragment.strip() == normalized_anchor


def _canonical_sections(payload: dict[str, object]) -> list[dict[str, Any]]:
    return [
        dict(section)
        for section in (payload.get("sections") or [])
        if isinstance(section, dict)
    ]


def _section_blob(section: dict[str, Any]) -> str:
    values = [
        str(section.get("heading") or ""),
        str(section.get("text") or ""),
        *[str(item) for item in (section.get("section_path") or []) if str(item).strip()],
    ]
    return " ".join(value.strip().lower() for value in values if value and value.strip())


def _section_score(section: dict[str, Any], *, family: str, ordinal: int) -> int:
    heading = str(section.get("heading") or "").strip().lower()
    text = str(section.get("text") or "").strip().lower()
    blob = _section_blob(section)
    score = 0
    if heading == "page summary":
        score -= 6
    if "[code]" in text:
        score += 3
    if ordinal == 0 and family in {
        TOPIC_PLAYBOOK_SOURCE_TYPE,
        OPERATION_PLAYBOOK_SOURCE_TYPE,
        POLICY_OVERLAY_BOOK_SOURCE_TYPE,
        SYNTHESIZED_PLAYBOOK_SOURCE_TYPE,
    }:
        score += 2
    if family == TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE and "[code]" in text:
        score += 1
    if family == POLICY_OVERLAY_BOOK_SOURCE_TYPE and len(text) <= 80:
        score += 1
    for keyword in CUSTOMER_PACK_FAMILY_KEYWORDS[family]:
        if keyword.lower() in blob:
            score += 2
    if family == SYNTHESIZED_PLAYBOOK_SOURCE_TYPE and blob:
        score += 1
    return score


def _select_family_sections(
    sections: list[dict[str, Any]],
    *,
    family: str,
) -> list[dict[str, Any]]:
    if not sections:
        return []
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    for ordinal, section in enumerate(sections):
        ranked.append((_section_score(section, family=family, ordinal=ordinal), ordinal, section))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    chosen = [section for score, _, section in ranked if score > 0]
    if not chosen:
        chosen = [
            section
            for section in sections
            if str(section.get("heading") or "").strip().lower() != "page summary"
        ]
    limit = min(
        CUSTOMER_PACK_FAMILY_MAX_SECTIONS[family],
        max(
            CUSTOMER_PACK_FAMILY_BASELINE_SECTIONS[family],
            math.ceil(len(chosen) * CUSTOMER_PACK_FAMILY_SECTION_RATIOS[family]),
        ),
    )
    selected_keys: set[str] = set()
    selected: list[dict[str, Any]] = []
    for section in chosen:
        section_key = str(section.get("section_key") or section.get("anchor") or "")
        if section_key in selected_keys:
            continue
        selected_keys.add(section_key)
        selected.append(section)
        if len(selected) >= limit:
            break
    if not selected and sections:
        selected = [sections[0]]
    return sorted(
        selected,
        key=lambda item: int(item.get("ordinal") or 0),
    )


def _clone_sections_for_asset(
    sections: list[dict[str, Any]],
    *,
    draft_id: str,
    asset_slug: str,
) -> list[dict[str, Any]]:
    viewer_base = _customer_pack_asset_viewer_path(draft_id=draft_id, asset_slug=asset_slug)
    cloned: list[dict[str, Any]] = []
    for ordinal, section in enumerate(sections, start=1):
        payload = dict(section)
        anchor = str(payload.get("anchor") or "").strip()
        payload["ordinal"] = ordinal
        payload["viewer_path"] = f"{viewer_base}#{anchor}" if anchor else viewer_base
        cloned.append(payload)
    return cloned


def build_customer_pack_playable_books(
    payload: dict[str, object],
    *,
    draft_id: str,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    sections = _canonical_sections(payload)
    normalization_notes = [
        str(note).strip()
        for note in (
            payload.get("normalization_notes")
            or payload.get("notes")
            or []
        )
        if str(note).strip()
    ]
    base_viewer_path = _customer_pack_asset_viewer_path(draft_id=draft_id)
    base_title = str(payload.get("title") or draft_id).strip() or draft_id
    base_source_type = str(payload.get("source_type") or "").strip()
    base_asset = {
        "asset_slug": draft_id,
        "asset_kind": "customer_pack_manual_book",
        "playbook_family": "manual_book",
        "family_label": "Customer Manual Book",
        "title": base_title,
        "viewer_path": base_viewer_path,
        "section_count": len(sections),
        "source_type": base_source_type,
    }

    derived_payloads: list[dict[str, object]] = []
    derived_assets: list[dict[str, object]] = []
    for family in CUSTOMER_PACK_DERIVED_FAMILIES:
        asset_slug = _customer_pack_asset_slug(draft_id, family)
        selected_sections = _select_family_sections(sections, family=family)
        if not selected_sections:
            continue
        derived_sections = _clone_sections_for_asset(
            selected_sections,
            draft_id=draft_id,
            asset_slug=asset_slug,
        )
        derived_title = f"{base_title} {CUSTOMER_PACK_FAMILY_LABELS[family]}"
        derived_payload = dict(payload)
        derived_payload.update(
            {
                "book_slug": asset_slug,
                "title": derived_title,
                "asset_slug": asset_slug,
                "asset_kind": "derived_playbook_family",
                "playbook_family": family,
                "family_label": CUSTOMER_PACK_FAMILY_LABELS[family],
                "family_summary": CUSTOMER_PACK_FAMILY_SUMMARIES[family],
                "derived_from_draft_id": draft_id,
                "derived_from_book_slug": str(payload.get("book_slug") or "").strip(),
                "target_viewer_path": _customer_pack_asset_viewer_path(
                    draft_id=draft_id,
                    asset_slug=asset_slug,
                ),
                "sections": derived_sections,
                "normalized_section_count": len(derived_sections),
            }
        )
        if normalization_notes:
            derived_payload["normalization_notes"] = normalization_notes
        derived_payloads.append(derived_payload)
        derived_assets.append(
            {
                "asset_slug": asset_slug,
                "asset_kind": "derived_playbook_family",
                "playbook_family": family,
                "family_label": CUSTOMER_PACK_FAMILY_LABELS[family],
                "title": derived_title,
                "viewer_path": derived_payload["target_viewer_path"],
                "section_count": len(derived_sections),
                "source_type": base_source_type,
                "family_summary": CUSTOMER_PACK_FAMILY_SUMMARIES[family],
            }
        )

    enriched_payload = dict(payload)
    enriched_payload.update(
        {
            "asset_slug": draft_id,
            "asset_kind": "customer_pack_manual_book",
            "target_viewer_path": base_viewer_path,
            "playable_asset_count": 1 + len(derived_assets),
            "derived_asset_count": len(derived_assets),
            "playable_assets": [base_asset, *derived_assets],
            "derived_assets": derived_assets,
        }
    )
    if normalization_notes:
        enriched_payload["normalization_notes"] = normalization_notes
    for derived_payload in derived_payloads:
        derived_payload["playable_asset_count"] = enriched_payload["playable_asset_count"]
        derived_payload["derived_asset_count"] = enriched_payload["derived_asset_count"]
        derived_payload["playable_assets"] = enriched_payload["playable_assets"]
        derived_payload["derived_assets"] = derived_assets
    return enriched_payload, derived_payloads


def _build_grade_gate(
    payload: dict[str, object],
    *,
    sections: list[dict[str, Any]],
    quality_score: int,
    quality_flags: list[str],
    corpus_manifest: dict[str, Any] | None = None,
) -> dict[str, object]:
    approval_state = str(_payload_or_evidence_value(payload, "approval_state") or "unreviewed").strip() or "unreviewed"
    publication_state = str(_payload_or_evidence_value(payload, "publication_state") or "draft").strip() or "draft"
    degraded_pdf = _normalized_bool(_payload_or_evidence_value(payload, "degraded_pdf"))
    fallback_used = _normalized_bool(_payload_or_evidence_value(payload, "fallback_used"))
    total_sections = len(sections)
    semantic_ready_count = sum(
        1
        for section in sections
        if str(section.get("semantic_role") or "").strip() not in {"", "unknown"}
    )
    anchored_section_count = sum(1 for section in sections if str(section.get("anchor") or "").strip())
    exact_landing_count = sum(
        1
        for section in sections
        if _viewer_path_has_exact_anchor(
            str(section.get("viewer_path") or "").strip(),
            str(section.get("anchor") or "").strip(),
        )
    )
    parse_ready = quality_score >= 70 and not quality_flags
    if total_sections <= 0:
        citation_status = "missing"
    elif exact_landing_count == total_sections:
        citation_status = "exact"
    elif exact_landing_count > 0 or anchored_section_count > 0:
        citation_status = "partial"
    else:
        citation_status = "missing"
    citation_ready = citation_status == "exact"

    manifest = dict(corpus_manifest or {})
    chunk_count = int(manifest.get("chunk_count") or 0)
    bm25_ready = bool(manifest.get("bm25_ready"))
    vector_status = str(manifest.get("vector_status") or "").strip()
    anchor_lineage_count = int(manifest.get("anchor_lineage_count") or 0)
    if chunk_count > 0 and bm25_ready and anchor_lineage_count >= max(exact_landing_count, 1):
        retrieval_status = "ready"
    elif chunk_count > 0 and (bm25_ready or vector_status == "ready"):
        retrieval_status = "partial"
    else:
        retrieval_status = "missing"
    retrieval_ready = retrieval_status == "ready"

    if not parse_ready:
        shared_grade = "blocked"
    elif citation_ready and retrieval_ready and quality_score >= 85 and not degraded_pdf and not fallback_used:
        shared_grade = "gold"
    elif citation_ready and retrieval_ready:
        shared_grade = "silver"
    elif citation_status in {"exact", "partial"} and retrieval_status in {"ready", "partial"}:
        shared_grade = "bronze"
    else:
        shared_grade = "blocked"

    llmwiki_ready = shared_grade in {"gold", "silver"} and retrieval_ready
    wikibook_ready = shared_grade in {"gold", "silver"} and citation_ready
    read_ready = llmwiki_ready and wikibook_ready and approval_state == "approved"
    publish_ready = read_ready and publication_state in {"active", "published"}
    promotion_reasons: list[str] = []
    if not parse_ready:
        promotion_reasons.append("parse_gate_not_ready")
    if not citation_ready:
        promotion_reasons.append(f"citation_landing_{citation_status}")
    if not retrieval_ready:
        promotion_reasons.append(f"retrieval_gate_{retrieval_status}")
    if approval_state != "approved":
        promotion_reasons.append(f"approval_not_ready:{approval_state}")
    if publication_state not in {"active", "published"}:
        promotion_reasons.append(f"publication_not_publish_ready:{publication_state}")

    if publish_ready:
        promotion_status = "promoted"
    elif llmwiki_ready and wikibook_ready and approval_state == "approved":
        promotion_status = "candidate"
    else:
        promotion_status = "blocked"

    return {
        "gate_version": GRADE_GATE_VERSION,
        "shared_grade": shared_grade,
        "parse_gate": {
            "status": "ready" if parse_ready else "review",
            "ready": parse_ready,
            "quality_score": int(quality_score),
            "quality_flags": list(quality_flags),
            "section_count": int(total_sections),
            "semantic_ready_count": int(semantic_ready_count),
            "semantic_ready_ratio": _safe_ratio(semantic_ready_count, total_sections),
            "degraded_pdf": degraded_pdf,
            "fallback_used": fallback_used,
        },
        "citation_gate": {
            "status": citation_status,
            "ready": citation_ready,
            "section_count": int(total_sections),
            "anchored_section_count": int(anchored_section_count),
            "exact_landing_count": int(exact_landing_count),
            "anchor_presence_ratio": _safe_ratio(anchored_section_count, total_sections),
            "exact_landing_ratio": _safe_ratio(exact_landing_count, total_sections),
        },
        "retrieval_gate": {
            "status": retrieval_status,
            "ready": retrieval_ready,
            "chunk_count": int(chunk_count),
            "bm25_ready": bm25_ready,
            "vector_status": vector_status or "missing",
            "anchor_lineage_count": int(anchor_lineage_count),
        },
        "surface_gates": {
            "llmwiki_ready": llmwiki_ready,
            "wikibook_ready": wikibook_ready,
            "llmwiki_status": "ready" if llmwiki_ready else ("review" if parse_ready else "blocked"),
            "wikibook_status": "ready" if wikibook_ready else ("review" if parse_ready else "blocked"),
        },
        "promotion_gate": {
            "status": promotion_status,
            "read_ready": read_ready,
            "publish_ready": publish_ready,
            "approval_state": approval_state,
            "publication_state": publication_state,
            "blocked_reasons": promotion_reasons,
        },
    }


def evaluate_canonical_book_quality(
    payload: dict[str, object],
    *,
    corpus_manifest: dict[str, Any] | None = None,
) -> dict[str, object]:
    sections = [dict(section) for section in (payload.get("sections") or []) if isinstance(section, dict)]
    if not sections:
        grade_gate = _build_grade_gate(
            payload,
            sections=[],
            quality_score=0,
            quality_flags=["no_sections"],
            corpus_manifest=corpus_manifest,
        )
        return {
            "quality_status": "review",
            "quality_score": 0,
            "quality_flags": ["no_sections"],
            "quality_summary": "섹션이 없어 study asset으로 사용할 수 없습니다.",
            "shared_grade": str(grade_gate["shared_grade"]),
            "grade_gate": grade_gate,
        }

    headings = [str(section.get("heading") or "").strip() for section in sections]
    texts = [str(section.get("text") or "").strip() for section in sections]
    page_summary_count = sum(heading == "Page Summary" for heading in headings)
    same_text_count = sum(
        1
        for heading, text in zip(headings, texts)
        if heading and text and text == heading
    )
    short_text_count = sum(1 for text in texts if 0 < len(text) <= 30)
    chapter_footer_count = sum(
        1
        for text in texts
        if re.search(r"(?:^|\n)\s*\d+\s*장\s*\.\s*[^\n]{4,}(?:\n|$)", text)
    )
    toc_artifact_count = sum(
        1
        for text in texts
        if re.search(r"(?:\.\s*){8,}", text) or "table of contents" in text.lower()
    )
    flattened_structured_count = sum(
        1
        for section in sections
        if _looks_like_flattened_structured_section(section)
    )

    total = max(len(sections), 1)
    page_summary_ratio = page_summary_count / total
    same_text_ratio = same_text_count / total
    short_text_ratio = short_text_count / total
    chapter_footer_ratio = chapter_footer_count / total
    toc_artifact_ratio = toc_artifact_count / total
    flattened_structured_ratio = flattened_structured_count / total

    flags: list[str] = []
    score = 100
    if page_summary_ratio >= 0.25:
        flags.append("too_many_page_summary_sections")
        score -= 35
    if same_text_ratio >= 0.25:
        flags.append("too_many_heading_only_sections")
        score -= 30
    if len(sections) >= 8 and short_text_ratio >= 0.35:
        flags.append("too_many_short_sections")
        score -= 20
    if len(sections) >= 500:
        flags.append("section_count_too_high")
        score -= 15
    if len(sections) >= 8 and chapter_footer_ratio >= 0.12:
        flags.append("chapter_footer_contamination")
        score -= 20
    if toc_artifact_ratio >= 0.08:
        flags.append("toc_artifacts_remaining")
        score -= 15
    if len(sections) >= 4 and flattened_structured_ratio >= 0.2:
        flags.append("structured_blocks_flattened")
        score -= 25

    clamped_score = max(score, 0)
    grade_gate = _build_grade_gate(
        payload,
        sections=sections,
        quality_score=clamped_score,
        quality_flags=flags,
        corpus_manifest=corpus_manifest,
    )
    shared_grade = str(grade_gate["shared_grade"])
    status = "ready" if shared_grade in {"gold", "silver"} else "review"
    if shared_grade == "gold":
        summary = "정규화 품질이 gold입니다. exact citation landing과 retrieval gate가 함께 준비되었습니다."
    elif shared_grade == "silver":
        summary = "정규화 품질이 silver입니다. LLM Wiki와 Wiki Book 승급선에 도달했습니다."
    elif shared_grade == "bronze":
        summary = "파싱은 성공했지만 citation 또는 retrieval gate가 아직 완전하지 않아 bronze 상태입니다."
    else:
        summary = "정규화 품질 검토가 필요합니다. section 구조 또는 승급 gate가 아직 불안정합니다."
    return {
        "quality_status": status,
        "quality_score": clamped_score,
        "quality_flags": flags,
        "quality_summary": summary,
        "shared_grade": shared_grade,
        "grade_gate": grade_gate,
    }


def _looks_like_flattened_structured_section(section: dict[str, Any]) -> bool:
    block_kinds = [
        str(item).strip().lower()
        for item in (section.get("block_kinds") or [])
        if str(item).strip()
    ]
    if "code" in block_kinds or "table" in block_kinds:
        return False

    text = str(section.get("text") or "").strip()
    if not text:
        return False
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if len(lines) < 3:
        return False

    score = 0
    for raw_line in lines[:12]:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("|") and line.count("|") >= 2:
            score += 3
        if _STRUCTURED_MANIFEST_KEY_RE.match(line):
            score += 3
        elif _STRUCTURED_KEY_VALUE_RE.match(line):
            score += 1
        if _STRUCTURED_COMMAND_RE.match(line):
            score += 2
        if raw_line[:1].isspace():
            score += 1
        if "://" in line:
            score += 1
        if any(token in line for token in ("{", "}", "[", "]")):
            score += 1
    return score >= 4


__all__ = [
    "build_customer_pack_playable_books",
    "evaluate_canonical_book_quality",
]
