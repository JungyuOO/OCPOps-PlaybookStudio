"""Gold Build repair contract for LLM Wiki document intake.

The Gold gate is a diagnostic step, not the final product state. This module
keeps that contract explicit: diagnose what blocks Gold, apply deterministic
repairs when possible, and return a run payload that UI/API surfaces can show
as a repair log and Gold evidence.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, replace
from typing import Any

from play_book_studio.ingestion.audit_rules import HANGUL_SYLLABLE_RE, LATIN_LETTER_RE
from play_book_studio.ingestion.document_parsing import DocumentChunk, ParsedUploadDocument


GOLD_BUILD_SCHEMA = "llm_wiki.gold_build_run.v1"
GOLD_BUILD_STAGES = ("diagnose", "repair", "rebuild", "reindex", "verify", "promote")
NON_KO_BLOCKING_RATIO = 0.05
MIXED_KO_BLOCKING_RATIO = 0.7

_HEADING_RE = re.compile(r"^\s*#{1,6}\s+\S+", re.MULTILINE)
_CODE_FENCE_RE = re.compile(r"```")
_COMMANDISH_LINE_RE = re.compile(
    r"^\s*(?:oc|kubectl|helm|podman|docker|crc|systemctl|journalctl|curl|ssh|sudo)\b",
    re.IGNORECASE | re.MULTILINE,
)
_TABLEISH_LINE_RE = re.compile(r"^\s*\|[^|\n]+\|[^|\n]+", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class GoldPreparedUpload:
    parsed: ParsedUploadDocument
    chunks: tuple[DocumentChunk, ...]
    run: dict[str, Any]


def prepare_upload_gold_build_candidate(
    parsed: ParsedUploadDocument,
    chunks: tuple[DocumentChunk, ...],
    *,
    source_scope: str = "user_upload",
    dry_run: bool = False,
    index_result: dict[str, Any] | None = None,
) -> GoldPreparedUpload:
    """Apply deterministic upload repairs before persistence/indexing."""

    repair_actions: list[dict[str, Any]] = []
    diagnostics = _diagnose_upload(parsed, chunks, index_result=index_result)
    repaired_parsed = parsed
    repaired_chunks = chunks

    if _has_diagnostic(diagnostics, "zero_sections") and chunks:
        title = _upload_title(parsed)
        repaired_parsed, repaired_chunks = _apply_synthetic_sections(parsed, chunks, title=title)
        repair_actions.append(
            _repair_action(
                "semantic_section_rebuild",
                diagnostic="zero_sections",
                status="applied",
                title="의미 단위 section 자동 생성",
                summary="heading이 없는 업로드 문서에 파일명 기반 루트 section과 viewer anchor를 부여했습니다.",
                evidence=[f"synthetic_section={title}", f"chunk_count={len(repaired_chunks)}"],
                next_action="Reader에서 목차와 chunk anchor가 열리는지 확인",
            )
        )

    # Re-diagnose after deterministic repairs. Non-deterministic repairs remain
    # explicit work orders instead of being mislabeled as Gold.
    remaining_diagnostics = _diagnose_upload(repaired_parsed, repaired_chunks, index_result=index_result)
    repair_actions.extend(
        _planned_repair_actions(
            remaining_diagnostics,
            already_applied={str(action.get("diagnostic") or "") for action in repair_actions},
        )
    )
    run = build_gold_build_run(
        run_id=_run_id("upload", parsed.sha256),
        source_kind="upload",
        source_scope=source_scope or "user_upload",
        title=_upload_title(repaired_parsed),
        diagnostics=remaining_diagnostics,
        repair_actions=repair_actions,
        dry_run=dry_run,
        index_result=index_result,
        metrics={
            "block_count": len(repaired_parsed.blocks),
            "chunk_count": len(repaired_chunks),
            "section_count": _section_count(repaired_chunks),
            "asset_count": len(repaired_parsed.assets),
            **_language_profile([chunk.embedding_text or chunk.markdown for chunk in repaired_chunks] or [repaired_parsed.markdown]),
        },
    )
    return GoldPreparedUpload(parsed=repaired_parsed, chunks=repaired_chunks, run=run)


def with_index_verification(run: dict[str, Any], *, index_result: dict[str, Any] | None) -> dict[str, Any]:
    """Return a run updated with Qdrant indexing evidence."""

    metrics = dict(run.get("metrics") or {})
    chunk_count = int(metrics.get("chunk_count") or 0)
    diagnostics = [
        dict(item)
        for item in (run.get("diagnostics") or [])
        if str(item.get("code") or "") not in {"citation_gap", "index_gap"}
    ]
    if index_result is not None:
        indexed_count = _safe_int(index_result.get("indexed_count"))
        candidate_count = _safe_int(index_result.get("candidate_count"))
        index_error = str(index_result.get("error") or "").strip()
        metrics["qdrant_candidate_count"] = candidate_count
        metrics["qdrant_indexed_count"] = indexed_count
        if chunk_count > 0 and indexed_count < chunk_count:
            evidence = [f"chunks={chunk_count}", f"indexed={indexed_count}"]
            if index_error:
                evidence.append(f"error={index_error}")
            diagnostics.append(
                _diagnostic(
                    "index_gap",
                    severity="blocking",
                    summary="Qdrant 색인이 완료되지 않았습니다." if index_error else "chunk 수보다 Qdrant index 수가 적습니다.",
                    evidence=evidence,
                )
            )
    return build_gold_build_run(
        run_id=str(run.get("run_id") or _run_id("gold", str(metrics))),
        source_kind=str(run.get("source_kind") or ""),
        source_scope=str(run.get("source_scope") or ""),
        title=str(run.get("title") or ""),
        diagnostics=diagnostics,
        repair_actions=[dict(item) for item in (run.get("repair_actions") or [])],
        dry_run=bool(run.get("dry_run")),
        index_result=index_result,
        metrics=metrics,
    )


def build_official_materialize_gold_run(report: dict[str, Any]) -> dict[str, Any]:
    """Build a Gold Build run from the official source materializer report."""

    smoke = report.get("smoke") if isinstance(report.get("smoke"), dict) else {}
    draft_summary = report.get("draft_summary") if isinstance(report.get("draft_summary"), dict) else {}
    gold_summary = report.get("gold_summary") if isinstance(report.get("gold_summary"), dict) else {}
    diagnostics: list[dict[str, Any]] = []
    if not bool(smoke.get("viewer_ready")):
        diagnostics.append(_diagnostic("viewer_smoke_failed", severity="blocking", summary="viewer가 열리지 않았습니다."))
    if not bool(smoke.get("source_meta_ready")):
        diagnostics.append(_diagnostic("citation_gap", severity="blocking", summary="source metadata가 viewer와 연결되지 않았습니다."))
    if not bool(smoke.get("approved_manifest_present")):
        diagnostics.append(_diagnostic("missing_source_provenance", severity="blocking", summary="approved manifest에 원천 증거가 없습니다."))

    repair_actions = [
        _repair_action(
            "ko_operational_rewrite",
            diagnostic="non_ko_content",
            status="applied",
            title="공식 KO 운영 문서체 생성",
            summary="translation draft 생성과 Gold promotion 경로를 실행했습니다.",
            evidence=[f"generated={draft_summary.get('generated_count', '')}".strip("=")],
            next_action="언어 gate report와 viewer smoke를 재확인",
        ),
        _repair_action(
            "anchor_metadata_rebuild",
            diagnostic="citation_gap",
            status="applied",
            title="viewer/citation anchor 재빌드",
            summary="Gold promotion 단계에서 reader metadata와 Qdrant sync를 실행했습니다.",
            evidence=[f"qdrant={gold_summary.get('qdrant_upserted_count', '')}".strip("=")],
            next_action="질문 재시도 시 citation href가 reader로 연결되는지 확인",
        ),
    ]
    return build_gold_build_run(
        run_id=_run_id("official", f"{report.get('book_slug')}:{report.get('source_basis')}"),
        source_kind="official_candidate",
        source_scope="official_docs",
        title=str(report.get("title") or report.get("book_slug") or ""),
        diagnostics=diagnostics,
        repair_actions=repair_actions,
        dry_run=False,
        index_result=None,
        metrics={
            "section_count": _safe_int(draft_summary.get("section_count")),
            "chunk_count": _safe_int(draft_summary.get("chunk_count")),
            "promoted_count": _safe_int(gold_summary.get("promoted_count")),
            "qdrant_indexed_count": _safe_int(gold_summary.get("qdrant_upserted_count")),
        },
    )


def gold_build_contract_from_blockers(
    blockers: list[str],
    *,
    title: str = "",
    source_kind: str = "approved_wiki_runtime",
    source_scope: str = "official_docs",
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    diagnostics = [
        _diagnostic_from_blocker(blocker)
        for blocker in blockers
        if str(blocker or "").strip()
    ]
    repair_actions = _planned_repair_actions(diagnostics)
    return build_gold_build_run(
        run_id=_run_id(source_kind, f"{title}:{','.join(blockers)}"),
        source_kind=source_kind,
        source_scope=source_scope,
        title=title,
        diagnostics=diagnostics,
        repair_actions=repair_actions,
        dry_run=False,
        index_result=None,
        metrics=metrics or {},
    )


def build_gold_build_run(
    *,
    run_id: str,
    source_kind: str,
    source_scope: str,
    title: str,
    diagnostics: list[dict[str, Any]],
    repair_actions: list[dict[str, Any]],
    dry_run: bool,
    index_result: dict[str, Any] | None,
    metrics: dict[str, Any],
) -> dict[str, Any]:
    blocking = [item for item in diagnostics if str(item.get("severity") or "") == "blocking"]
    unapplied_actions = [
        action
        for action in repair_actions
        if str(action.get("status") or "") not in {"applied", "verified", "not_needed"}
    ]
    index_ready = _index_evidence_complete(index_result=index_result, metrics=metrics)
    status = "gold" if not dry_run and not blocking and not unapplied_actions and index_ready else "building_gold"
    if dry_run:
        status = "auto_candidate"
    elif unapplied_actions:
        status = "needs_manual_repair"
    elif blocking:
        status = "repairing"
    stage_results = _stage_results(
        status=status,
        diagnostics=diagnostics,
        repair_actions=repair_actions,
        index_result=index_result,
        metrics=metrics,
    )
    return {
        "schema": GOLD_BUILD_SCHEMA,
        "run_id": run_id,
        "status": status,
        "final_grade": "Gold" if status == "gold" else "Gold Build Repair",
        "source_kind": source_kind,
        "source_scope": source_scope,
        "title": title,
        "policy": "Gold Gate is a repair diagnostic. Bad documents are repaired into readable Wiki docs before promotion.",
        "diagnostics": diagnostics,
        "repair_attempts": len([action for action in repair_actions if str(action.get("status") or "") == "applied"]),
        "repair_actions": repair_actions,
        "stage_results": stage_results,
        "current_stage": _current_stage(status),
        "metrics": metrics,
        "gold_evidence": _gold_evidence(status=status, metrics=metrics, stage_results=stage_results),
        "manual_repair_needed": status == "needs_manual_repair",
        "reader_path": "",
        "qdrant_index": index_result or {},
    }


def _diagnose_upload(
    parsed: ParsedUploadDocument,
    chunks: tuple[DocumentChunk, ...],
    *,
    index_result: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    chunk_count = len(chunks)
    section_count = _section_count(chunks)
    if len(parsed.blocks) <= 0 or section_count <= 0:
        diagnostics.append(
            _diagnostic(
                "zero_sections",
                severity="blocking",
                summary="읽을 수 있는 Wiki section이 없습니다.",
                evidence=[f"blocks={len(parsed.blocks)}", f"sections={section_count}"],
            )
        )
    if chunk_count <= 0:
        diagnostics.append(_diagnostic("zero_chunks", severity="blocking", summary="검색/인용에 쓸 chunk가 없습니다."))
    language = _language_profile([chunk.embedding_text or chunk.markdown for chunk in chunks] or [parsed.markdown])
    if language["text_unit_count"] > 0 and language["hangul_unit_ratio"] < NON_KO_BLOCKING_RATIO:
        diagnostics.append(
            _diagnostic(
                "non_ko_content",
                severity="blocking",
                summary="본문이 한국어 운영 문서체로 정리되지 않았습니다.",
                evidence=[
                    f"hangul_ratio={language['hangul_unit_ratio']}",
                    f"latin_only_ratio={language['latin_only_unit_ratio']}",
                ],
            )
        )
    elif language["text_unit_count"] > 0 and language["hangul_unit_ratio"] < MIXED_KO_BLOCKING_RATIO:
        diagnostics.append(
            _diagnostic(
                "mixed_ko_content",
                severity="blocking",
                summary="한국어 운영 문서 비율이 낮아 Gold 승급 전에 재작성 검수가 필요합니다.",
                evidence=[
                    f"hangul_ratio={language['hangul_unit_ratio']}",
                    f"latin_only_ratio={language['latin_only_unit_ratio']}",
                ],
            )
        )
    if _has_poor_readability(parsed.markdown):
        diagnostics.append(
            _diagnostic(
                "poor_readability",
                severity="warning",
                summary="긴 문단이 절차/주의/명령 블록으로 정리되지 않았습니다.",
            )
        )
    if _TABLEISH_LINE_RE.search(parsed.markdown) and "|---" not in parsed.markdown:
        diagnostics.append(_diagnostic("table_loss", severity="warning", summary="표가 Markdown table로 안정화되지 않았을 수 있습니다."))
    if _COMMANDISH_LINE_RE.search(parsed.markdown) and not _CODE_FENCE_RE.search(parsed.markdown):
        diagnostics.append(_diagnostic("code_loss", severity="blocking", summary="명령어가 code block으로 보호되지 않았습니다."))
    if index_result is not None:
        indexed_count = _safe_int(index_result.get("indexed_count"))
        if chunk_count > 0 and indexed_count < chunk_count:
            diagnostics.append(
                _diagnostic(
                    "index_gap",
                    severity="blocking",
                    summary="Qdrant 색인이 chunk 수와 맞지 않습니다.",
                    evidence=[f"chunks={chunk_count}", f"indexed={indexed_count}"],
                )
            )
    return diagnostics


def _planned_repair_actions(
    diagnostics: list[dict[str, Any]],
    *,
    already_applied: set[str] | None = None,
) -> list[dict[str, Any]]:
    already_applied = already_applied or set()
    rows: list[dict[str, Any]] = []
    for diagnostic in diagnostics:
        if str(diagnostic.get("severity") or "") != "blocking":
            continue
        code = str(diagnostic.get("code") or "")
        if code in already_applied:
            continue
        rows.append(_planned_repair_action_for(code, diagnostic))
    return [row for row in rows if row]


def _planned_repair_action_for(code: str, diagnostic: dict[str, Any]) -> dict[str, Any]:
    if code in {"zero_sections", "zero_chunks", "missing_runtime_artifact", "missing_viewer_path"}:
        return _repair_action(
            "semantic_section_rebuild",
            diagnostic=code,
            status="manual_required" if code != "zero_sections" else "queued",
            title="section/chunk 재생성",
            summary="원문에서 heading을 다시 추출하고 없으면 의미 단위 section을 생성해야 합니다.",
            evidence=list(diagnostic.get("evidence") or []),
            next_action="Gold Build rebuild 단계에서 section/chunk 생성 경로 재실행",
        )
    if code in {"non_ko_content", "mixed_ko_content", "language_quality_failed", "language_gate_missing"}:
        return _repair_action(
            "ko_operational_rewrite",
            diagnostic=code,
            status="provider_required",
            title="한국어 운영 문서체 재작성",
            summary="기술 의미, 명령어, 리소스명은 보존하고 설명 문장을 한국어 운영 문서체로 재작성해야 합니다.",
            evidence=list(diagnostic.get("evidence") or []),
            next_action="LLM repair writer 연결 후 한국어 품질 gate 재실행",
        )
    if code == "poor_readability":
        return _repair_action(
            "reader_readability_reflow",
            diagnostic=code,
            status="queued",
            title="가독성 리플로우",
            summary="긴 문단을 절차, 주의사항, 확인 명령, 예상 결과로 재배치해야 합니다.",
            next_action="Reader payload 재빌드 전에 Markdown 구조 재작성",
        )
    if code == "table_loss":
        return _repair_action(
            "table_restore",
            diagnostic=code,
            status="queued",
            title="표 구조 복원",
            summary="깨진 표를 Markdown table 또는 key-value block으로 복원해야 합니다.",
            next_action="표 복원 후 reader smoke와 chunk anchor 확인",
        )
    if code == "code_loss":
        return _repair_action(
            "code_block_restore",
            diagnostic=code,
            status="queued",
            title="명령어/code block 보존",
            summary="oc/kubectl/YAML 같은 실행 단위를 자연어로 뭉개지 않도록 code block으로 보호해야 합니다.",
            next_action="code block 복원 후 chunk metadata에 command evidence 기록",
        )
    if code in {"citation_gap", "index_gap", "missing_source_provenance", "missing_source_lane"}:
        return _repair_action(
            "anchor_metadata_rebuild",
            diagnostic=code,
            status="queued",
            title="citation/source metadata 재빌드",
            summary="viewer anchor, source_url, source lane, Qdrant payload를 다시 맞춰야 합니다.",
            evidence=list(diagnostic.get("evidence") or []),
            next_action="Reindex 후 citation smoke 재실행",
        )
    return _repair_action(
        "gold_contract_repair",
        diagnostic=code,
        status="queued",
        title="Gold 계약 blocker 수리",
        summary="진단 결과를 수리 작업으로 전환해야 합니다.",
        evidence=list(diagnostic.get("evidence") or []),
        next_action="원인별 repair action을 명시하고 Gold Build 재실행",
    )


def _apply_synthetic_sections(
    parsed: ParsedUploadDocument,
    chunks: tuple[DocumentChunk, ...],
    *,
    title: str,
) -> tuple[ParsedUploadDocument, tuple[DocumentChunk, ...]]:
    source_anchor = f"upload-{uuid.uuid5(uuid.NAMESPACE_URL, title).hex[:10]}"
    markdown = parsed.markdown
    if markdown and not _HEADING_RE.search(markdown):
        markdown = f"# {title}\n\n{markdown}"
    repaired_chunks = tuple(
        replace(
            chunk,
            section_path=chunk.section_path or (title,),
            heading_title=chunk.heading_title or title,
            source_anchor=chunk.source_anchor or source_anchor,
            toc_path=chunk.toc_path or (title,),
            metadata={
                **dict(chunk.metadata),
                "gold_build_repair": "semantic_section_rebuild",
                "synthetic_section": title,
            },
        )
        for chunk in chunks
    )
    return replace(
        parsed,
        markdown=markdown,
        metadata={
            **dict(parsed.metadata),
            "gold_build_repair": "semantic_section_rebuild",
            "synthetic_section": title,
        },
    ), repaired_chunks


def _diagnostic(code: str, *, severity: str, summary: str, evidence: list[str] | None = None) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "summary": summary,
        "evidence": [item for item in (evidence or []) if str(item).strip()],
    }


def _diagnostic_from_blocker(blocker: str) -> dict[str, Any]:
    code = str(blocker or "").replace("runtime_not_readable::", "").strip()
    summaries = {
        "zero_sections": "section이 없어 reader/wiki 문서로 읽을 수 없습니다.",
        "zero_chunks": "검색과 citation에 사용할 chunk가 없습니다.",
        "non_ko_content": "한국어 운영 문서체가 아닙니다.",
        "mixed_ko_content": "한국어/비한국어 본문이 섞여 있습니다.",
        "language_gate_missing": "한국어 품질 gate evidence가 없습니다.",
        "missing_source_provenance": "원천 출처 evidence가 없습니다.",
        "missing_source_lane": "source lane metadata가 없습니다.",
        "missing_viewer_path": "viewer path가 없습니다.",
        "missing_runtime_artifact": "reader runtime artifact가 없습니다.",
    }
    return _diagnostic(code or "gold_contract_failed", severity="blocking", summary=summaries.get(code, "Gold 계약 blocker가 남아 있습니다."))


def _repair_action(
    action_id: str,
    *,
    diagnostic: str,
    status: str,
    title: str,
    summary: str,
    evidence: list[str] | None = None,
    next_action: str,
) -> dict[str, Any]:
    return {
        "id": action_id,
        "diagnostic": diagnostic,
        "status": status,
        "title": title,
        "summary": summary,
        "evidence": [item for item in (evidence or []) if str(item).strip()],
        "next_action": next_action,
    }


def _stage_results(
    *,
    status: str,
    diagnostics: list[dict[str, Any]],
    repair_actions: list[dict[str, Any]],
    index_result: dict[str, Any] | None,
    metrics: dict[str, Any],
) -> list[dict[str, str]]:
    action_statuses = {str(action.get("status") or "") for action in repair_actions}
    blocking_count = len([item for item in diagnostics if str(item.get("severity") or "") == "blocking"])
    index_ready = _index_evidence_complete(index_result=index_result, metrics=metrics)
    stages: list[dict[str, str]] = []
    for stage in GOLD_BUILD_STAGES:
        stage_status = "pass"
        detail = ""
        if status == "auto_candidate" and stage in {"reindex", "verify", "promote"}:
            stage_status = "pending"
            detail = "dry run 또는 저장 전 후보"
        elif stage == "diagnose":
            stage_status = "pass" if diagnostics else "pass"
            detail = f"{len(diagnostics)} diagnostics"
        elif stage == "repair":
            if {"provider_required", "manual_required", "queued"} & action_statuses:
                stage_status = "pending"
                detail = "repair actions remain"
            else:
                detail = "repairs applied"
        elif stage == "reindex":
            if index_result is None:
                if index_ready:
                    detail = f"{_safe_int(metrics.get('qdrant_indexed_count'))} indexed"
                else:
                    stage_status = "pending"
                    detail = "index evidence pending"
            else:
                indexed_count = _safe_int(index_result.get("indexed_count"))
                candidate_count = _safe_int(index_result.get("candidate_count"))
                if index_ready:
                    detail = f"{indexed_count} indexed"
                else:
                    stage_status = "fail"
                    detail = f"index incomplete: {indexed_count}/{candidate_count}"
        elif stage == "verify":
            if blocking_count:
                stage_status = "fail"
                detail = f"{blocking_count} blockers"
            else:
                detail = "reader/index checks passed"
        elif stage == "promote":
            if status != "gold":
                stage_status = "pending"
                detail = status
            else:
                detail = "Gold"
        stages.append({"stage": stage, "status": stage_status, "detail": detail})
    return stages


def _index_evidence_complete(*, index_result: dict[str, Any] | None, metrics: dict[str, Any]) -> bool:
    chunk_count = _safe_int(metrics.get("chunk_count"))
    if chunk_count <= 0:
        return False
    if index_result is not None:
        indexed_count = _safe_int(index_result.get("indexed_count"))
        status = str(index_result.get("status") or "").strip()
        error = str(index_result.get("error") or "").strip()
        return indexed_count >= chunk_count and status != "deferred" and not error
    if "qdrant_indexed_count" not in metrics:
        return False
    return _safe_int(metrics.get("qdrant_indexed_count")) >= chunk_count


def _gold_evidence(*, status: str, metrics: dict[str, Any], stage_results: list[dict[str, str]]) -> list[str]:
    if status != "gold":
        return []
    evidence = [
        f"sections={_safe_int(metrics.get('section_count'))}",
        f"chunks={_safe_int(metrics.get('chunk_count'))}",
    ]
    if "qdrant_indexed_count" in metrics:
        evidence.append(f"qdrant={_safe_int(metrics.get('qdrant_indexed_count'))}")
    evidence.extend(
        f"{row['stage']}={row['status']}"
        for row in stage_results
        if str(row.get("status") or "") == "pass"
    )
    return evidence


def _current_stage(status: str) -> str:
    if status == "gold":
        return "promote"
    if status == "needs_manual_repair":
        return "repair"
    if status == "repairing":
        return "verify"
    if status == "auto_candidate":
        return "diagnose"
    return "repair"


def _language_profile(texts: list[str]) -> dict[str, Any]:
    cleaned = [str(text or "").strip() for text in texts if str(text or "").strip()]
    if not cleaned:
        return {
            "text_unit_count": 0,
            "hangul_unit_count": 0,
            "latin_only_unit_count": 0,
            "hangul_unit_ratio": 0.0,
            "latin_only_unit_ratio": 0.0,
        }
    hangul_count = sum(1 for text in cleaned if HANGUL_SYLLABLE_RE.search(text))
    latin_only_count = sum(1 for text in cleaned if LATIN_LETTER_RE.search(text) and not HANGUL_SYLLABLE_RE.search(text))
    return {
        "text_unit_count": len(cleaned),
        "hangul_unit_count": hangul_count,
        "latin_only_unit_count": latin_only_count,
        "hangul_unit_ratio": round(hangul_count / len(cleaned), 4),
        "latin_only_unit_ratio": round(latin_only_count / len(cleaned), 4),
    }


def _section_count(chunks: tuple[DocumentChunk, ...]) -> int:
    return len({tuple(chunk.section_path) for chunk in chunks if chunk.section_path})


def _has_poor_readability(markdown: str) -> bool:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", markdown or "") if part.strip()]
    return any(len(paragraph) >= 900 and "\n" not in paragraph for paragraph in paragraphs)


def _has_diagnostic(diagnostics: list[dict[str, Any]], code: str) -> bool:
    return any(str(item.get("code") or "") == code for item in diagnostics)


def _upload_title(parsed: ParsedUploadDocument) -> str:
    for line in (parsed.markdown or "").splitlines():
        match = re.match(r"^\s*#{1,6}\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip()
    stem = re.sub(r"[-_]+", " ", parsed.filename.rsplit(".", 1)[0]).strip()
    return stem or parsed.filename or "Uploaded Document"


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _run_id(prefix: str, key: str) -> str:
    return f"{prefix}-{uuid.uuid5(uuid.NAMESPACE_URL, key or prefix).hex[:16]}"


__all__ = [
    "GOLD_BUILD_SCHEMA",
    "GoldPreparedUpload",
    "build_gold_build_run",
    "build_official_materialize_gold_run",
    "gold_build_contract_from_blockers",
    "prepare_upload_gold_build_candidate",
    "with_index_verification",
]
