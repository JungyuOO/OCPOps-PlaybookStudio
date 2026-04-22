from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from play_book_studio.config.settings import Settings
from play_book_studio.ingestion.graph_sidecar import (
    graph_sidecar_compact_artifact_status,
    refresh_active_runtime_graph_artifacts,
)


TOPIC_PLAYBOOK_SOURCE_TYPE = "topic_playbook"
OPERATION_PLAYBOOK_SOURCE_TYPE = "operation_playbook"
TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE = "troubleshooting_playbook"
POLICY_OVERLAY_BOOK_SOURCE_TYPE = "policy_overlay_book"
SYNTHESIZED_PLAYBOOK_SOURCE_TYPE = "synthesized_playbook"
DERIVED_PLAYBOOK_SOURCE_TYPES = frozenset(
    {
        TOPIC_PLAYBOOK_SOURCE_TYPE,
        OPERATION_PLAYBOOK_SOURCE_TYPE,
        TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE,
        POLICY_OVERLAY_BOOK_SOURCE_TYPE,
        SYNTHESIZED_PLAYBOOK_SOURCE_TYPE,
    }
)


@dataclass(frozen=True)
class DerivedPlaybookSpec:
    source_slug: str
    derived_slug: str
    family: str
    title: str
    summary: str
    keywords: tuple[str, ...]
    preferred_roles: tuple[str, ...] = ("procedure",)
    include_overview: bool = True
    max_sections: int = 14


CURATED_DERIVED_PLAYBOOK_SPECS: tuple[DerivedPlaybookSpec, ...] = (
    DerivedPlaybookSpec(
        source_slug="backup_and_restore",
        derived_slug="backup_restore_control_plane",
        family=TOPIC_PLAYBOOK_SOURCE_TYPE,
        title="컨트롤 플레인 백업/복구 플레이북",
        summary="백업, 스냅샷, quorum 복원처럼 실제 운영자가 바로 실행하는 컨트롤 플레인 복구 절차만 추렸습니다.",
        keywords=("backup", "restore", "snapshot", "quorum", "etcd", "백업", "복구", "재해"),
        preferred_roles=("procedure", "concept"),
    ),
    DerivedPlaybookSpec(
        source_slug="etcd",
        derived_slug="etcd_backup_restore",
        family=TOPIC_PLAYBOOK_SOURCE_TYPE,
        title="etcd 백업/복구 플레이북",
        summary="etcd 백업, 검증, 복원, quorum 손실 대응 절차만 추린 집중 실행본입니다.",
        keywords=("etcd", "backup", "restore", "snapshot", "quorum", "백업", "복구"),
        preferred_roles=("procedure", "concept"),
    ),
    DerivedPlaybookSpec(
        source_slug="machine_configuration",
        derived_slug="machine_config_operations",
        family=TOPIC_PLAYBOOK_SOURCE_TYPE,
        title="MachineConfig 운영 플레이북",
        summary="MachineConfig 적용, 노드 재시작, 드레이닝과 검증 절차를 중심으로 재구성한 운영본입니다.",
        keywords=("machineconfig", "machine config", "node", "drain", "pool", "구성", "노드", "드레인"),
        preferred_roles=("procedure", "concept"),
    ),
    DerivedPlaybookSpec(
        source_slug="monitoring",
        derived_slug="monitoring_alert_operations",
        family=TOPIC_PLAYBOOK_SOURCE_TYPE,
        title="모니터링/알림 운영 플레이북",
        summary="Prometheus, Alertmanager, 텔레메트리와 경보 대응에 필요한 절차만 모았습니다.",
        keywords=("monitor", "alert", "prometheus", "alertmanager", "telemetry", "모니터", "알림", "경보"),
        preferred_roles=("procedure", "concept"),
    ),
    DerivedPlaybookSpec(
        source_slug="operators",
        derived_slug="operator_lifecycle_management",
        family=TOPIC_PLAYBOOK_SOURCE_TYPE,
        title="오퍼레이터 수명주기 플레이북",
        summary="Operator 설치, Subscription, InstallPlan, 업그레이드와 검증 절차를 중심으로 정리했습니다.",
        keywords=("operator", "olm", "subscription", "installplan", "catalog", "오퍼레이터"),
        preferred_roles=("procedure", "concept"),
    ),
    DerivedPlaybookSpec(
        source_slug="installing_on_any_platform",
        derived_slug="install_any_platform_flow",
        family=TOPIC_PLAYBOOK_SOURCE_TYPE,
        title="Any Platform 설치 흐름 플레이북",
        summary="설치 준비, bootstrap, 자격 증명, 설치 검증처럼 핵심 설치 플로우만 재구성했습니다.",
        keywords=("install", "bootstrap", "credential", "upi", "ipi", "설치", "부트스트랩", "검증"),
        preferred_roles=("procedure", "concept"),
    ),
    DerivedPlaybookSpec(
        source_slug="backup_and_restore",
        derived_slug="backup_restore_operations",
        family=OPERATION_PLAYBOOK_SOURCE_TYPE,
        title="컨트롤 플레인 백업 운영 플레이북",
        summary="백업 실행, 결과 검증, 보관 원칙만 추린 운영 절차본입니다.",
        keywords=("backup", "snapshot", "verify", "cluster-backup", "백업", "검증", "보관"),
        preferred_roles=("procedure", "reference"),
    ),
    DerivedPlaybookSpec(
        source_slug="machine_configuration",
        derived_slug="machine_config_rollout_operations",
        family=OPERATION_PLAYBOOK_SOURCE_TYPE,
        title="MachineConfig 롤아웃 운영 플레이북",
        summary="드레이닝, 재시작, 롤아웃 검증처럼 day-2 운영 절차만 다시 묶었습니다.",
        keywords=("machineconfig", "drain", "reboot", "rollout", "pool", "노드", "검증"),
        preferred_roles=("procedure", "reference"),
    ),
    DerivedPlaybookSpec(
        source_slug="monitoring",
        derived_slug="monitoring_stack_operations",
        family=OPERATION_PLAYBOOK_SOURCE_TYPE,
        title="모니터링 스택 운영 플레이북",
        summary="Prometheus, Alertmanager, 텔레메트리 운영과 점검 절차만 추렸습니다.",
        keywords=("monitor", "alert", "prometheus", "alertmanager", "telemetry", "운영", "점검", "경보"),
        preferred_roles=("procedure", "reference"),
    ),
    DerivedPlaybookSpec(
        source_slug="operators",
        derived_slug="operator_upgrade_operations",
        family=OPERATION_PLAYBOOK_SOURCE_TYPE,
        title="오퍼레이터 업그레이드 운영 플레이북",
        summary="Subscription, InstallPlan, 업그레이드 검증 같은 운영 절차만 모았습니다.",
        keywords=("operator", "subscription", "installplan", "upgrade", "catalog", "오퍼레이터", "업그레이드"),
        preferred_roles=("procedure", "reference"),
    ),
    DerivedPlaybookSpec(
        source_slug="backup_and_restore",
        derived_slug="backup_restore_recovery_troubleshooting",
        family=TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE,
        title="컨트롤 플레인 복구 트러블슈팅 플레이북",
        summary="복구 실패, quorum 손실, 백업 검증 오류처럼 장애 대응 분기만 추렸습니다.",
        keywords=("restore", "recovery", "quorum", "failure", "fail", "recover", "복구", "장애", "실패", "쿼럼"),
        preferred_roles=("procedure", "reference"),
        include_overview=False,
    ),
    DerivedPlaybookSpec(
        source_slug="etcd",
        derived_slug="etcd_quorum_troubleshooting",
        family=TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE,
        title="etcd 쿼럼 복구 트러블슈팅 플레이북",
        summary="quorum 손실, restore 판단, 안정화 검증 같은 장애 대응 절차만 추렸습니다.",
        keywords=("quorum", "restore", "failure", "recover", "복구", "장애", "실패", "쿼럼"),
        preferred_roles=("procedure", "reference"),
        include_overview=False,
    ),
    DerivedPlaybookSpec(
        source_slug="installing_on_any_platform",
        derived_slug="install_any_platform_troubleshooting",
        family=TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE,
        title="Any Platform 설치 트러블슈팅 플레이북",
        summary="bootstrap 지연, 설치 실패, gather/debug 분기만 모은 장애 대응본입니다.",
        keywords=("bootstrap", "failure", "timeout", "gather", "debug", "실패", "장애", "타임아웃", "복구"),
        preferred_roles=("procedure", "reference"),
        include_overview=False,
    ),
)

TOPIC_PLAYBOOK_SPECS = tuple(
    spec for spec in CURATED_DERIVED_PLAYBOOK_SPECS if spec.family == TOPIC_PLAYBOOK_SOURCE_TYPE
)
OPERATION_PLAYBOOK_SPECS = tuple(
    spec for spec in CURATED_DERIVED_PLAYBOOK_SPECS if spec.family == OPERATION_PLAYBOOK_SOURCE_TYPE
)
TROUBLESHOOTING_PLAYBOOK_SPECS = tuple(
    spec
    for spec in CURATED_DERIVED_PLAYBOOK_SPECS
    if spec.family == TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE
)
POLICY_OVERLAY_BOOK_SPECS = tuple(
    spec
    for spec in CURATED_DERIVED_PLAYBOOK_SPECS
    if spec.family == POLICY_OVERLAY_BOOK_SOURCE_TYPE
)
SYNTHESIZED_PLAYBOOK_SPECS = tuple(
    spec
    for spec in CURATED_DERIVED_PLAYBOOK_SPECS
    if spec.family == SYNTHESIZED_PLAYBOOK_SOURCE_TYPE
)

FAMILY_DISPLAY_LABELS = {
    TOPIC_PLAYBOOK_SOURCE_TYPE: "토픽 플레이북",
    OPERATION_PLAYBOOK_SOURCE_TYPE: "운영 플레이북",
    TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE: "트러블슈팅 플레이북",
    POLICY_OVERLAY_BOOK_SOURCE_TYPE: "정책 오버레이 북",
    SYNTHESIZED_PLAYBOOK_SOURCE_TYPE: "합성 플레이북",
}
FAMILY_SLUG_SUFFIXES = {
    TOPIC_PLAYBOOK_SOURCE_TYPE: "topic_playbook",
    OPERATION_PLAYBOOK_SOURCE_TYPE: "operations_playbook",
    TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE: "troubleshooting_playbook",
    POLICY_OVERLAY_BOOK_SOURCE_TYPE: "policy_overlay_book",
    SYNTHESIZED_PLAYBOOK_SOURCE_TYPE: "synthesized_playbook",
}
FAMILY_SUMMARY_SUFFIXES = {
    TOPIC_PLAYBOOK_SOURCE_TYPE: "핵심 토픽 절차와 개념만 추린 집중 플레이북입니다.",
    OPERATION_PLAYBOOK_SOURCE_TYPE: "day-2 운영 절차와 검증 단계를 다시 묶은 운영 플레이북입니다.",
    TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE: "실패 징후, 복구 분기, 점검 절차만 모은 트러블슈팅 플레이북입니다.",
    POLICY_OVERLAY_BOOK_SOURCE_TYPE: "사전 조건, 제한, 검증, 요구 사항을 다시 묶은 정책 오버레이 북입니다.",
    SYNTHESIZED_PLAYBOOK_SOURCE_TYPE: "핵심 설명, 절차, 검증을 한 권으로 압축한 합성 플레이북입니다.",
}
FAMILY_DEFAULT_PREFERRED_ROLES = {
    TOPIC_PLAYBOOK_SOURCE_TYPE: ("procedure", "concept"),
    OPERATION_PLAYBOOK_SOURCE_TYPE: ("procedure", "reference"),
    TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE: ("procedure", "reference"),
    POLICY_OVERLAY_BOOK_SOURCE_TYPE: ("reference", "concept", "procedure"),
    SYNTHESIZED_PLAYBOOK_SOURCE_TYPE: ("procedure", "concept", "reference"),
}
FAMILY_DEFAULT_INCLUDE_OVERVIEW = {
    TOPIC_PLAYBOOK_SOURCE_TYPE: True,
    OPERATION_PLAYBOOK_SOURCE_TYPE: True,
    TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE: False,
    POLICY_OVERLAY_BOOK_SOURCE_TYPE: True,
    SYNTHESIZED_PLAYBOOK_SOURCE_TYPE: True,
}
FAMILY_DEFAULT_MAX_SECTIONS = {
    TOPIC_PLAYBOOK_SOURCE_TYPE: 14,
    OPERATION_PLAYBOOK_SOURCE_TYPE: 12,
    TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE: 10,
    POLICY_OVERLAY_BOOK_SOURCE_TYPE: 10,
    SYNTHESIZED_PLAYBOOK_SOURCE_TYPE: 16,
}
FAMILY_KEYWORD_HINTS = {
    TOPIC_PLAYBOOK_SOURCE_TYPE: ("topic", "workflow", "procedure", "개요", "절차"),
    OPERATION_PLAYBOOK_SOURCE_TYPE: ("operation", "ops", "runbook", "day-2", "운영", "점검", "검증"),
    TROUBLESHOOTING_PLAYBOOK_SOURCE_TYPE: ("troubleshoot", "failure", "error", "debug", "recover", "장애", "실패", "복구"),
    POLICY_OVERLAY_BOOK_SOURCE_TYPE: (
        "policy",
        "must",
        "should",
        "requirement",
        "limit",
        "support",
        "unsupported",
        "security",
        "prerequisite",
        "정책",
        "요구",
        "제한",
        "권장",
        "금지",
        "사전",
        "보안",
    ),
    SYNTHESIZED_PLAYBOOK_SOURCE_TYPE: (
        "overview",
        "workflow",
        "procedure",
        "verification",
        "reference",
        "guide",
        "개요",
        "절차",
        "검증",
        "가이드",
    ),
}


def _read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _write_jsonl_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _derived_source_type(row: dict[str, Any]) -> str:
    source_metadata = row.get("source_metadata") if isinstance(row.get("source_metadata"), dict) else {}
    return str(source_metadata.get("source_type") or "").strip()


def _is_derived_playbook_row(row: dict[str, Any]) -> bool:
    return _derived_source_type(row) in DERIVED_PLAYBOOK_SOURCE_TYPES


def _approved_derivation_source_payload(payload: dict[str, Any]) -> bool:
    source_metadata = payload.get("source_metadata") if isinstance(payload.get("source_metadata"), dict) else {}
    source_type = str(source_metadata.get("source_type") or "").strip()
    return (
        source_type in {"manual_synthesis", "official_doc"}
        and str(payload.get("translation_status") or "").strip() == "approved_ko"
        and str(payload.get("review_status") or "").strip() == "approved"
    )


def _block_text(block: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("title", "text", "code", "caption"):
        value = _stringify(block.get(key))
        if value:
            parts.append(value)
    for item in block.get("items") or []:
        value = _stringify(item)
        if value:
            parts.append(value)
    for step in block.get("steps") or []:
        if not isinstance(step, dict):
            continue
        value = _stringify(step.get("text"))
        if value:
            parts.append(value)
        for substep in step.get("substeps") or []:
            value = _stringify(substep)
            if value:
                parts.append(value)
    return " ".join(parts)


def _section_haystack(section: dict[str, Any]) -> str:
    parts: list[str] = [
        _stringify(section.get("heading")),
        _stringify(section.get("anchor")),
        _stringify(section.get("section_path_label")),
    ]
    for item in section.get("path") or []:
        value = _stringify(item)
        if value:
            parts.append(value)
    for item in section.get("section_path") or []:
        value = _stringify(item)
        if value:
            parts.append(value)
    for block in section.get("blocks") or []:
        if isinstance(block, dict):
            parts.append(_block_text(block))
    return " ".join(part for part in parts if part).lower()


def _family_fallback_roles(spec: DerivedPlaybookSpec) -> tuple[str, ...]:
    if spec.family == TOPIC_PLAYBOOK_SOURCE_TYPE:
        return ("procedure", "concept", "reference")
    if spec.family == POLICY_OVERLAY_BOOK_SOURCE_TYPE:
        return ("reference", "concept", "procedure")
    if spec.family == SYNTHESIZED_PLAYBOOK_SOURCE_TYPE:
        return ("procedure", "concept", "reference")
    return ("procedure", "reference", "concept")


def _tokenize_keywords(*values: str) -> tuple[str, ...]:
    seen: set[str] = set()
    tokens: list[str] = []
    for value in values:
        for token in re.findall(r"[0-9A-Za-z가-힣]+", _stringify(value).lower()):
            if len(token) < 2:
                continue
            if token in seen:
                continue
            seen.add(token)
            tokens.append(token)
    return tuple(tokens)


def _default_derived_title(source_payload: dict[str, Any], family: str) -> str:
    source_title = _stringify(source_payload.get("title")).strip() or _stringify(source_payload.get("book_slug")).strip()
    return f"{source_title} {FAMILY_DISPLAY_LABELS[family]}".strip()


def _default_derived_summary(source_payload: dict[str, Any], family: str) -> str:
    source_title = _stringify(source_payload.get("title")).strip() or _stringify(source_payload.get("book_slug")).strip()
    return f"{source_title}에서 {FAMILY_SUMMARY_SUFFIXES[family]}".strip()


def _default_derived_slug(source_payload: dict[str, Any], family: str) -> str:
    source_slug = _stringify(source_payload.get("book_slug")).strip()
    return f"{source_slug}_{FAMILY_SLUG_SUFFIXES[family]}".strip("_")


def _default_derived_keywords(source_payload: dict[str, Any], family: str) -> tuple[str, ...]:
    source_title = _stringify(source_payload.get("title"))
    source_slug = _stringify(source_payload.get("book_slug"))
    section_terms: list[str] = []
    for section in source_payload.get("sections") or []:
        if not isinstance(section, dict):
            continue
        section_terms.append(_stringify(section.get("heading")))
        section_terms.append(_stringify(section.get("anchor")))
    return _tokenize_keywords(
        source_title,
        source_slug,
        " ".join(section_terms[:8]),
        *FAMILY_KEYWORD_HINTS[family],
    )


def _default_derived_spec(source_payload: dict[str, Any], family: str) -> DerivedPlaybookSpec:
    return DerivedPlaybookSpec(
        source_slug=_stringify(source_payload.get("book_slug")).strip(),
        derived_slug=_default_derived_slug(source_payload, family),
        family=family,
        title=_default_derived_title(source_payload, family),
        summary=_default_derived_summary(source_payload, family),
        keywords=_default_derived_keywords(source_payload, family),
        preferred_roles=FAMILY_DEFAULT_PREFERRED_ROLES[family],
        include_overview=FAMILY_DEFAULT_INCLUDE_OVERVIEW[family],
        max_sections=FAMILY_DEFAULT_MAX_SECTIONS[family],
    )


def _select_derived_sections(
    sections: list[dict[str, Any]],
    spec: DerivedPlaybookSpec,
) -> list[dict[str, Any]]:
    keyword_hits: list[int] = []
    overview_index: int | None = None
    preferred_role_hits: list[int] = []
    fallback_role_hits: list[int] = []
    for index, section in enumerate(sections):
        haystack = _section_haystack(section)
        role = str(section.get("semantic_role") or "").strip().lower()
        if overview_index is None and role in {"overview", "concept"}:
            overview_index = index
        if role in spec.preferred_roles:
            preferred_role_hits.append(index)
        if role in _family_fallback_roles(spec):
            fallback_role_hits.append(index)
        if any(keyword in haystack for keyword in spec.keywords):
            keyword_hits.append(index)

    selected_indices: list[int] = []
    if spec.include_overview and overview_index is not None:
        selected_indices.append(overview_index)
    selected_indices.extend(keyword_hits)
    selected_indices.extend(preferred_role_hits)
    if not selected_indices:
        selected_indices.extend(fallback_role_hits)
    if not selected_indices and sections:
        selected_indices.extend(range(min(len(sections), spec.max_sections)))

    seen: set[int] = set()
    ordered: list[dict[str, Any]] = []
    for index in selected_indices:
        if index in seen:
            continue
        seen.add(index)
        ordered.append(dict(sections[index]))
        if len(ordered) >= spec.max_sections:
            break
    return ordered


def _viewer_base_path(version: str, locale: str, slug: str) -> str:
    return f"/docs/ocp/{version}/{locale}/{slug}/index.html"


def _rewrite_section_for_derived(
    section: dict[str, Any],
    *,
    derived_slug: str,
    viewer_base_path: str,
) -> dict[str, Any]:
    anchor = _stringify(section.get("anchor") or section.get("anchor_id")).strip()
    if not anchor:
        anchor = f"section-{int(section.get('ordinal') or 0)}"
    payload = dict(section)
    payload["section_id"] = f"{derived_slug}:{anchor}"
    payload["section_key"] = f"{derived_slug}:{anchor}"
    payload["viewer_path"] = f"{viewer_base_path}#{anchor}"
    payload["anchor"] = anchor
    payload["anchor_id"] = anchor
    return payload


def _load_source_payload(settings: Settings, source_slug: str) -> dict[str, Any] | None:
    book_path = settings.playbook_books_dir / f"{source_slug}.json"
    if book_path.exists():
        payload = json.loads(book_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    for row in _read_jsonl_rows(settings.playbook_documents_path):
        if str(row.get("book_slug") or "").strip() == source_slug:
            return row
    return None


def _resolved_source_payloads(settings: Settings, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    for row in rows:
        slug = str(row.get("book_slug") or "").strip()
        if not slug or not _approved_derivation_source_payload(row):
            continue
        payload = dict(row)
        loaded = _load_source_payload(settings, slug)
        if loaded is not None:
            merged = dict(payload)
            merged.update(loaded)
            source_metadata = dict(row.get("source_metadata") or {})
            source_metadata.update(loaded.get("source_metadata") or {})
            if source_metadata:
                merged["source_metadata"] = source_metadata
            for key in ("translation_status", "review_status", "version", "locale", "title", "source_uri"):
                if not _stringify(merged.get(key)).strip():
                    merged[key] = row.get(key)
            payload = merged
        if _approved_derivation_source_payload(payload):
            payloads[slug] = payload
    return payloads


def _build_generation_specs(source_payloads: dict[str, dict[str, Any]]) -> list[DerivedPlaybookSpec]:
    override_specs = {
        (spec.source_slug, spec.family): spec
        for spec in CURATED_DERIVED_PLAYBOOK_SPECS
    }
    specs: list[DerivedPlaybookSpec] = []
    for source_slug in sorted(source_payloads):
        for family in sorted(DERIVED_PLAYBOOK_SOURCE_TYPES):
            spec = override_specs.get((source_slug, family))
            if spec is not None:
                specs.append(spec)
    return specs


def _existing_derived_slugs(settings: Settings, rows: list[dict[str, Any]]) -> set[str]:
    slugs = {
        str(row.get("book_slug") or "").strip()
        for row in rows
        if _is_derived_playbook_row(row) and str(row.get("book_slug") or "").strip()
    }
    if not settings.playbook_books_dir.exists():
        return slugs
    for path in settings.playbook_books_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if _is_derived_playbook_row(payload):
            slugs.add(path.stem)
    return slugs


def _derive_playbook_payload(
    source_payload: dict[str, Any],
    spec: DerivedPlaybookSpec,
) -> dict[str, Any] | None:
    if not _approved_derivation_source_payload(source_payload):
        return None
    sections = [
        dict(section)
        for section in source_payload.get("sections") or []
        if isinstance(section, dict)
    ]
    if not sections:
        return None
    selected_sections = _select_derived_sections(sections, spec)
    if not selected_sections:
        return None

    version = _stringify(source_payload.get("version") or "4.20")
    locale = _stringify(source_payload.get("locale") or "ko")
    viewer_base_path = _viewer_base_path(version, locale, spec.derived_slug)
    rewritten_sections = [
        _rewrite_section_for_derived(
            section,
            derived_slug=spec.derived_slug,
            viewer_base_path=viewer_base_path,
        )
        for section in selected_sections
    ]
    anchor_map = {
        str(section.get("anchor") or ""): str(section.get("viewer_path") or "")
        for section in rewritten_sections
        if str(section.get("anchor") or "").strip()
    }

    source_metadata = dict(source_payload.get("source_metadata") or {})
    base_source_id = _stringify(source_metadata.get("source_id")).strip()
    source_metadata.update(
        {
            "source_id": (
                f"{base_source_id}:{spec.family}:{spec.derived_slug}"
                if base_source_id
                else f"{spec.family}:{spec.derived_slug}"
            ),
            "source_type": spec.family,
            "source_lane": "applied_playbook",
            "derived_from_book_slug": _stringify(source_payload.get("book_slug")),
            "derived_from_title": _stringify(source_payload.get("title")),
            "derived_family": spec.family,
            "topic_key": spec.derived_slug,
        }
    )

    payload = dict(source_payload)
    payload.update(
        {
            "book_slug": spec.derived_slug,
            "title": spec.title,
            "topic_summary": spec.summary,
            "section_count": len(rewritten_sections),
            "sections": rewritten_sections,
            "anchor_map": anchor_map,
            "source_metadata": source_metadata,
        }
    )
    return payload


def _family_summary(
    generated_rows: Iterable[dict[str, Any]],
    *,
    family: str,
) -> dict[str, Any]:
    slugs = sorted(
        str(row.get("book_slug") or "").strip()
        for row in generated_rows
        if str(((row.get("source_metadata") or {}).get("source_type") or "")).strip() == family
        and str(row.get("book_slug") or "").strip()
    )
    return {
        "generated_count": len(slugs),
        "generated_slugs": slugs,
    }


def build_expected_derived_playbook_outputs(
    settings: Settings,
    *,
    rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    source_rows = (
        [dict(row) for row in rows]
        if rows is not None
        else _read_jsonl_rows(settings.playbook_documents_path)
    )
    retained_rows = [
        row
        for row in source_rows
        if not _is_derived_playbook_row(row)
    ]
    source_payloads = _resolved_source_payloads(settings, retained_rows)
    generation_specs = _build_generation_specs(source_payloads)
    generated_rows: list[dict[str, Any]] = []
    generated_slugs: list[str] = []
    missing_sources: list[str] = []

    for spec in generation_specs:
        source_payload = source_payloads.get(spec.source_slug)
        if source_payload is None:
            missing_sources.append(spec.source_slug)
            continue
        derived_payload = _derive_playbook_payload(source_payload, spec)
        if derived_payload is None:
            continue
        generated_rows.append(derived_payload)
        generated_slugs.append(spec.derived_slug)

    return {
        "retained_rows": retained_rows,
        "generated_rows": generated_rows,
        "generated_slugs": sorted(generated_slugs),
        "missing_sources": sorted(set(missing_sources)),
    }


def materialize_derived_playbooks(settings: Settings) -> dict[str, Any]:
    rows = _read_jsonl_rows(settings.playbook_documents_path)
    existing_derived_slugs = _existing_derived_slugs(settings, rows)
    expected_outputs = build_expected_derived_playbook_outputs(settings, rows=rows)
    retained_rows = list(expected_outputs["retained_rows"])
    generated_rows = list(expected_outputs["generated_rows"])
    generated_slugs = list(expected_outputs["generated_slugs"])
    missing_sources = list(expected_outputs["missing_sources"])

    _write_jsonl_rows(
        settings.playbook_documents_path,
        retained_rows + sorted(generated_rows, key=lambda row: str(row.get("book_slug") or "")),
    )

    settings.playbook_books_dir.mkdir(parents=True, exist_ok=True)
    for slug in sorted(existing_derived_slugs):
        derived_path = settings.playbook_books_dir / f"{slug}.json"
        if derived_path.exists() and slug not in generated_slugs:
            derived_path.unlink()
    for payload in generated_rows:
        slug = str(payload.get("book_slug") or "").strip()
        if not slug:
            continue
        (settings.playbook_books_dir / f"{slug}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    graph_refresh = refresh_active_runtime_graph_artifacts(
        settings,
        refresh_full_sidecar=False,
        allow_compact_degrade=True,
    )

    family_counts = Counter(
        str(((row.get("source_metadata") or {}).get("source_type") or "")).strip()
        for row in generated_rows
        if str(((row.get("source_metadata") or {}).get("source_type") or "")).strip()
    )
    family_summaries = {
        family: _family_summary(generated_rows, family=family)
        for family in sorted(DERIVED_PLAYBOOK_SOURCE_TYPES)
    }
    return {
        "generated_count": len(generated_rows),
        "generated_slugs": sorted(generated_slugs),
        "missing_sources": sorted(set(missing_sources)),
        "family_counts": dict(sorted(family_counts.items())),
        "family_summaries": family_summaries,
        "graph_compact_refresh": dict(graph_refresh.get("compact_sidecar", {})),
        "graph_compact_artifact": graph_sidecar_compact_artifact_status(settings),
    }


def materialize_topic_playbooks(settings: Settings) -> dict[str, Any]:
    summary = materialize_derived_playbooks(settings)
    topic_summary = dict(summary["family_summaries"].get(TOPIC_PLAYBOOK_SOURCE_TYPE, {}))
    missing_sources = {
        spec.source_slug
        for spec in TOPIC_PLAYBOOK_SPECS
        if spec.source_slug in set(summary["missing_sources"])
    }
    topic_summary["missing_sources"] = sorted(missing_sources)
    return topic_summary


def approved_materialized_derived_playbooks(
    settings: Settings,
    *,
    families: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    approved: list[dict[str, Any]] = []
    family_filter = (
        frozenset(families)
        if families is not None
        else DERIVED_PLAYBOOK_SOURCE_TYPES
    )
    for row in _read_jsonl_rows(settings.playbook_documents_path):
        slug = str(row.get("book_slug") or "").strip()
        if not slug or not _is_derived_playbook_row(row):
            continue
        source_metadata = row.get("source_metadata") if isinstance(row.get("source_metadata"), dict) else {}
        source_type = str(source_metadata.get("source_type") or "").strip()
        if source_type not in DERIVED_PLAYBOOK_SOURCE_TYPES or source_type not in family_filter:
            continue
        if str(row.get("translation_status") or "").strip() != "approved_ko":
            continue
        if str(row.get("review_status") or "").strip() != "approved":
            continue
        if not (settings.playbook_books_dir / f"{slug}.json").exists():
            continue
        approved.append(row)
    return approved


def approved_materialized_topic_playbooks(settings: Settings) -> list[dict[str, Any]]:
    return approved_materialized_derived_playbooks(
        settings,
        families=(TOPIC_PLAYBOOK_SOURCE_TYPE,),
    )
