from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from play_book_studio.app.runtime_report import DEFAULT_PLAYBOOK_UI_BASE_URL


HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")
ANSWER_PREFIX_RE = re.compile(r"^\s*답변:")
INLINE_CITATION_RE = re.compile(r"\[\d+\]")
NO_EVIDENCE_RE = re.compile(
    r"(근거에 .*없습니다|근거가 없습니다|정보가 없습니다|답변할 수 없습니다|답할 수 없습니다|찾을 수 없습니다|포함되어 있지 않습니다)"
)

DEFAULT_CHAT_MATRIX_CASES: tuple[dict[str, Any], ...] = (
    {
        "id": "default_customer_cicd",
        "query": "고객 문서 기준 CI/CD 운영 구조를 신규 운영자에게 설명해줘",
        "payload": {"restrict_uploaded_sources": True},
        "expected_collections": ["uploaded"],
        "expected_book_slugs": ["customer-master-kmsc-ocp-operations-playbook"],
        "allow_no_evidence_phrase": False,
    },
    {
        "id": "selected_customer_architecture",
        "query": "고객 운영북 기준 목표 아키텍처와 OCP 구성 핵심을 공식문서와 같이 설명해줘",
        "payload": {
            "selected_draft_ids": ["customer-master-kmsc-ocp-operations-playbook"],
            "restrict_uploaded_sources": False,
        },
        "expected_collections": ["uploaded", "core"],
        "expected_book_slugs": ["customer-master-kmsc-ocp-operations-playbook"],
        "require_llm_runtime": True,
        "require_vector_runtime": True,
        "allow_no_evidence_phrase": False,
    },
    {
        "id": "official_buildconfig",
        "query": "OCP 4.20에서 BuildConfig 운영자가 먼저 확인할 점과 예시 명령을 알려줘",
        "payload": {"restrict_uploaded_sources": False},
        "expected_collections": ["core"],
        "expected_book_slugs": ["builds_using_buildconfig"],
        "require_code_block": True,
        "must_include_terms": ["BuildConfig", "oc"],
        "allow_no_evidence_phrase": False,
    },
    {
        "id": "default_blended_cicd_buildconfig",
        "query": "고객 CI/CD 운영 자료와 OCP 4.20 BuildConfig 공식문서를 같이 참고해서 점검 순서를 알려줘",
        "payload": {"restrict_uploaded_sources": False},
        "expected_collections": ["uploaded", "core"],
        "expected_book_slugs_any": [
            "customer-master-kmsc-ocp-operations-playbook",
            "builds_using_buildconfig",
        ],
        "require_code_block": True,
        "must_include_terms": ["BuildConfig"],
        "allow_no_evidence_phrase": False,
    },
    {
        "id": "selected_blended_router",
        "query": "고객 OCP 운영 설계서와 공식 문서를 같이 참고해서 Router 구성을 설명해줘",
        "payload": {
            "selected_draft_ids": ["customer-master-kmsc-ocp-operations-playbook"],
            "restrict_uploaded_sources": False,
        },
        "expected_collections": ["uploaded", "core"],
        "expected_book_slugs": ["customer-master-kmsc-ocp-operations-playbook"],
        "allow_no_evidence_phrase": True,
    },
    {
        "id": "default_blended_training_day",
        "query": "신규 운영자 교육 하루 코스를 고객 운영북과 OCP 4.20 공식문서 기준으로 짜줘",
        "payload": {"restrict_uploaded_sources": False},
        "expected_collections": ["uploaded", "core"],
        "require_llm_runtime": True,
        "require_vector_runtime": True,
        "allow_no_evidence_phrase": False,
    },
)


def _iso_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _git_value(root_dir: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root_dir,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:  # noqa: BLE001
        return ""
    return result.stdout.strip()


def _read_cases(cases_path: str | Path | None) -> list[dict[str, Any]]:
    if cases_path is None:
        return [dict(item) for item in DEFAULT_CHAT_MATRIX_CASES]
    path = Path(cases_path)
    cases: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        cases.append(json.loads(line))
    return cases


def _safe_json(response: requests.Response) -> dict[str, Any] | str:
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001
        return response.text[:2000]
    if isinstance(payload, dict):
        return payload
    return str(payload)[:2000]


def _citation_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    citations = payload.get("citations")
    if not isinstance(citations, list):
        return []
    return [item for item in citations if isinstance(item, dict)]


def _cited_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    citations = _citation_rows(payload)
    cited_indices = {
        int(index)
        for index in payload.get("cited_indices", [])
        if isinstance(index, int) or str(index).isdigit()
    }
    if not cited_indices:
        return []
    return [
        item
        for item in citations
        if int(item.get("index") or 0) in cited_indices
    ]


def _extract_retrieval_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    trace = payload.get("retrieval_trace")
    if not isinstance(trace, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key in (
        "selected",
        "final",
        "reranked",
        "hybrid",
        "hits",
        "bm25",
        "vector",
    ):
        value = trace.get(key)
        if isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, dict))
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        identity = str(row.get("chunk_id") or row.get("id") or row)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(row)
        if len(unique) >= 10:
            break
    return unique


def _has_expected_books(
    *,
    cited_books: set[str],
    case: dict[str, Any],
) -> bool:
    expected_all = {
        str(item).strip()
        for item in case.get("expected_book_slugs", [])
        if str(item).strip()
    }
    expected_any = {
        str(item).strip()
        for item in case.get("expected_book_slugs_any", [])
        if str(item).strip()
    }
    if expected_all and not expected_all.issubset(cited_books):
        return False
    if expected_any and not (expected_any & cited_books):
        return False
    return True


def _extract_llm_runtime(payload: dict[str, Any]) -> dict[str, Any]:
    pipeline_trace = payload.get("pipeline_trace")
    if isinstance(pipeline_trace, dict) and isinstance(pipeline_trace.get("llm"), dict):
        return dict(pipeline_trace["llm"])
    runtime = payload.get("runtime")
    if isinstance(runtime, dict) and isinstance(runtime.get("llm"), dict):
        return dict(runtime["llm"])
    return {}


def _extract_vector_runtime(payload: dict[str, Any]) -> dict[str, Any]:
    retrieval_trace = payload.get("retrieval_trace")
    if isinstance(retrieval_trace, dict) and isinstance(retrieval_trace.get("vector_runtime"), dict):
        return dict(retrieval_trace["vector_runtime"])
    runtime = payload.get("runtime")
    if isinstance(runtime, dict) and isinstance(runtime.get("vector_runtime"), dict):
        return dict(runtime["vector_runtime"])
    return {}


def _runtime_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _llm_runtime_live(payload: dict[str, Any], case: dict[str, Any]) -> bool:
    if not case.get("require_llm_runtime", False):
        return True
    runtime = _extract_llm_runtime(payload)
    provider = str(runtime.get("last_provider") or "").strip()
    expected_provider = str(case.get("expected_llm_provider") or "openai-compatible").strip()
    provider_ok = provider == expected_provider if expected_provider else bool(provider)
    return (
        provider_ok
        and not bool(runtime.get("last_fallback_used", False))
        and _runtime_float(runtime.get("provider_round_trip_ms")) > 0
    )


def _vector_runtime_live(payload: dict[str, Any], case: dict[str, Any]) -> bool:
    if not case.get("require_vector_runtime", False):
        return True
    runtime = _extract_vector_runtime(payload)
    endpoints_used = [
        str(item).strip()
        for item in (runtime.get("endpoints_used") or [])
        if str(item).strip()
    ]
    endpoint_used = str(runtime.get("endpoint_used") or "").strip()
    subquery_count = int(runtime.get("subquery_count") or len(runtime.get("subqueries") or []) or 0)
    empty_subqueries = int(runtime.get("empty_subqueries") or 0)
    return bool(endpoints_used or endpoint_used) and subquery_count > 0 and empty_subqueries < subquery_count


def _llm_runtime_summary(payload: dict[str, Any]) -> dict[str, Any]:
    runtime = _extract_llm_runtime(payload)
    return {
        "provider": str(runtime.get("last_provider") or "").strip(),
        "fallback_used": bool(runtime.get("last_fallback_used", False)),
        "provider_round_trip_ms": runtime.get("provider_round_trip_ms"),
        "requested_max_tokens": runtime.get("requested_max_tokens")
        or runtime.get("last_requested_max_tokens"),
    }


def _vector_runtime_summary(payload: dict[str, Any]) -> dict[str, Any]:
    runtime = _extract_vector_runtime(payload)
    return {
        "endpoint_used": str(runtime.get("endpoint_used") or "").strip(),
        "endpoints_used": [
            str(item).strip()
            for item in (runtime.get("endpoints_used") or [])
            if str(item).strip()
        ],
        "subquery_count": int(runtime.get("subquery_count") or len(runtime.get("subqueries") or []) or 0),
        "empty_subqueries": int(runtime.get("empty_subqueries") or 0),
    }


def _suggested_queries(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("suggested_queries")
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _suggested_followups(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("suggested_followups")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict) and str(item.get("query") or "").strip()]


def _followup_dimensions(payload: dict[str, Any]) -> set[str]:
    return {
        str(item.get("dimension") or "").strip()
        for item in _suggested_followups(payload)
        if str(item.get("dimension") or "").strip()
    }


def _case_requires_suggestions(case: dict[str, Any]) -> bool:
    if "require_suggested_queries" in case:
        return bool(case.get("require_suggested_queries"))
    return str(case.get("response_kind", "rag")) == "rag"


def _case_requires_structured_followups(case: dict[str, Any]) -> bool:
    if "require_structured_followups" in case:
        return bool(case.get("require_structured_followups"))
    return _case_requires_suggestions(case)


def _structured_followups_ok(payload: dict[str, Any], case: dict[str, Any]) -> bool:
    if not _case_requires_structured_followups(case):
        return True
    followups = _suggested_followups(payload)
    if len(followups) < int(case.get("min_suggested_queries", 3)):
        return False
    required_dimensions = {
        str(item).strip()
        for item in case.get("required_followup_dimensions", ["next_action", "verify", "branch"])
        if str(item).strip()
    }
    dimensions = _followup_dimensions(payload)
    return required_dimensions.issubset(dimensions)


def _evaluate_payload(
    *,
    case: dict[str, Any],
    status_code: int,
    payload: dict[str, Any] | str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "pass": False,
            "status": "non_json_response",
            "checks": {"http_ok": status_code < 400, "json_payload": False},
            "response_preview": str(payload)[:1000],
        }

    answer = str(payload.get("answer") or "")
    citations = _citation_rows(payload)
    cited_rows = _cited_rows(payload)
    citation_source_collections = {
        str(item.get("source_collection") or "").strip()
        for item in cited_rows
        if str(item.get("source_collection") or "").strip()
    }
    cited_books = {
        str(item.get("book_slug") or "").strip()
        for item in cited_rows
        if str(item.get("book_slug") or "").strip()
    }
    expected_collections = {
        str(item).strip()
        for item in case.get("expected_collections", [])
        if str(item).strip()
    }
    must_include_terms = [
        str(item).strip()
        for item in case.get("must_include_terms", [])
        if str(item).strip()
    ]
    missing_terms = [
        term
        for term in must_include_terms
        if term.lower() not in answer.lower()
    ]
    suggested_queries = _suggested_queries(payload)
    suggested_followups = _suggested_followups(payload)
    min_suggested_queries = int(case.get("min_suggested_queries", 3))
    checks = {
        "http_ok": status_code < 400,
        "response_kind_rag": str(payload.get("response_kind") or "") == str(case.get("response_kind", "rag")),
        "has_answer": bool(answer.strip()),
        "has_korean": bool(HANGUL_RE.search(answer)) if case.get("require_korean", True) else True,
        "answer_prefix": bool(ANSWER_PREFIX_RE.search(answer)) if case.get("require_answer_prefix", True) else True,
        "inline_citation": bool(payload.get("cited_indices")) or bool(INLINE_CITATION_RE.search(answer)),
        "citation_indices_valid": all(
            1 <= int(index) <= len(citations)
            for index in payload.get("cited_indices", [])
            if isinstance(index, int) or str(index).isdigit()
        ),
        "expected_collections": expected_collections.issubset(citation_source_collections),
        "expected_books": _has_expected_books(cited_books=cited_books, case=case),
        "warning_free": not payload.get("warnings"),
        "code_block": ("```" in answer) if case.get("require_code_block", False) else True,
        "must_include_terms": not missing_terms,
        "no_missing_evidence_phrase": (
            True
            if case.get("allow_no_evidence_phrase", False)
            else not NO_EVIDENCE_RE.search(answer)
        ),
        "suggested_queries_present": (
            len(suggested_queries) >= min_suggested_queries
            if _case_requires_suggestions(case)
            else True
        ),
        "structured_followups": _structured_followups_ok(payload, case),
        "llm_runtime_live": _llm_runtime_live(payload, case),
        "vector_runtime_live": _vector_runtime_live(payload, case),
    }
    passed = all(bool(value) for value in checks.values())
    retrieval_rows = _extract_retrieval_rows(payload)
    return {
        "pass": passed,
        "status": "ok" if passed else "fail",
        "checks": checks,
        "response_kind": str(payload.get("response_kind") or ""),
        "collections": sorted(citation_source_collections),
        "books": sorted(cited_books),
        "cited_indices": list(payload.get("cited_indices", [])),
        "warnings": list(payload.get("warnings") or []),
        "missing_terms": missing_terms,
        "answer_preview": answer[:1200],
        "suggested_queries": suggested_queries,
        "suggested_followups": suggested_followups,
        "suggested_dimensions": sorted(_followup_dimensions(payload)),
        "citation_count": len(citations),
        "llm_runtime": _llm_runtime_summary(payload),
        "vector_runtime": _vector_runtime_summary(payload),
        "retrieval_top": [
            {
                "chunk_id": row.get("chunk_id") or row.get("id"),
                "book_slug": row.get("book_slug"),
                "section": row.get("section") or row.get("chapter"),
                "score": row.get("score") or row.get("fused_score") or row.get("raw_score"),
            }
            for row in retrieval_rows[:5]
        ],
    }


def build_chat_matrix_smoke(
    root_dir: str | Path,
    *,
    ui_base_url: str = DEFAULT_PLAYBOOK_UI_BASE_URL,
    cases_path: str | Path | None = None,
    timeout_seconds: float = 90.0,
) -> dict[str, Any]:
    root = Path(root_dir)
    base_url = ui_base_url.rstrip("/")
    cases = _read_cases(cases_path)
    run_id = datetime.now().astimezone().strftime("%Y%m%d%H%M%S")
    results: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        request_payload = dict(case.get("payload") or {})
        request_payload["query"] = str(case.get("query") or "").strip()
        request_payload.setdefault("session_id", f"chat-matrix-smoke-{run_id}-{case.get('id') or index}")
        try:
            response = requests.post(
                f"{base_url}/api/chat",
                json=request_payload,
                headers={"Content-Type": "application/json"},
                timeout=timeout_seconds,
            )
            payload = _safe_json(response)
            evaluated = _evaluate_payload(
                case=case,
                status_code=response.status_code,
                payload=payload,
            )
            status_code = response.status_code
        except Exception as exc:  # noqa: BLE001
            evaluated = {
                "pass": False,
                "status": "request_error",
                "checks": {"request_ok": False},
                "error": str(exc),
            }
            status_code = 0
        results.append(
            {
                "id": str(case.get("id") or index),
                "query": str(case.get("query") or ""),
                "status_code": status_code,
                **evaluated,
            }
        )

    pass_count = sum(1 for item in results if item.get("pass"))
    llm_required_ids = {
        str(case.get("id") or index)
        for index, case in enumerate(cases, start=1)
        if bool(case.get("require_llm_runtime", False))
    }
    vector_required_ids = {
        str(case.get("id") or index)
        for index, case in enumerate(cases, start=1)
        if bool(case.get("require_vector_runtime", False))
    }
    llm_required = [
        item
        for item in results
        if str(item.get("id") or "") in llm_required_ids
        and bool((item.get("checks") or {}).get("llm_runtime_live"))
    ]
    vector_required = [
        item
        for item in results
        if str(item.get("id") or "") in vector_required_ids
        and bool((item.get("checks") or {}).get("vector_runtime_live"))
    ]
    return {
        "generated_at": _iso_timestamp(),
        "branch": _git_value(root, "branch", "--show-current"),
        "head": _git_value(root, "rev-parse", "HEAD"),
        "ui_base_url": base_url,
        "cases_path": str(cases_path or ""),
        "pass_count": pass_count,
        "total": len(results),
        "runtime_requirements": {
            "llm_live_pass_count": len(llm_required),
            "llm_live_total": len(llm_required_ids),
            "vector_live_pass_count": len(vector_required),
            "vector_live_total": len(vector_required_ids),
        },
        "status": "ok" if pass_count == len(results) else "fail",
        "results": results,
    }


def write_chat_matrix_smoke(
    root_dir: str | Path,
    *,
    output_path: str | Path | None = None,
    ui_base_url: str = DEFAULT_PLAYBOOK_UI_BASE_URL,
    cases_path: str | Path | None = None,
    timeout_seconds: float = 90.0,
) -> tuple[Path, dict[str, Any]]:
    root = Path(root_dir)
    payload = build_chat_matrix_smoke(
        root,
        ui_base_url=ui_base_url,
        cases_path=cases_path,
        timeout_seconds=timeout_seconds,
    )
    target = (
        Path(output_path).resolve()
        if output_path is not None
        else root / ".kugnusdocs" / "reports" / f"{datetime.now().date().isoformat()}-official-customer-chat-api-matrix.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target, payload
