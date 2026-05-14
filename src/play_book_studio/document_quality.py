"""Document quality gates for upload Gold promotion."""

from __future__ import annotations

import re
from typing import Any


QUALITY_SCHEMA_VERSION = "llm_wiki.document_quality.v1"

_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_COMMANDISH_LINE_RE = re.compile(
    r"^\s*(?:\$+\s*)?(?:oc|kubectl|helm|podman|docker|python|ansible-playbook|curl)\s+",
    re.IGNORECASE,
)
_YAMLISH_LINE_RE = re.compile(
    r"^\s*(?:apiVersion|kind|metadata|spec|subjects|roleRef|rules|verbs|resources|namespace|name|"
    r"allowHostDirVolumePlugin|allowHostIPC|allowHostNetwork|allowHostPID|allowHostPorts|"
    r"allowPrivilegeEscalation|allowPrivilegedContainer|priority|readOnlyRootFilesystem|"
    r"runAsUser|seLinuxContext|supplementalGroups|serviceAccountName|securityContext|users|groups|volumes):\s*",
)
_PAGE_HEADING_RE = re.compile(r"^\s*#{1,6}\s*Page\s+\d+\s*$", re.IGNORECASE)
_PAGE_FOOTER_RE = re.compile(r"(?m)^[A-Za-z가-힣][A-Za-z가-힣 ._-]{0,31}\n\d{1,4}$")
_BROKEN_BASH_RE = re.compile(
    r"```bash\n(?P<body>.*?)```",
    re.DOTALL,
)
_LATIN_SPLIT_RE = re.compile(r"$^")
_KNOWN_KO_SPLIT_RE = re.compile(
    r"(?:오픈시\s+프트|비활\s+성화|네임스페이\s+스|테스\s+트|인\s+프라|프로젝\s+트|"
    r"쿠버네티\s+스|클러\s+스터|사용\s+자|서비\s+스|권한\s+부\s+여|SA\s+지\s+정|"
    r"설\s+정|금\s+지|공\s+유|우\s+선순위)"
)


def build_document_quality_snapshot(
    document: dict[str, Any],
    *,
    topology: dict[str, Any] | None = None,
    gold_build_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a persisted quality gate snapshot from stored document evidence."""

    chunks = [chunk for chunk in document.get("chunks") or [] if isinstance(chunk, dict)]
    assets = [asset for asset in document.get("assets") or [] if isinstance(asset, dict)]
    markdown = "\n\n".join(str(chunk.get("markdown") or chunk.get("text") or "") for chunk in chunks)
    source_scope = str(document.get("source_scope") or "").strip()
    checks: list[dict[str, Any]] = []

    _append_check(
        checks,
        "chunk_presence",
        "문서 조각 생성",
        "pass" if chunks else "fail",
        "blocking",
        f"{len(chunks)}개 chunk",
        evidence=[f"chunk_count={len(chunks)}"],
    )

    page_stub_count = _page_stub_count(chunks)
    _append_check(
        checks,
        "page_stub",
        "빈 페이지 조각",
        "fail" if page_stub_count else "pass",
        "repair_required",
        f"짧은 Page stub {page_stub_count}개",
        evidence=[f"page_stub_count={page_stub_count}"],
    )

    unfenced_code = _unfenced_code_lines(markdown)
    _append_check(
        checks,
        "code_loss",
        "명령어/YAML code block 보존",
        "fail" if unfenced_code else "pass",
        "repair_required",
        "명령어 또는 YAML이 fence 없이 평문에 섞였습니다." if unfenced_code else "명령어/code block 보존 확인",
        evidence=unfenced_code[:8],
    )

    split_artifacts = _split_text_artifacts(markdown)
    _append_check(
        checks,
        "split_text",
        "단어 깨짐",
        "fail" if len(split_artifacts) >= 5 else "warn" if split_artifacts else "pass",
        "repair_required",
        f"단어 깨짐 후보 {len(split_artifacts)}개",
        evidence=split_artifacts[:10],
    )

    page_footer_noise = _page_footer_noise(markdown)
    _append_check(
        checks,
        "page_footer_noise",
        "페이지 푸터 오염",
        "fail" if page_footer_noise else "pass",
        "repair_required",
        f"본문에 섞인 페이지 푸터 {len(page_footer_noise)}개",
        evidence=page_footer_noise[:8],
    )

    broken_commands = _broken_wrapped_commands(markdown)
    _append_check(
        checks,
        "broken_wrapped_command",
        "페이지 경계 명령어 깨짐",
        "fail" if broken_commands else "pass",
        "repair_required",
        f"페이지/줄바꿈으로 깨진 명령어 {len(broken_commands)}개",
        evidence=broken_commands[:8],
    )

    described_assets = [
        asset
        for asset in assets
        if str(asset.get("qwen_description") or asset.get("caption_text") or asset.get("ocr_text") or "").strip()
    ]
    referenced_asset_ids = {
        str(asset_id)
        for chunk in chunks
        for asset_id in (chunk.get("asset_ids") or [])
        if str(asset_id).strip()
    }
    asset_ids = {str(asset.get("asset_id") or "") for asset in assets if str(asset.get("asset_id") or "").strip()}
    missing_asset_descriptions = max(0, len(assets) - len(described_assets))
    orphaned_assets = sorted(asset_ids - referenced_asset_ids)
    asset_status = "pass"
    if missing_asset_descriptions:
        asset_status = "fail"
    elif assets and orphaned_assets:
        asset_status = "warn"
    _append_check(
        checks,
        "asset_evidence",
        "이미지/asset 근거",
        asset_status,
        "repair_required",
        f"{len(described_assets)}/{len(assets)}개 asset 설명, orphan {len(orphaned_assets)}개",
        evidence=[f"missing_descriptions={missing_asset_descriptions}", *orphaned_assets[:6]],
    )

    topology_status = _topology_status(topology)
    _append_check(
        checks,
        "topology_snapshot",
        "지식망 스냅샷",
        "pass" if topology_status == "ready" else "fail",
        "repair_required",
        "지식망 스냅샷 준비됨" if topology_status == "ready" else "Gold/indexed 상태여도 지식망 스냅샷이 없습니다.",
        evidence=[f"topology_status={topology_status}"],
    )

    failed = [check for check in checks if check["status"] == "fail"]
    warnings = [check for check in checks if check["status"] == "warn"]
    if not chunks:
        state = "blocked"
    elif failed:
        state = "needs_repair"
    else:
        state = "gold_ready"
    score = max(0, 100 - len(failed) * 18 - len(warnings) * 6)
    return {
        "schema_version": QUALITY_SCHEMA_VERSION,
        "document_source_id": str(document.get("document_source_id") or ""),
        "parsed_document_id": str(document.get("parsed_document_id") or ""),
        "state": state,
        "score": score,
        "checks": checks,
        "blockers": failed,
        "warnings": warnings,
        "metadata": {
            "source": "document_quality.build_document_quality_snapshot",
            "source_scope": source_scope,
            "chunk_count": len(chunks),
            "asset_count": len(assets),
            "topology_status": topology_status,
            "gold_build_status": str((gold_build_run or {}).get("status") or ""),
        },
    }


def merge_quality_into_gold_run(gold_build_run: dict[str, Any], quality: dict[str, Any]) -> dict[str, Any]:
    if str(quality.get("state") or "") == "gold_ready":
        return {
            **dict(gold_build_run or {}),
            "quality_snapshot": quality,
        }

    blockers = [
        {
            "code": str(check.get("id") or "quality_gate"),
            "severity": "blocking",
            "summary": str(check.get("summary") or check.get("label") or "품질 gate blocker"),
            "evidence": list(check.get("evidence") or []),
        }
        for check in quality.get("blockers") or []
        if isinstance(check, dict)
    ]
    repair_actions = [
        _quality_repair_action(check)
        for check in quality.get("blockers") or []
        if isinstance(check, dict)
    ]
    quality_codes = {str(item.get("code") or "") for item in blockers}
    quality_action_ids = {str(item.get("id") or "") for item in repair_actions}
    existing_diagnostics = [
        item
        for item in list((gold_build_run or {}).get("diagnostics") or [])
        if str(item.get("code") or "") not in quality_codes
    ]
    existing_repair_actions = [
        item
        for item in list((gold_build_run or {}).get("repair_actions") or [])
        if str(item.get("id") or "") not in quality_action_ids
    ]
    stage_results = list((gold_build_run or {}).get("stage_results") or [])
    for row in stage_results:
        if str(row.get("stage") or "") == "verify":
            row["status"] = "fail"
            row["detail"] = f"quality={quality.get('state')}"
        if str(row.get("stage") or "") == "promote":
            row["status"] = "pending"
            row["detail"] = "quality gate blocked"

    return {
        **dict(gold_build_run or {}),
        "status": "needs_manual_repair",
        "final_grade": "Gold Build Repair",
        "current_stage": "repair",
        "diagnostics": [*existing_diagnostics, *blockers],
        "repair_actions": [*existing_repair_actions, *repair_actions],
        "stage_results": stage_results,
        "blocking_message": _quality_blocking_message(quality),
        "manual_repair_needed": True,
        "quality_snapshot": quality,
        "gold_evidence": [],
    }


def _append_check(
    checks: list[dict[str, Any]],
    check_id: str,
    label: str,
    status: str,
    severity: str,
    summary: str,
    *,
    evidence: list[str] | None = None,
) -> None:
    checks.append(
        {
            "id": check_id,
            "label": label,
            "status": status,
            "severity": severity,
            "summary": summary,
            "evidence": [item for item in (evidence or []) if str(item).strip()],
        }
    )


def _page_stub_count(chunks: list[dict[str, Any]]) -> int:
    count = 0
    for chunk in chunks:
        markdown = str(chunk.get("markdown") or "").strip()
        heading = str(chunk.get("heading_title") or "").strip()
        token_count = int(chunk.get("token_count") or len(markdown.split()))
        if token_count <= 15 and (_PAGE_HEADING_RE.match(markdown) or re.match(r"^Page\s+\d+$", heading, re.I)):
            count += 1
    return count


def _unfenced_code_lines(markdown: str) -> list[str]:
    lines: list[str] = []
    in_fence = False
    for raw_line in str(markdown or "").splitlines():
        if _FENCE_RE.match(raw_line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        line = raw_line.strip()
        if not line:
            continue
        if _COMMANDISH_LINE_RE.match(line) or _YAMLISH_LINE_RE.match(line):
            lines.append(line[:180])
    return lines


def _split_text_artifacts(markdown: str) -> list[str]:
    candidates = set()
    for match in _KNOWN_KO_SPLIT_RE.finditer(markdown or ""):
        candidates.add(match.group(0))
    for match in _LATIN_SPLIT_RE.finditer(markdown or ""):
        candidates.add(match.group(0))
    return sorted(candidates)


def _page_footer_noise(markdown: str) -> list[str]:
    candidates = set()
    for match in _PAGE_FOOTER_RE.finditer(markdown or ""):
        text = match.group(0).strip()
        label = text.splitlines()[0].strip()
        if label and ":" not in label and not label.startswith("#"):
            candidates.add(text.replace("\n", " "))
    return sorted(candidates)


def _broken_wrapped_commands(markdown: str) -> list[str]:
    candidates: set[str] = set()
    for match in _BROKEN_BASH_RE.finditer(markdown or ""):
        body = match.group("body")
        lines = [line.rstrip() for line in body.splitlines() if line.strip()]
        if not lines:
            continue
        last = lines[-1].strip()
        if re.search(r"\s(?:-n|--namespace)$", last) or re.search(r"\b[A-Za-z0-9_-]{3,}-$", last):
            candidates.add(last[:180])
        if re.search(r"\b[A-Za-z0-9_-]{3,}-[A-Za-z]{1,4}$", last):
            candidates.add(last[:180])
    outside_fence = re.sub(r"```.*?```", "", markdown or "", flags=re.DOTALL)
    for match in re.finditer(r"(?m)^[A-Za-z]{1,4}$", outside_fence):
        fragment = match.group(0)
        if fragment.lower() in {"ct", "ject", "tion"}:
            candidates.add(f"orphan_fragment={fragment}")
    return sorted(candidates)


def _topology_status(topology: dict[str, Any] | None) -> str:
    if not topology:
        return "missing"
    metadata = topology.get("metadata") if isinstance(topology.get("metadata"), dict) else {}
    summary = topology.get("summary") if isinstance(topology.get("summary"), dict) else {}
    storage = str(metadata.get("storage") or "").lower()
    state = str(topology.get("state") or summary.get("state") or "").lower()
    if storage == "postgres" and state == "ready":
        return "ready"
    if str(topology.get("status") or "").lower() in {"deferred", "failed"}:
        return str(topology.get("status")).lower()
    return state or storage or "missing"


def _quality_blocking_message(quality: dict[str, Any]) -> str:
    blockers = quality.get("blockers") if isinstance(quality.get("blockers"), list) else []
    labels = [str(item.get("label") or item.get("id") or "").strip() for item in blockers if isinstance(item, dict)]
    labels = [label for label in labels if label]
    if not labels:
        return "품질 판정서를 통과하지 못해 Gold 승급이 보류되었습니다."
    return "품질 판정서 보류: " + " · ".join(labels[:4])


def _quality_repair_action(check: dict[str, Any]) -> dict[str, Any]:
    check_id = str(check.get("id") or "quality_gate")
    next_action = "품질 재검사 API로 수리 결과를 다시 확인"
    if check_id == "page_stub":
        next_action = "빈 페이지 표식을 제거하고 chunk, Qdrant 색인, 지식망, 품질 판정을 다시 생성"
    elif check_id == "code_loss":
        next_action = "코드블록 자동 수리 후 chunk, Qdrant 색인, 지식망, 품질 판정을 다시 생성"
    elif check_id in {"page_footer_noise", "broken_wrapped_command", "split_text"}:
        next_action = "PDF 텍스트 오염을 정리한 뒤 코드블록, chunk, Qdrant 색인, 지식망, 품질 판정을 다시 생성"
    return {
        "id": f"quality_{check_id}",
        "diagnostic": check_id,
        "status": "queued",
        "title": str(check.get("label") or "품질 gate 수리"),
        "summary": str(check.get("summary") or "Gold 승급 전에 품질 gate를 통과해야 합니다."),
        "evidence": list(check.get("evidence") or []),
        "next_action": next_action,
    }


__all__ = [
    "QUALITY_SCHEMA_VERSION",
    "build_document_quality_snapshot",
    "merge_quality_into_gold_run",
]
