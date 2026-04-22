"""Goal-first quality gate engine for shared document truth."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from play_book_studio.canonical.models import CanonicalDocumentAst
from play_book_studio.canonical.validate import CanonicalValidationIssue, validate_document_ast


AxisName = Literal[
    "source_fidelity",
    "structure_recovery",
    "reader_grade",
    "chat_grade",
    "governance_grade",
]
VerdictName = Literal["blocked_artifact", "bronze", "silver", "gold", "promoted"]

AXIS_WEIGHTS: dict[AxisName, int] = {
    "source_fidelity": 25,
    "structure_recovery": 20,
    "reader_grade": 20,
    "chat_grade": 20,
    "governance_grade": 15,
}
SEVERITY_DEDUCTIONS = {
    "low": 1.0,
    "medium": 3.0,
    "high": 6.0,
    "critical": 10.0,
}
METRIC_TARGETS = {
    "citation_accuracy": 0.9,
    "faithfulness": 0.9,
    "answer_relevance": 0.85,
    "context_precision": 0.8,
    "context_recall": 0.8,
}


@dataclass(slots=True)
class QualityGateIssue:
    axis: AxisName
    severity: str
    code: str
    message: str
    target_kind: str = ""
    target_id: str = ""
    fail_gate: str = ""
    evidence: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "axis": self.axis,
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "target_kind": self.target_kind,
            "target_id": self.target_id,
            "fail_gate": self.fail_gate,
            "evidence": dict(self.evidence),
        }


@dataclass(slots=True)
class QualityGateAxisScore:
    axis: AxisName
    weight: int
    score: float
    passed: bool
    evidence: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "axis": self.axis,
            "weight": self.weight,
            "score": round(self.score, 2),
            "passed": self.passed,
            "evidence": dict(self.evidence),
        }


@dataclass(slots=True)
class QualityGateResult:
    quality_verdict: VerdictName
    final_verdict: VerdictName
    total_score: float
    axis_scores: tuple[QualityGateAxisScore, ...]
    issues: tuple[QualityGateIssue, ...]
    fail_gates: tuple[str, ...]
    promotion_ready: bool
    evidence: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "quality_verdict": self.quality_verdict,
            "final_verdict": self.final_verdict,
            "total_score": round(self.total_score, 2),
            "axis_scores": [item.to_dict() for item in self.axis_scores],
            "issues": [item.to_dict() for item in self.issues],
            "fail_gates": list(self.fail_gates),
            "promotion_ready": self.promotion_ready,
            "evidence": dict(self.evidence),
        }


def _normalized_text(value: object) -> str:
    return " ".join(str(value or "").split())


def _as_mapping(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _document_payload(document: CanonicalDocumentAst | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(document, CanonicalDocumentAst):
        return document.to_dict()
    payload = dict(document)
    if isinstance(payload.get("document"), Mapping):
        document_meta = dict(payload.get("document") or {})
        sections = [dict(section) for section in payload.get("sections") or [] if isinstance(section, Mapping)]
        blocks = [dict(block) for block in payload.get("blocks") or [] if isinstance(block, Mapping)]
        if sections and blocks and all(not isinstance(section.get("blocks"), list) for section in sections):
            blocks_by_section: dict[str, list[dict[str, Any]]] = {}
            for block in blocks:
                section_id = _normalized_text(block.get("section_id"))
                if not section_id:
                    continue
                blocks_by_section.setdefault(section_id, []).append(block)
            sections = [
                {
                    **section,
                    "blocks": blocks_by_section.get(_normalized_text(section.get("section_id")), []),
                }
                for section in sections
            ]
        return {
            "doc_id": document_meta.get("document_id") or document_meta.get("doc_id") or "",
            "book_slug": document_meta.get("book_slug") or "",
            "title": document_meta.get("title") or "",
            "source_type": document_meta.get("source_type") or "",
            "source_url": document_meta.get("source_uri") or document_meta.get("source_url") or "",
            "viewer_base_path": document_meta.get("viewer_base_path") or "",
            "source_language": document_meta.get("source_language") or "",
            "display_language": document_meta.get("display_language") or "",
            "translation_status": document_meta.get("translation_status") or "",
            "pack_id": document_meta.get("pack_id") or "",
            "pack_label": document_meta.get("pack_label") or "",
            "inferred_product": document_meta.get("product") or document_meta.get("inferred_product") or "",
            "inferred_version": document_meta.get("version") or document_meta.get("inferred_version") or "",
            "sections": sections,
            "provenance": {
                "source_lane": document_meta.get("source_lane") or "",
                "source_fingerprint": document_meta.get("source_fingerprint") or "",
                "parsed_artifact_id": document_meta.get("parsed_artifact_id") or "",
                "review_status": document_meta.get("review_status") or "",
                "translation_stage": document_meta.get("translation_status") or "",
                "tenant_id": document_meta.get("tenant_id") or "",
                "workspace_id": document_meta.get("workspace_id") or "",
                "pack_id": document_meta.get("pack_id") or "",
                "access_groups": document_meta.get("access_groups") or [],
                "provider_egress_policy": document_meta.get("provider_egress_policy") or "",
                "approval_state": document_meta.get("approval_state") or "",
                "publication_state": document_meta.get("publication_state") or "",
                "citation_eligible": bool(document_meta.get("review_status") == "approved"),
            },
        }
    return payload


def _parsed_artifact_payload(parsed_artifact: object | None) -> dict[str, Any]:
    if parsed_artifact is None:
        return {}
    if isinstance(parsed_artifact, Mapping):
        return dict(parsed_artifact)
    to_dict = getattr(parsed_artifact, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        if isinstance(payload, Mapping):
            return dict(payload)
    raise TypeError("parsed_artifact must be a mapping or provide to_dict()")


def _document_meta(payload: dict[str, Any], parsed_payload: dict[str, Any]) -> dict[str, Any]:
    provenance = _as_mapping(payload.get("provenance"))
    source_ref = _as_mapping(parsed_payload.get("source_ref"))
    security = _as_mapping(parsed_payload.get("security_envelope"))
    quality_state = _as_mapping(parsed_payload.get("quality_state"))
    return {
        "doc_id": _normalized_text(payload.get("doc_id")),
        "book_slug": _normalized_text(payload.get("book_slug")),
        "title": _normalized_text(payload.get("title")),
        "source_url": _normalized_text(payload.get("source_url")),
        "source_lane": _normalized_text(provenance.get("source_lane") or source_ref.get("source_lane")),
        "source_type": _normalized_text(payload.get("source_type") or provenance.get("source_type") or source_ref.get("source_type")),
        "source_fingerprint": _normalized_text(provenance.get("source_fingerprint") or source_ref.get("source_fingerprint")),
        "parsed_artifact_id": _normalized_text(provenance.get("parsed_artifact_id") or parsed_payload.get("parsed_artifact_id")),
        "source_language": _normalized_text(payload.get("source_language")),
        "display_language": _normalized_text(payload.get("display_language")),
        "translation_status": _normalized_text(payload.get("translation_status") or provenance.get("translation_stage")),
        "translation_stage": _normalized_text(provenance.get("translation_stage")),
        "review_status": _normalized_text(provenance.get("review_status") or quality_state.get("review_status")),
        "citation_eligible": bool(provenance.get("citation_eligible")),
        "tenant_id": _normalized_text(provenance.get("tenant_id") or security.get("tenant_id")),
        "workspace_id": _normalized_text(provenance.get("workspace_id") or security.get("workspace_id")),
        "pack_id": _normalized_text(payload.get("pack_id") or provenance.get("pack_id") or security.get("pack_id")),
        "access_groups": tuple(
            _normalized_text(item)
            for item in (provenance.get("access_groups") or security.get("access_groups") or [])
            if _normalized_text(item)
        ),
        "provider_egress_policy": _normalized_text(
            provenance.get("provider_egress_policy") or security.get("provider_egress_policy")
        ),
        "approval_state": _normalized_text(provenance.get("approval_state")),
        "publication_state": _normalized_text(provenance.get("publication_state")),
    }


def _sections(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(section) for section in payload.get("sections") or [] if isinstance(section, Mapping)]


def _block_kind(block: Mapping[str, Any]) -> str:
    return _normalized_text(block.get("kind") or block.get("block_type")).lower()


def _block_has_content(block: Mapping[str, Any]) -> bool:
    kind = _block_kind(block)
    if kind in {"paragraph", "heading", "quote", "callout", "xref", "speaker_note", "slide_summary", "diagram_summary"}:
        return bool(_normalized_text(block.get("text") or block.get("label")))
    if kind in {"list", "prerequisite"}:
        return any(_normalized_text(item) for item in block.get("items") or [])
    if kind in {"procedure", "procedure_step"}:
        if _normalized_text(block.get("text")):
            return True
        steps = block.get("steps") or []
        return any(_normalized_text(step.get("text") if isinstance(step, Mapping) else step) for step in steps)
    if kind == "code":
        return bool(_normalized_text(block.get("code")))
    if kind == "table":
        headers = [_normalized_text(item) for item in block.get("headers") or [] if _normalized_text(item)]
        rows = block.get("rows") or []
        return bool(headers) and bool(rows)
    if kind == "figure":
        return bool(
            _normalized_text(block.get("caption"))
            or _normalized_text(block.get("figure_asset_id"))
            or _normalized_text(block.get("image_path"))
        )
    return bool(
        _normalized_text(block.get("text"))
        or _normalized_text(block.get("code"))
        or _normalized_text(block.get("caption"))
    )


def _validation_issues(document: CanonicalDocumentAst | Mapping[str, Any], payload: dict[str, Any]) -> list[CanonicalValidationIssue]:
    if isinstance(document, CanonicalDocumentAst):
        return validate_document_ast(document)
    issues: list[CanonicalValidationIssue] = []
    if not _normalized_text(payload.get("doc_id")):
        issues.append(CanonicalValidationIssue("error", "missing_doc_id", "문서 id가 비어 있습니다."))
    if not _normalized_text(payload.get("title")):
        issues.append(CanonicalValidationIssue("error", "missing_title", "문서 제목이 비어 있습니다."))
    seen_section_ids: set[str] = set()
    seen_anchors: set[str] = set()
    for section in _sections(payload):
        section_id = _normalized_text(section.get("section_id"))
        anchor = _normalized_text(section.get("anchor"))
        if not section_id:
            issues.append(CanonicalValidationIssue("error", "missing_section_id", "section id가 비어 있습니다."))
        if section_id and section_id in seen_section_ids:
            issues.append(CanonicalValidationIssue("error", "duplicate_section_id", f"중복 section id: {section_id}", section_id=section_id))
        seen_section_ids.add(section_id)
        if not _normalized_text(section.get("heading")):
            issues.append(CanonicalValidationIssue("error", "missing_heading", "section heading이 비어 있습니다.", section_id=section_id))
        if not list(section.get("blocks") or []):
            issues.append(CanonicalValidationIssue("warning", "empty_blocks", "section block이 비어 있습니다.", section_id=section_id))
        if anchor and anchor in seen_anchors:
            issues.append(CanonicalValidationIssue("warning", "duplicate_anchor", f"중복 anchor: {anchor}", section_id=section_id))
        if anchor:
            seen_anchors.add(anchor)
    if not _sections(payload):
        issues.append(CanonicalValidationIssue("error", "missing_sections", "문서 section이 없습니다."))
    return issues


def _issue(axis: AxisName, severity: str, code: str, message: str, *, fail_gate: str = "", target_kind: str = "", target_id: str = "", evidence: Mapping[str, object] | None = None) -> QualityGateIssue:
    return QualityGateIssue(
        axis=axis,
        severity=severity,
        code=code,
        message=message,
        fail_gate=fail_gate,
        target_kind=target_kind,
        target_id=target_id,
        evidence=dict(evidence or {}),
    )


def evaluate_document_quality(
    document: CanonicalDocumentAst | Mapping[str, Any],
    *,
    parsed_artifact: object | None = None,
    chat_metrics: Mapping[str, Any] | None = None,
) -> QualityGateResult:
    payload = _document_payload(document)
    parsed_payload = _parsed_artifact_payload(parsed_artifact)
    meta = _document_meta(payload, parsed_payload)
    sections = _sections(payload)
    validation_issues = _validation_issues(document, payload)
    issues: list[QualityGateIssue] = []

    if not sections:
        issues.append(_issue("source_fidelity", "critical", "missing_sections", "문서 section이 없어 원문 보존성을 평가할 수 없습니다.", fail_gate="fidelity"))

    if not meta["source_url"]:
        issues.append(_issue("source_fidelity", "high", "missing_source_url", "원문 URL이 비어 있습니다.", evidence={"field": "source_url"}))
    if not meta["source_fingerprint"]:
        issues.append(_issue("source_fidelity", "high", "missing_source_fingerprint", "source fingerprint가 없어 원문 매핑이 약합니다.", evidence={"field": "source_fingerprint"}))
    if not meta["parsed_artifact_id"]:
        issues.append(_issue("source_fidelity", "medium", "missing_parsed_artifact_id", "parsed artifact id가 비어 있습니다.", evidence={"field": "parsed_artifact_id"}))
    if meta["source_lane"].startswith("vendor_official") and meta["display_language"] == "ko" and meta["source_language"] == "en" and meta["translation_status"] in {"original", ""}:
        issues.append(_issue("source_fidelity", "critical", "translation_incomplete", "공식 lane 영어 원문이 번역 완료 없이 남아 있습니다.", fail_gate="fidelity", evidence={"translation_status": meta["translation_status"]}))

    empty_sections = 0
    empty_content_blocks = 0
    paragraph_only_sections = 0
    unknown_role_sections = 0
    procedure_role_without_steps = 0
    landing_ready_sections = 0
    total_blocks = 0
    table_block_count = 0
    figure_block_count = 0
    for section in sections:
        section_id = _normalized_text(section.get("section_id"))
        blocks = [dict(block) for block in section.get("blocks") or [] if isinstance(block, Mapping)]
        if not blocks:
            empty_sections += 1
        anchor = _normalized_text(section.get("anchor"))
        viewer_path = _normalized_text(section.get("viewer_path"))
        if anchor and viewer_path:
            landing_ready_sections += 1
        semantic_role = _normalized_text(section.get("semantic_role") or "unknown")
        if semantic_role == "unknown":
            unknown_role_sections += 1
        block_kinds = [_block_kind(block) for block in blocks]
        if blocks and block_kinds and all(kind == "paragraph" for kind in block_kinds):
            paragraph_only_sections += 1
        if semantic_role == "procedure" and not any(kind in {"procedure", "procedure_step", "code", "prerequisite"} for kind in block_kinds):
            procedure_role_without_steps += 1
        for block in blocks:
            total_blocks += 1
            kind = _block_kind(block)
            if kind == "table":
                table_block_count += 1
            if kind == "figure":
                figure_block_count += 1
            if not _block_has_content(block):
                empty_content_blocks += 1
                severity = "high" if kind in {"code", "table", "figure"} else "medium"
                fail_gate = "fidelity" if kind in {"code", "table", "figure"} else ""
                issues.append(_issue("source_fidelity", severity, f"empty_{kind or 'block'}", f"{kind or 'block'} block 내용이 비어 있습니다.", fail_gate=fail_gate, target_kind="block", target_id=section_id))

    if empty_sections:
        severity = "critical" if empty_sections == len(sections) else "high"
        fail_gate = "fidelity" if empty_sections == len(sections) else ""
        issues.append(_issue("source_fidelity", severity, "empty_sections", "비어 있는 section이 존재합니다.", fail_gate=fail_gate, evidence={"empty_section_count": empty_sections}))

    if not meta["source_lane"]:
        issues.append(_issue("governance_grade", "critical", "missing_source_lane", "source lane이 비어 있습니다.", fail_gate="governance", evidence={"field": "source_lane"}))
    if not meta["tenant_id"] or not meta["workspace_id"] or not meta["pack_id"]:
        issues.append(_issue("governance_grade", "critical", "missing_boundary_identity", "tenant/workspace/pack identity가 비어 있습니다.", fail_gate="governance", evidence={"tenant_id": meta["tenant_id"], "workspace_id": meta["workspace_id"], "pack_id": meta["pack_id"]}))
    if not meta["access_groups"]:
        issues.append(_issue("governance_grade", "critical", "missing_access_groups", "access_groups가 비어 있습니다.", fail_gate="governance"))
    if not meta["provider_egress_policy"]:
        issues.append(_issue("governance_grade", "medium", "missing_provider_egress_policy", "provider egress policy가 비어 있습니다."))
    if meta["source_lane"].startswith("customer") and "public" in meta["access_groups"]:
        issues.append(_issue("governance_grade", "critical", "customer_boundary_blur", "customer lane 문서가 public access group과 섞여 있습니다.", fail_gate="governance"))

    for validation_issue in validation_issues:
        if validation_issue.code in {"duplicate_section_id", "missing_heading", "missing_section_id", "missing_sections"}:
            issues.append(_issue("structure_recovery", "critical", validation_issue.code, validation_issue.message, fail_gate="structure", target_kind="section", target_id=validation_issue.section_id))
        elif validation_issue.code in {"duplicate_anchor"}:
            issues.append(_issue("structure_recovery", "high", validation_issue.code, validation_issue.message, target_kind="section", target_id=validation_issue.section_id))
        elif validation_issue.code in {"empty_blocks"}:
            issues.append(_issue("structure_recovery", "medium", validation_issue.code, validation_issue.message, target_kind="section", target_id=validation_issue.section_id))

    if sections and unknown_role_sections / max(len(sections), 1) > 0.8:
        issues.append(_issue("structure_recovery", "high", "semantic_roles_unknown", "대부분의 section semantic role이 unknown입니다.", evidence={"unknown_ratio": round(unknown_role_sections / max(len(sections), 1), 4)}))
    if sections and procedure_role_without_steps:
        issues.append(_issue("reader_grade", "high", "procedure_sections_not_framed", "procedure semantic role section에 절차/명령 framing이 부족합니다.", evidence={"count": procedure_role_without_steps}))
    if sections and paragraph_only_sections / max(len(sections), 1) > 0.6:
        issues.append(_issue("reader_grade", "high", "wall_of_text_risk", "문서가 paragraph dump에 치우쳐 reader rhythm이 약합니다.", evidence={"paragraph_only_ratio": round(paragraph_only_sections / max(len(sections), 1), 4)}))

    if landing_ready_sections == 0:
        issues.append(_issue("chat_grade", "critical", "citation_landing_unavailable", "anchor와 viewer landing이 가능한 section이 없습니다.", fail_gate="chat"))
    if not meta["citation_eligible"]:
        issues.append(_issue("chat_grade", "high", "citation_not_eligible", "citation eligibility가 비활성화되어 chat-grade가 약합니다."))

    parsed_tables = len(parsed_payload.get("table_refs") or [])
    parsed_figures = len(parsed_payload.get("figure_refs") or [])
    if parsed_tables and table_block_count == 0:
        issues.append(_issue("source_fidelity", "critical", "table_loss_against_parsed_artifact", "parsed artifact에 table이 있는데 AST block으로 보존되지 않았습니다.", fail_gate="fidelity", evidence={"expected_tables": parsed_tables}))
    if parsed_figures and figure_block_count == 0:
        issues.append(_issue("source_fidelity", "critical", "figure_loss_against_parsed_artifact", "parsed artifact에 figure가 있는데 AST block으로 보존되지 않았습니다.", fail_gate="fidelity", evidence={"expected_figures": parsed_figures}))

    metric_evidence: dict[str, float] = {}
    for metric_name, target in METRIC_TARGETS.items():
        raw_value = (chat_metrics or {}).get(metric_name)
        if raw_value is None:
            continue
        try:
            value = max(0.0, min(1.0, float(raw_value)))
        except (TypeError, ValueError):
            continue
        metric_evidence[metric_name] = round(value, 4)
        if value < 0.5 and metric_name in {"citation_accuracy", "faithfulness"}:
            issues.append(_issue("chat_grade", "critical", f"{metric_name}_too_low", f"{metric_name}가 너무 낮아 grounded answer를 신뢰하기 어렵습니다.", fail_gate="chat", evidence={"value": round(value, 4), "target": target}))
        elif value < target - 0.15:
            issues.append(_issue("chat_grade", "high", f"{metric_name}_below_target", f"{metric_name}가 목표치보다 크게 낮습니다.", evidence={"value": round(value, 4), "target": target}))
        elif value < target:
            issues.append(_issue("chat_grade", "medium", f"{metric_name}_below_target", f"{metric_name}가 목표치에 못 미칩니다.", evidence={"value": round(value, 4), "target": target}))
    if bool((chat_metrics or {}).get("unsupported_synthesis_detected")):
        issues.append(_issue("chat_grade", "critical", "unsupported_synthesis_detected", "근거 없는 synthesis가 감지되었습니다.", fail_gate="chat"))
    if bool((chat_metrics or {}).get("viewer_chat_truth_drift")):
        issues.append(_issue("chat_grade", "critical", "viewer_chat_truth_drift", "viewer와 chat truth drift가 감지되었습니다.", fail_gate="chat"))

    axis_scores: list[QualityGateAxisScore] = []
    fail_gates = tuple(sorted({item.fail_gate for item in issues if item.fail_gate}))
    for axis, weight in AXIS_WEIGHTS.items():
        axis_issues = [item for item in issues if item.axis == axis]
        if any(item.fail_gate for item in axis_issues):
            score = 0.0
        else:
            deductions = sum(SEVERITY_DEDUCTIONS.get(item.severity, 0.0) for item in axis_issues)
            score = max(0.0, float(weight) - deductions)
        axis_scores.append(
            QualityGateAxisScore(
                axis=axis,
                weight=weight,
                score=score,
                passed=not any(item.fail_gate for item in axis_issues) and score >= weight * 0.75,
                evidence={
                    "issue_count": len(axis_issues),
                    "blocking_issue_count": sum(1 for item in axis_issues if item.fail_gate),
                },
            )
        )

    total_score = round(sum(item.score for item in axis_scores), 2)
    if fail_gates or total_score < 60.0:
        quality_verdict: VerdictName = "blocked_artifact"
    elif total_score >= 90.0:
        quality_verdict = "gold"
    elif total_score >= 78.0:
        quality_verdict = "silver"
    else:
        quality_verdict = "bronze"

    promotion_ready = (
        quality_verdict == "gold"
        and not fail_gates
        and meta["review_status"] == "approved"
        and meta["approval_state"] == "approved"
        and meta["citation_eligible"]
        and meta["translation_status"] == "approved_ko"
    )
    final_verdict: VerdictName = "promoted" if promotion_ready else quality_verdict
    return QualityGateResult(
        quality_verdict=quality_verdict,
        final_verdict=final_verdict,
        total_score=total_score,
        axis_scores=tuple(axis_scores),
        issues=tuple(issues),
        fail_gates=fail_gates,
        promotion_ready=promotion_ready,
        evidence={
            "section_count": len(sections),
            "block_count": total_blocks,
            "empty_section_count": empty_sections,
            "empty_content_block_count": empty_content_blocks,
            "landing_ready_section_count": landing_ready_sections,
            "paragraph_only_section_count": paragraph_only_sections,
            "unknown_role_section_count": unknown_role_sections,
            "table_block_count": table_block_count,
            "figure_block_count": figure_block_count,
            "chat_metrics": metric_evidence,
        },
    )


__all__ = [
    "AXIS_WEIGHTS",
    "QualityGateAxisScore",
    "QualityGateIssue",
    "QualityGateResult",
    "evaluate_document_quality",
]
