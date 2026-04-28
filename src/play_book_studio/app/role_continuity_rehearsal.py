"""Live multi-turn role continuity harness for operator and learner flows."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from play_book_studio.app.chat_matrix_smoke import (
    _git_value,
    _runtime_dependency_failures,
    _runtime_dependency_status,
)
from play_book_studio.app.runtime_report import DEFAULT_PLAYBOOK_UI_BASE_URL


DEFAULT_ROLE_CONTINUITY_SCENARIOS: tuple[dict[str, object], ...] = (
    {
        "role": "operator_a",
        "mode": "ops",
        "acceptance": "10턴 동안 문서 위치 단답/no_answer 없이 절차, 확인, 검증, citation이 유지되어야 한다.",
        "required_terms": ("확인", "검증", "순서", "조치", "체크"),
        "questions": (
            "OpenShift Operator 문제를 처음 만났을 때 무엇부터 봐야 하나?",
            "ClusterOperator가 Degraded=True이면 어떤 순서로 확인하지?",
            "관련 Pod와 이벤트는 어떤 명령으로 확인해야 해?",
            "CSV 상태가 Pending이면 어디를 봐야 하나?",
            "Subscription과 InstallPlan 문제를 구분하는 기준은?",
            "CatalogSource가 문제일 때 확인 순서는?",
            "네임스페이스 권한이나 RBAC 문제 가능성은 어떻게 확인해?",
            "조치 후 정상화 검증은 어떤 신호를 봐야 하나?",
            "운영자에게 보고할 때 핵심 증거를 어떻게 정리하지?",
            "지금까지 절차를 장애 대응 체크리스트로 압축해줘",
        ),
    },
    {
        "role": "learner_b",
        "mode": "learn",
        "acceptance": "10턴 동안 일반 guide/no_answer 없이 개념, 구조, 단계, citation이 유지되어야 한다.",
        "required_terms": ("개념", "학습", "이해", "차이", "구조", "단계"),
        "questions": (
            "OpenShift를 처음 배우는 사람에게 전체 구조를 어떻게 설명하면 좋을까?",
            "Kubernetes와 OpenShift의 차이를 초보자 기준으로 설명해줘",
            "Operator 개념을 왜 쓰는지 학습 순서로 알려줘",
            "ClusterOperator와 일반 Operator는 어떻게 구분해?",
            "OLM, Subscription, CSV, InstallPlan 관계를 예시로 설명해줘",
            "Route와 Ingress 차이를 실무자가 이해하기 쉽게 설명해줘",
            "StorageClass, PVC, PV 흐름을 학습 단계별로 정리해줘",
            "Day-2 운영에서 Observability가 왜 중요한지 알려줘",
            "공식 문서와 고객 운영 자료를 같이 공부할 때 어떤 순서가 좋아?",
            "지금까지 배운 내용을 1주 학습 플랜으로 정리해줘",
        ),
    },
)


def _iso_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _answer_has_any(answer: str, terms: tuple[str, ...]) -> bool:
    return any(term in answer for term in terms)


def _evaluate_turn(payload: dict[str, Any], *, required_terms: tuple[str, ...]) -> dict[str, Any]:
    answer = str(payload.get("answer") or "")
    citations = payload.get("citations") if isinstance(payload.get("citations"), list) else []
    response_kind = str(payload.get("response_kind") or "")
    doc_locator_only = "문서를 여는 것이 맞습니다" in answer and len(answer) < 260
    checks = {
        "response_ok": response_kind != "no_answer",
        "min_answer_length": len(answer) >= 120,
        "min_citations": len(citations) > 0,
        "not_doc_locator_only": not doc_locator_only,
        "role_terms": _answer_has_any(answer, required_terms),
    }
    return {
        "pass": all(checks.values()),
        "checks": checks,
        "response_kind": response_kind,
        "citation_count": len(citations),
        "answer_length": len(answer),
        "answer_preview": answer[:800],
    }


def build_role_continuity_rehearsal(
    root_dir: str | Path,
    *,
    ui_base_url: str = DEFAULT_PLAYBOOK_UI_BASE_URL,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    root = Path(root_dir)
    base_url = ui_base_url.rstrip("/")
    preflight = _runtime_dependency_status(root)
    if not bool(preflight.get("ready")):
        failures = _runtime_dependency_failures(preflight)
        return {
            "generated_at": _iso_timestamp(),
            "branch": _git_value(root, "branch", "--show-current"),
            "head": _git_value(root, "rev-parse", "HEAD"),
            "ui_base_url": base_url,
            "status": "blocked",
            "pass_count": 0,
            "total": sum(len(item["questions"]) for item in DEFAULT_ROLE_CONTINUITY_SCENARIOS),
            "failures": failures,
            "runtime_dependency_preflight": preflight,
            "roles": {},
            "results": [],
        }

    run_id = datetime.now().astimezone().strftime("%Y%m%d%H%M%S")
    results: list[dict[str, Any]] = []
    roles: dict[str, dict[str, int]] = {}
    for scenario in DEFAULT_ROLE_CONTINUITY_SCENARIOS:
        role = str(scenario["role"])
        mode = str(scenario["mode"])
        questions = tuple(str(item) for item in scenario["questions"])
        required_terms = tuple(str(item) for item in scenario["required_terms"])
        session_id = f"role-continuity-{run_id}-{role}"
        roles[role] = {"pass": 0, "total": len(questions)}
        for turn_index, question in enumerate(questions, start=1):
            try:
                response = requests.post(
                    f"{base_url}/api/chat",
                    json={"session_id": session_id, "mode": mode, "query": question},
                    headers={"Content-Type": "application/json"},
                    timeout=timeout_seconds,
                )
                payload = response.json()
                evaluated = _evaluate_turn(payload, required_terms=required_terms)
                status_code = response.status_code
            except Exception as exc:  # noqa: BLE001
                evaluated = {
                    "pass": False,
                    "checks": {"request_ok": False},
                    "error": str(exc),
                    "response_kind": "",
                    "citation_count": 0,
                    "answer_length": 0,
                    "answer_preview": "",
                }
                status_code = 0
            if evaluated["pass"]:
                roles[role]["pass"] += 1
            results.append(
                {
                    "role": role,
                    "mode": mode,
                    "session_id": session_id,
                    "turn": turn_index,
                    "query": question,
                    "status_code": status_code,
                    **evaluated,
                }
            )

    pass_count = sum(1 for item in results if item.get("pass"))
    return {
        "generated_at": _iso_timestamp(),
        "branch": _git_value(root, "branch", "--show-current"),
        "head": _git_value(root, "rev-parse", "HEAD"),
        "ui_base_url": base_url,
        "status": "ok" if pass_count == len(results) else "fail",
        "pass_count": pass_count,
        "total": len(results),
        "runtime_dependency_preflight": preflight,
        "roles": roles,
        "acceptance": {
            str(item["role"]): str(item["acceptance"])
            for item in DEFAULT_ROLE_CONTINUITY_SCENARIOS
        },
        "results": results,
    }


def write_role_continuity_rehearsal(
    root_dir: str | Path,
    *,
    output_path: str | Path | None = None,
    ui_base_url: str = DEFAULT_PLAYBOOK_UI_BASE_URL,
    timeout_seconds: float = 120.0,
) -> tuple[Path, dict[str, Any]]:
    root = Path(root_dir)
    payload = build_role_continuity_rehearsal(
        root,
        ui_base_url=ui_base_url,
        timeout_seconds=timeout_seconds,
    )
    target = (
        Path(output_path).resolve()
        if output_path is not None
        else root / ".kugnusdocs" / "reports" / f"{datetime.now().date().isoformat()}-role-continuity-rehearsal.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target, payload
