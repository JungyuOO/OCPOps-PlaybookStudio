# Retrieval 파이프라인 재설계 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** per-query 하드코딩 규칙 스택을 제거하고, hybrid(BM25+벡터) recall-first 경로 + eval 기반 측정으로 retrieval 계층을 교체한다.

**Architecture:** stage-1 hybrid 검색(BM25 top-40 ‖ 벡터 top-40 → RRF → top-8)이 recall을 책임지고, 리랭커는 `RERANKER_ENABLED` 플래그 뒤의 선택적 재정렬 단계로 둔다. eval 하니스(eval셋 + recall 프로브)를 먼저 만들어 모든 변경을 측정으로 검증한다.

**Tech Stack:** Python 3, pytest, Qdrant(HTTP), 원격 임베딩/리랭커 서버, BM25 인메모리 인덱스.

설계 문서: `docs/superpowers/specs/2026-05-18-retrieval-pipeline-redesign-design.md`

---

## Phase 1 — eval 하니스 (측정 도구를 먼저 만든다)

### Task 1: eval셋 시드 파일

**Files:**
- Create: `tests/eval/retrieval_eval_set.jsonl`

- [ ] **Step 1: eval셋 파일 작성**

각 줄이 하나의 케이스. 알려진 실패 질문 + 실제 OCP 운영자 말투 질문으로 시드한다.
최소 시드(이후 30~50개로 확장):

```jsonl
{"id": "ocp-login", "query": "ocp 로그인 어떻게 함", "expect_command": "oc login", "note": "알려진 실패"}
{"id": "pdb-all-ns", "query": "모든 프로젝트에서 pod 중단 예산 확인 어떻게해?", "expect_section_contains": "중단 예산", "expect_command": "oc get poddisruptionbudget", "note": "알려진 실패"}
{"id": "node-status", "query": "노드 상태 어디서 봐", "expect_command": "oc get nodes"}
{"id": "namespace-list", "query": "네임스페이스 목록 보는 명령어", "expect_command": "oc get"}
{"id": "pvc-pending", "query": "pvc가 pending인데 뭐 확인해", "expect_section_contains": "PVC"}
{"id": "etcd-backup", "query": "etcd 백업 어떻게 해", "expect_command": "cluster-backup.sh"}
{"id": "clusteroperator-degraded", "query": "클러스터 오퍼레이터 degraded 확인", "expect_command": "oc get clusteroperators"}
{"id": "must-gather", "query": "장애 분석 자료 어떻게 모아", "expect_command": "oc adm must-gather"}
{"id": "pod-logs", "query": "파드 로그 보는 법", "expect_command": "oc logs"}
{"id": "csr-approve", "query": "csr 승인 명령어", "expect_command": "oc adm certificate approve"}
```

매칭 규칙(Task 2에서 구현): 케이스는 다음 중 하나라도 만족하면 PASS.
- `expect_chunk_ids` 가 있고 hit.chunk_id 가 그 안에 있음
- `expect_book` 이 있고 hit.book_slug 일치 (+ `expect_section_contains` 가 있으면 hit.section 에 포함)
- `expect_command` 가 있고 hit.cli_commands 중 하나 또는 hit.text 에 그 문자열 포함
- `expect_section_contains` 단독이면 hit.section 에 포함

- [ ] **Step 2: 파일이 유효한 JSONL인지 확인**

Run: `python -c "import json; [json.loads(l) for l in open('tests/eval/retrieval_eval_set.jsonl', encoding='utf-8') if l.strip()]; print('ok')"`
Expected: `ok`

- [ ] **Step 3: 커밋**

```bash
git add tests/eval/retrieval_eval_set.jsonl
git commit -m "test: retrieval eval 시드셋 추가"
```

---

### Task 2: recall 프로브 — 매칭 + 단일 케이스 측정

**Files:**
- Create: `src/play_book_studio/evals/recall_probe.py`
- Test: `tests/test_recall_probe.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_recall_probe.py
from play_book_studio.evals.recall_probe import hit_matches_case, rank_in_hits
from play_book_studio.retrieval.models import RetrievalHit


def _hit(chunk_id, *, book_slug="nodes", section="", cli_commands=(), text=""):
    return RetrievalHit(
        chunk_id=chunk_id, book_slug=book_slug, chapter="", section=section,
        anchor="", source_url="", viewer_path="", text=text, source="bm25",
        raw_score=1.0, cli_commands=tuple(cli_commands),
    )


def test_hit_matches_case_by_command():
    case = {"expect_command": "oc get poddisruptionbudget"}
    assert hit_matches_case(_hit("c1", cli_commands=("oc get poddisruptionbudget --all-namespaces",)), case)
    assert not hit_matches_case(_hit("c2", cli_commands=("oc get pods",)), case)


def test_hit_matches_case_by_section_contains():
    case = {"expect_section_contains": "중단 예산"}
    assert hit_matches_case(_hit("c1", section="Pod 중단 예산"), case)
    assert not hit_matches_case(_hit("c2", section="노드 상태"), case)


def test_rank_in_hits_returns_one_based_rank_or_none():
    case = {"expect_command": "oc get nodes"}
    hits = [_hit("a"), _hit("b", cli_commands=("oc get nodes",)), _hit("c")]
    assert rank_in_hits(hits, case) == 2
    assert rank_in_hits([_hit("x")], case) is None
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_recall_probe.py -v`
Expected: FAIL — `ModuleNotFoundError: play_book_studio.evals.recall_probe`

- [ ] **Step 3: 최소 구현**

```python
# src/play_book_studio/evals/recall_probe.py
"""Stage-1 hybrid recall 측정 프로브. answerer/LLM 없이 검색 단계만 평가한다."""
from __future__ import annotations

from play_book_studio.retrieval.models import RetrievalHit


def hit_matches_case(hit: RetrievalHit, case: dict) -> bool:
    """hit이 케이스의 기대 정답에 해당하면 True."""
    expect_chunk_ids = {str(c) for c in case.get("expect_chunk_ids", []) if str(c)}
    if expect_chunk_ids and hit.chunk_id in expect_chunk_ids:
        return True

    expect_book = str(case.get("expect_book", "")).strip()
    section_needle = str(case.get("expect_section_contains", "")).strip()
    if expect_book:
        if hit.book_slug == expect_book and (not section_needle or section_needle in hit.section):
            return True

    command_needle = str(case.get("expect_command", "")).strip()
    if command_needle:
        if any(command_needle in cmd for cmd in hit.cli_commands):
            return True
        if command_needle in hit.text:
            return True

    if section_needle and not expect_book:
        if section_needle in hit.section:
            return True

    return False


def rank_in_hits(hits: list[RetrievalHit], case: dict) -> int | None:
    """케이스에 매칭되는 첫 hit의 1-based 순위. 없으면 None."""
    for index, hit in enumerate(hits, start=1):
        if hit_matches_case(hit, case):
            return index
    return None
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_recall_probe.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/play_book_studio/evals/recall_probe.py tests/test_recall_probe.py
git commit -m "test: recall 프로브 매칭/순위 helper 추가"
```

---

### Task 3: recall 프로브 — 단계별 검색 실행

**Files:**
- Modify: `src/play_book_studio/evals/recall_probe.py`
- Test: `tests/test_recall_probe.py`

- [ ] **Step 1: 실패 테스트 추가**

`tests/test_recall_probe.py` 끝에 추가:

```python
from play_book_studio.evals.recall_probe import probe_case


class _FakeBM25:
    def __init__(self, hits): self._hits = hits
    def search(self, query, top_k=10): return self._hits[:top_k]


class _FakeVector:
    def __init__(self, hits): self._hits = hits
    def search(self, query, top_k=10, query_filter=None): return self._hits[:top_k]


def test_probe_case_reports_per_stage_ranks():
    target = _hit("pdb", section="Pod 중단 예산", cli_commands=("oc get poddisruptionbudget",))
    noise = _hit("noise", section="기타")
    case = {"id": "pdb", "query": "pod 중단 예산", "expect_command": "oc get poddisruptionbudget"}

    result = probe_case(
        bm25_index=_FakeBM25([noise, target]),
        vector_retriever=_FakeVector([target, noise]),
        case=case,
        candidate_k=40,
    )

    assert result["bm25_rank"] == 2
    assert result["vector_rank"] == 1
    assert result["rrf_rank"] == 1
    assert result["pass_at_8"] is True
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_recall_probe.py::test_probe_case_reports_per_stage_ranks -v`
Expected: FAIL — `ImportError: cannot import name 'probe_case'`

- [ ] **Step 3: 구현 추가**

`recall_probe.py` 에 추가 (상단 import 에 RRF 추가):

```python
from play_book_studio.retrieval.ranking import rrf_merge_named_hit_lists


def probe_case(*, bm25_index, vector_retriever, case: dict, candidate_k: int = 40) -> dict:
    """한 케이스를 stage-1 hybrid만 태워 단계별 순위를 보고한다."""
    query = str(case.get("query", ""))

    bm25_hits = bm25_index.search(query, top_k=candidate_k) if bm25_index else []
    vector_hits = []
    if vector_retriever is not None:
        try:
            vector_hits = vector_retriever.search(query, top_k=candidate_k)
        except Exception as exc:  # noqa: BLE001
            vector_hits = []
            case = {**case, "_vector_error": str(exc)}

    rrf_hits = rrf_merge_named_hit_lists(
        {"bm25": bm25_hits, "vector": vector_hits},
        source_name="hybrid",
        top_k=candidate_k,
    )

    bm25_rank = rank_in_hits(bm25_hits, case)
    vector_rank = rank_in_hits(vector_hits, case)
    rrf_rank = rank_in_hits(rrf_hits, case)

    return {
        "id": case.get("id"),
        "query": query,
        "bm25_rank": bm25_rank,
        "vector_rank": vector_rank,
        "rrf_rank": rrf_rank,
        "pass_at_8": rrf_rank is not None and rrf_rank <= 8,
        "pass_at_20": rrf_rank is not None and rrf_rank <= 20,
        "vector_error": case.get("_vector_error", ""),
    }
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_recall_probe.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/play_book_studio/evals/recall_probe.py tests/test_recall_probe.py
git commit -m "test: recall 프로브 단계별 검색 실행 추가"
```

---

### Task 4: recall 프로브 CLI + baseline 측정

**Files:**
- Create: `scripts/run_recall_probe.py`
- Modify: `src/play_book_studio/evals/recall_probe.py`

- [ ] **Step 1: 집계 함수 테스트 추가**

`tests/test_recall_probe.py` 끝에 추가:

```python
from play_book_studio.evals.recall_probe import summarize_probe_results


def test_summarize_probe_results_computes_recall_at_k():
    results = [
        {"id": "a", "rrf_rank": 1, "pass_at_8": True, "pass_at_20": True},
        {"id": "b", "rrf_rank": 12, "pass_at_8": False, "pass_at_20": True},
        {"id": "c", "rrf_rank": None, "pass_at_8": False, "pass_at_20": False},
    ]
    summary = summarize_probe_results(results)
    assert summary["case_count"] == 3
    assert summary["recall_at_8"] == round(1 / 3, 4)
    assert summary["recall_at_20"] == round(2 / 3, 4)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_recall_probe.py::test_summarize_probe_results_computes_recall_at_k -v`
Expected: FAIL — `ImportError: cannot import name 'summarize_probe_results'`

- [ ] **Step 3: 집계 함수 구현**

`recall_probe.py` 에 추가:

```python
def summarize_probe_results(results: list[dict]) -> dict:
    total = len(results)
    if total == 0:
        return {"case_count": 0, "recall_at_8": 0.0, "recall_at_20": 0.0, "mrr": 0.0}
    pass8 = sum(1 for r in results if r.get("pass_at_8"))
    pass20 = sum(1 for r in results if r.get("pass_at_20"))
    mrr = sum(1.0 / r["rrf_rank"] for r in results if r.get("rrf_rank")) / total
    return {
        "case_count": total,
        "recall_at_8": round(pass8 / total, 4),
        "recall_at_20": round(pass20 / total, 4),
        "mrr": round(mrr, 4),
        "fail_ids": [r.get("id") for r in results if not r.get("pass_at_8")],
    }
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_recall_probe.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: CLI 스크립트 작성**

```python
# scripts/run_recall_probe.py
"""eval셋을 stage-1 hybrid에 태워 단계별 recall 표를 출력한다.

사용: python scripts/run_recall_probe.py
"""
from __future__ import annotations

import json
from pathlib import Path

from play_book_studio.config.settings import load_settings
from play_book_studio.evals.recall_probe import probe_case, summarize_probe_results
from play_book_studio.retrieval.retriever import ChatRetriever

EVAL_SET = Path("tests/eval/retrieval_eval_set.jsonl")


def main() -> None:
    settings = load_settings()
    retriever = ChatRetriever.from_settings(settings, enable_vector=True, enable_reranker=False)
    cases = [json.loads(line) for line in EVAL_SET.read_text(encoding="utf-8").splitlines() if line.strip()]

    results = [
        probe_case(
            bm25_index=retriever.bm25_index,
            vector_retriever=retriever.vector_retriever,
            case=case,
            candidate_k=40,
        )
        for case in cases
    ]

    print(f"{'case':<28}{'BM25':>6}{'VEC':>6}{'RRF':>6}  @8")
    for r in results:
        def fmt(v): return "-" if v is None else str(v)
        flag = "PASS" if r["pass_at_8"] else "FAIL"
        print(f"{str(r['id']):<28}{fmt(r['bm25_rank']):>6}{fmt(r['vector_rank']):>6}{fmt(r['rrf_rank']):>6}  {flag}")

    summary = summarize_probe_results(results)
    print(f"\nrecall@8={summary['recall_at_8']}  recall@20={summary['recall_at_20']}  MRR={summary['mrr']}")
    print(f"fail: {summary['fail_ids']}")


if __name__ == "__main__":
    main()
```

> 참고: `load_settings` 의 정확한 이름은 `src/play_book_studio/config/settings.py` 에서
> 확인할 것. import 줄이 다르면 그 파일의 공개 로더 함수로 맞춘다.

- [ ] **Step 6: baseline 측정 (현재 파이프라인 그대로)**

Run: `python scripts/run_recall_probe.py`
Expected: 표 출력 + `recall@8=<값>`. 이 숫자가 baseline. 결과를 커밋 메시지에 기록.

- [ ] **Step 7: 커밋**

```bash
git add scripts/run_recall_probe.py src/play_book_studio/evals/recall_probe.py tests/test_recall_probe.py
git commit -m "test: recall 프로브 CLI 추가 (baseline recall@8=<측정값> 기록)"
```

---

## Phase 2 — query_normalize (intent 하드코딩 제거)

### Task 5: alias 테이블 + 로더

**Files:**
- Create: `src/play_book_studio/retrieval/aliases.toml`
- Create: `src/play_book_studio/retrieval/alias_table.py`
- Test: `tests/test_alias_table.py`

- [ ] **Step 1: alias 데이터 파일 작성**

```toml
# src/play_book_studio/retrieval/aliases.toml
# 자연어 표현 -> BM25/임베딩 질의에 덧붙일 정규 용어.
# 새 표현이 안 잡히면 여기 한 줄만 추가한다. 코드 수정 불필요.

[aliases]
"pod 중단 예산" = ["poddisruptionbudget", "PodDisruptionBudget"]
"중단 예산" = ["poddisruptionbudget"]
"모든 프로젝트" = ["--all-namespaces"]
"로그인" = ["login", "oc login"]
"로그아웃" = ["logout"]
"노드 상태" = ["node status", "oc get nodes"]
"네임스페이스" = ["namespace", "project"]
```

- [ ] **Step 2: 실패 테스트 작성**

```python
# tests/test_alias_table.py
from play_book_studio.retrieval.alias_table import load_alias_table, expand_with_aliases


def test_expand_with_aliases_appends_canonical_terms():
    table = {"pod 중단 예산": ["poddisruptionbudget"], "모든 프로젝트": ["--all-namespaces"]}
    expanded = expand_with_aliases("모든 프로젝트에서 pod 중단 예산 확인", table)
    assert "poddisruptionbudget" in expanded
    assert "--all-namespaces" in expanded
    assert "모든 프로젝트에서 pod 중단 예산 확인" in expanded


def test_expand_with_aliases_no_match_returns_query_unchanged():
    assert expand_with_aliases("관련 없는 질문", {"로그인": ["login"]}) == "관련 없는 질문"


def test_load_alias_table_reads_packaged_toml():
    table = load_alias_table()
    assert "로그인" in table
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `pytest tests/test_alias_table.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: 구현**

```python
# src/play_book_studio/retrieval/alias_table.py
"""자연어 표현 -> 정규 용어 alias 테이블. intent_profile 하드코딩을 대체한다."""
from __future__ import annotations

import tomllib
from pathlib import Path

_ALIAS_PATH = Path(__file__).with_name("aliases.toml")


def load_alias_table() -> dict[str, list[str]]:
    raw = tomllib.loads(_ALIAS_PATH.read_text(encoding="utf-8"))
    aliases = raw.get("aliases", {})
    return {str(k): [str(v) for v in vals] for k, vals in aliases.items()}


def expand_with_aliases(query: str, table: dict[str, list[str]]) -> str:
    """질의에 매칭되는 alias의 정규 용어를 뒤에 덧붙인다. 원문은 보존."""
    lowered = query.lower()
    extra: list[str] = []
    seen: set[str] = set()
    for phrase, canonicals in table.items():
        if phrase.lower() in lowered:
            for term in canonicals:
                if term not in seen and term not in query:
                    seen.add(term)
                    extra.append(term)
    if not extra:
        return query
    return query + " " + " ".join(extra)
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest tests/test_alias_table.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: 커밋**

```bash
git add src/play_book_studio/retrieval/aliases.toml src/play_book_studio/retrieval/alias_table.py tests/test_alias_table.py
git commit -m "feat: 단일 alias 테이블 추가 (intent 하드코딩 대체)"
```

---

### Task 6: query_normalize 모듈

**Files:**
- Create: `src/play_book_studio/retrieval/query_normalize.py`
- Test: `tests/test_query_normalize.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_query_normalize.py
from play_book_studio.retrieval.query_normalize import normalize_query


def test_normalize_query_trims_and_collapses_whitespace():
    assert normalize_query("  노드   상태   확인  ") == "노드 상태 확인"


def test_normalize_query_appends_alias_terms():
    out = normalize_query("모든 프로젝트에서 pod 중단 예산 확인")
    assert "poddisruptionbudget" in out
    assert "--all-namespaces" in out


def test_normalize_query_returns_single_string_no_fanout():
    # subquery fan-out 없음: 항상 문자열 하나.
    assert isinstance(normalize_query("ocp 로그인 어떻게 함"), str)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_query_normalize.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 구현**

```python
# src/play_book_studio/retrieval/query_normalize.py
"""질의 정규화 단일 모듈.

query_terms*, query_understanding, intent_profile, rewrite, query_signal_pipeline 을
대체한다. subquery fan-out 없음 — 항상 정규화된 문자열 하나를 반환한다.
"""
from __future__ import annotations

from .alias_table import expand_with_aliases, load_alias_table

_ALIAS_TABLE = load_alias_table()


def normalize_query(query: str) -> str:
    collapsed = " ".join(str(query or "").split())
    if not collapsed:
        return ""
    return expand_with_aliases(collapsed, _ALIAS_TABLE)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_query_normalize.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/play_book_studio/retrieval/query_normalize.py tests/test_query_normalize.py
git commit -m "feat: query_normalize 단일 모듈 추가"
```

---

## Phase 3 — hybrid_search (검색 경로 교체)

### Task 7: hybrid_search 모듈 — 병렬 검색 + RRF

**Files:**
- Create: `src/play_book_studio/retrieval/hybrid_search.py`
- Test: `tests/test_hybrid_search.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_hybrid_search.py
from play_book_studio.retrieval.hybrid_search import hybrid_search
from play_book_studio.retrieval.models import RetrievalHit


def _hit(chunk_id, *, book_slug="nodes", raw_score=1.0):
    return RetrievalHit(
        chunk_id=chunk_id, book_slug=book_slug, chapter="", section="", anchor="",
        source_url="", viewer_path="", text="", source="x", raw_score=raw_score,
    )


class _FakeBM25:
    def __init__(self, hits): self._hits = hits
    def search(self, query, top_k=10): return self._hits[:top_k]


class _FakeVector:
    def __init__(self, hits, *, fail=False): self._hits = hits; self._fail = fail
    def search(self, query, top_k=10, query_filter=None):
        if self._fail:
            raise RuntimeError("vector down")
        return self._hits[:top_k]


def test_hybrid_search_merges_bm25_and_vector_to_top_k():
    result = hybrid_search(
        "노드 상태",
        bm25_index=_FakeBM25([_hit("a"), _hit("b")]),
        vector_retriever=_FakeVector([_hit("b"), _hit("c")]),
        candidate_k=40, top_k=8,
    )
    ids = [h.chunk_id for h in result.hits]
    assert set(ids) == {"a", "b", "c"}
    assert len(result.hits) <= 8


def test_hybrid_search_falls_back_to_bm25_when_vector_fails():
    result = hybrid_search(
        "노드 상태",
        bm25_index=_FakeBM25([_hit("a")]),
        vector_retriever=_FakeVector([], fail=True),
        candidate_k=40, top_k=8,
    )
    assert [h.chunk_id for h in result.hits] == ["a"]
    assert result.vector_failed is True
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_hybrid_search.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 구현**

```python
# src/play_book_studio/retrieval/hybrid_search.py
"""Stage-1 hybrid 검색: BM25 ‖ 벡터 -> RRF -> top-k.

retriever_search.py / retriever_plan.py / query_signal_pipeline.py 의
fan-out·metadata-filter 경로를 대체한다. subquery는 항상 1개.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .models import RetrievalHit
from .query_normalize import normalize_query
from .ranking import rrf_merge_named_hit_lists


@dataclass(slots=True)
class HybridSearchResult:
    hits: list[RetrievalHit]
    normalized_query: str
    bm25_count: int
    vector_count: int
    vector_failed: bool


def hybrid_search(
    query: str,
    *,
    bm25_index,
    vector_retriever,
    candidate_k: int = 40,
    top_k: int = 8,
) -> HybridSearchResult:
    normalized = normalize_query(query)

    def run_bm25() -> list[RetrievalHit]:
        if bm25_index is None:
            return []
        return bm25_index.search(normalized, top_k=candidate_k)

    vector_failed = False

    def run_vector() -> list[RetrievalHit]:
        nonlocal vector_failed
        if vector_retriever is None:
            return []
        try:
            return vector_retriever.search(normalized, top_k=candidate_k)
        except Exception:  # noqa: BLE001
            vector_failed = True
            return []

    with ThreadPoolExecutor(max_workers=2) as executor:
        bm25_future = executor.submit(run_bm25)
        vector_future = executor.submit(run_vector)
        bm25_hits = bm25_future.result()
        vector_hits = vector_future.result()

    merged = rrf_merge_named_hit_lists(
        {"bm25": bm25_hits, "vector": vector_hits},
        source_name="hybrid",
        top_k=top_k,
    )
    return HybridSearchResult(
        hits=merged,
        normalized_query=normalized,
        bm25_count=len(bm25_hits),
        vector_count=len(vector_hits),
        vector_failed=vector_failed,
    )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_hybrid_search.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/play_book_studio/retrieval/hybrid_search.py tests/test_hybrid_search.py
git commit -m "feat: hybrid_search 모듈 추가 (병렬 BM25+벡터, RRF, fan-out 제거)"
```

---

### Task 8: hydration을 RRF 병합 후 top-8로 이동

**Files:**
- Modify: `src/play_book_studio/retrieval/vector.py` (`search_with_trace` 의 `_hydrate_hits_from_database` 호출 제거 — 줄 위치는 작업 시 확인)
- Modify: `src/play_book_studio/retrieval/hybrid_search.py`
- Test: `tests/test_hybrid_search.py`

- [ ] **Step 1: 실패 테스트 추가**

`tests/test_hybrid_search.py` 끝에 추가:

```python
def test_hybrid_search_hydrates_only_final_hits(monkeypatch):
    hydrated_calls = []

    def fake_hydrate(hits, *, database_url):
        hydrated_calls.append(len(hits))
        return hits

    import play_book_studio.retrieval.hybrid_search as hs
    monkeypatch.setattr(hs, "hydrate_final_hits", fake_hydrate)

    bm25 = _FakeBM25([_hit(str(i)) for i in range(40)])
    vector = _FakeVector([_hit(str(i)) for i in range(40, 80)])
    hybrid_search("q", bm25_index=bm25, vector_retriever=vector,
                  candidate_k=40, top_k=8, database_url="postgres://x")

    # 80개 후보가 아니라 최종 8개만 hydration.
    assert hydrated_calls == [8]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_hybrid_search.py::test_hybrid_search_hydrates_only_final_hits -v`
Expected: FAIL — `hybrid_search() got an unexpected keyword argument 'database_url'`

- [ ] **Step 3: 구현 — hydration helper + hybrid_search 인자 추가**

`hybrid_search.py` 에 추가:

```python
def hydrate_final_hits(hits: list[RetrievalHit], *, database_url: str) -> list[RetrievalHit]:
    """최종 후보만 canonical DB 행으로 보강. DB 미설정/빈 후보면 그대로 반환."""
    if not hits or not database_url.strip():
        return hits
    import psycopg

    from .chunk_hydration import hydrate_retrieval_hits

    with psycopg.connect(database_url) as connection:
        return hydrate_retrieval_hits(connection, hits)
```

`hybrid_search()` 시그니처에 `database_url: str = ""` 추가하고, `merged` 계산 직후:

```python
    merged = rrf_merge_named_hit_lists(
        {"bm25": bm25_hits, "vector": vector_hits},
        source_name="hybrid",
        top_k=top_k,
    )
    merged = hydrate_final_hits(merged, database_url=database_url)
```

`vector.py` `search_with_trace` 에서 `_hydrate_hits_from_database` 호출을 제거한다
(벡터 검색은 더 이상 hydration하지 않음 — 병합 후 일괄 처리). `hydration` trace 키는
`{"status": "deferred"}` 로 둔다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_hybrid_search.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add src/play_book_studio/retrieval/hybrid_search.py src/play_book_studio/retrieval/vector.py tests/test_hybrid_search.py
git commit -m "perf: hydration을 RRF 병합 후 최종 top-8로 이동"
```

---

### Task 9: ChatRetriever를 hybrid_search 경로로 전환

**Files:**
- Modify: `src/play_book_studio/retrieval/retriever.py` (`retrieve` 메서드, 줄 108-129)
- Test: `tests/test_retriever_hybrid_path.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_retriever_hybrid_path.py
from play_book_studio.retrieval.models import RetrievalHit
from play_book_studio.retrieval.retriever import ChatRetriever


def _hit(chunk_id):
    return RetrievalHit(
        chunk_id=chunk_id, book_slug="nodes", chapter="", section="", anchor="",
        source_url="", viewer_path="", text="", source="bm25", raw_score=1.0,
    )


class _FakeBM25:
    def search(self, query, top_k=10): return [_hit("a"), _hit("b")]


def test_retrieve_uses_hybrid_search_without_fanout():
    retriever = ChatRetriever.__new__(ChatRetriever)
    retriever.bm25_index = _FakeBM25()
    retriever.vector_retriever = None
    retriever.reranker = None
    retriever.settings = type("S", (), {"database_url": "", "reranker_enabled": False})()

    result = retriever.retrieve("노드 상태", top_k=8)

    assert [h.chunk_id for h in result.hits] == ["a", "b"]
    assert result.trace["retrieval_query_count"] == 1
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_retriever_hybrid_path.py -v`
Expected: FAIL — 현재 `retrieve` 는 `execute_retrieval_pipeline` 호출, trace 키 불일치

- [ ] **Step 3: 구현 — `retrieve` 를 hybrid_search 호출로 교체**

`retriever.py` 의 `retrieve` 메서드 본문(줄 119-129)을 교체:

```python
    def retrieve(
        self,
        query: str,
        *,
        context: SessionContext | None = None,
        top_k: int = 8,
        candidate_k: int = 40,
        use_bm25: bool = True,
        use_vector: bool = True,
        trace_callback=None,
    ) -> RetrievalResult:
        from .hybrid_search import hybrid_search

        search = hybrid_search(
            query,
            bm25_index=self.bm25_index if use_bm25 else None,
            vector_retriever=self.vector_retriever if use_vector else None,
            candidate_k=candidate_k,
            top_k=top_k,
            database_url=getattr(self.settings, "database_url", ""),
        )
        hits = search.hits
        reranker_failed = False
        if self.reranker is not None and self.reranker.enabled and hits:
            try:
                hits = self.reranker.rerank(search.normalized_query, hits, top_k=top_k)[:top_k]
            except Exception:  # noqa: BLE001 — 리랭커 에러 시 pre-rerank 순서로 폴백
                reranker_failed = True
                hits = search.hits

        return RetrievalResult(
            query=query,
            normalized_query=search.normalized_query,
            rewritten_query=search.normalized_query,
            top_k=top_k,
            candidate_k=candidate_k,
            context=(context or SessionContext()).to_dict(),
            hits=hits,
            trace={
                "retrieval_query_count": 1,
                "bm25_count": search.bm25_count,
                "vector_count": search.vector_count,
                "vector_failed": search.vector_failed,
                "reranker_applied": self.reranker is not None and self.reranker.enabled,
                "reranker_failed": reranker_failed,
            },
        )
```

> `top_k` 기본값을 5→8, `candidate_k` 10→40 으로 변경한 점에 유의. 호출처
> (`answerer.py` 등)에서 명시적으로 5를 넘기면 그 값도 8로 올린다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_retriever_hybrid_path.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: recall 프로브 재측정**

Run: `python scripts/run_recall_probe.py`
Expected: recall@8 이 Task 4 baseline 대비 상승. 표 확인.

- [ ] **Step 6: 커밋**

```bash
git add src/play_book_studio/retrieval/retriever.py tests/test_retriever_hybrid_path.py
git commit -m "feat: ChatRetriever를 hybrid_search 경로로 전환 (fan-out·metadata filter 제거)"
```

---

## Phase 4 — answerer grounding guard soft-degrade

### Task 10: hard-block 가드를 soft-degrade로 전환

**Files:**
- Modify: `src/play_book_studio/answering/answerer.py` (가드 블록들 — 줄 905, 945, 1211, 1249 부근의 `_build_grounding_blocked_result` 호출)
- Test: `tests/test_grounding_soft_degrade.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_grounding_soft_degrade.py
"""grounding guard 불일치 시 답변을 차단하지 않고 주의문구로 degrade한다."""
from play_book_studio.answering.answerer import _grounding_caveat_note


def test_grounding_caveat_note_is_non_empty_warning_text():
    note = _grounding_caveat_note("insufficient command grounding coverage")
    assert note
    assert "근거" in note
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/test_grounding_soft_degrade.py -v`
Expected: FAIL — `ImportError: cannot import name '_grounding_caveat_note'`

- [ ] **Step 3: 구현 — caveat helper 추가 + 가드 전환**

`answerer.py` 에 helper 추가:

```python
def _grounding_caveat_note(reason: str) -> str:
    """grounding guard 불일치 시 답변에 덧붙일 주의문구."""
    return (
        "\n\n> 참고: 이 답변의 근거가 질문과 부분적으로만 일치합니다. "
        "공식 문서 인용을 직접 확인하세요."
    )
```

각 가드 블록(`actionable_command_query and not has_sufficient_command_grounding(...)`,
`_requires_monitoring_backup_grounding`, `_requires_console_grounding`,
`_requires_rbac_grounding`)에서 `return self._build_grounding_blocked_result(...)` 를
제거하고, 대신 `warnings.append(...)` 만 남긴 뒤 답변 본문에 `_grounding_caveat_note(...)`
를 덧붙여 정상 답변 경로로 진행한다.

`context_bundle.citations` 가 **빈 경우**(줄 847 `if not context_bundle.citations:`)는
그대로 차단 유지 — 이건 진짜 "hit 0개"다.

- [ ] **Step 4: 테스트 통과 확인 + 회귀 확인**

Run: `pytest tests/test_grounding_soft_degrade.py tests/test_chat_grounding_quality.py -v`
Expected: 새 테스트 PASS. `test_chat_grounding_quality.py` 의 일부 가드 관련 테스트는
실패할 수 있음 — Task 12에서 정리.

- [ ] **Step 5: 커밋**

```bash
git add src/play_book_studio/answering/answerer.py tests/test_grounding_soft_degrade.py
git commit -m "feat: grounding guard를 hard-block에서 soft-degrade로 전환"
```

---

## Phase 5 — dead 모듈 삭제 + 테스트 정리

### Task 11: 끊어진 import 식별

**Files:**
- (조사만 — 변경 없음)

- [ ] **Step 1: 삭제 후보 모듈의 잔존 참조 확인**

Run:
```bash
git grep -l -E "intent_profile|query_signal_pipeline|query_understanding|build_retrieval_plan|retriever_rerank|scoring_adjustments|book_adjustment" -- "src/play_book_studio/**/*.py" | grep -v "/retrieval/"
```
Expected: retrieval 디렉터리 밖에서 위 모듈을 import하는 파일 목록. 각 파일이 어떤
심볼을 쓰는지 기록 — Task 12 삭제 전에 호출처를 정리해야 한다.

- [ ] **Step 2: 조사 결과를 plan 메모로 커밋**

```bash
git commit --allow-empty -m "chore: dead 모듈 잔존 참조 조사 완료"
```

---

### Task 12: dead 모듈 삭제 + 깨진 테스트를 eval 케이스로 전환

**Files:**
- Delete: `intent_profile.py`, `intent_detectors.py`, `intent_patterns.py`, `intents.py`,
  `query_signal_pipeline.py`, `query_understanding.py`, `query_terms*.py`(7개),
  `rewrite.py`, `scoring_adjustments*.py`(전체), `book_adjustment_*.py`(전체),
  `concept_expansion.py`, `domain_lexicon.py`, `ambiguity.py`, `scoring_signals.py`,
  `scoring_postprocess.py`, `retriever_rerank.py`, `retriever_plan.py`,
  `retriever_pipeline.py`, `retriever_search.py` — 모두 `src/play_book_studio/retrieval/`
- Modify: `tests/test_chat_grounding_quality.py`
- Modify: Task 11에서 식별된 호출처 파일들

- [ ] **Step 1: 호출처 정리**

Task 11에서 식별된 retrieval 밖 파일들에서 삭제 모듈 import를 제거하고, 필요한 기능은
`hybrid_search` / `query_normalize` 로 대체한다. (파일별 구체 수정은 Step 1 조사 결과에
따라 결정 — 각 파일은 보통 `build_intent_profile` 또는 `normalize_query` 한두 개를 쓴다.)

> **삭제는 한 커밋에 몰지 않는다.** 25개 파일을 한 번에 지우면 회귀 발생 시 bisect가
> 불가능하다. 아래처럼 3개 클러스터로 나눠 각각 `pytest -q` 그린 확인 후 커밋한다.
> 한 클러스터에서 `ModuleNotFoundError` 가 나면 그 클러스터만 되돌리고 Step 1의
> 호출처 정리로 복귀한다.

- [ ] **Step 2: 클러스터 A 삭제 — query 이해 모듈**

```bash
cd src/play_book_studio/retrieval
git rm intent_profile.py intent_detectors.py intent_patterns.py intents.py \
  query_signal_pipeline.py query_understanding.py query_terms*.py rewrite.py
```

Run: `pytest -q && python -c "import play_book_studio.retrieval.retriever"`
Expected: 수집 에러 없음. 에러가 남으면 그 import를 `query_normalize` 로 교체.

```bash
git add -A && git commit -m "refactor: query 이해 하드코딩 모듈 삭제 (intent/signal/query_terms)"
```

- [ ] **Step 3: 클러스터 B 삭제 — 스코어링 조정 모듈**

```bash
cd src/play_book_studio/retrieval
git rm scoring_adjustments*.py book_adjustment_*.py concept_expansion.py \
  domain_lexicon.py ambiguity.py scoring_signals.py scoring_postprocess.py
```

Run: `pytest -q && python -c "import play_book_studio.retrieval.retriever"`
Expected: 수집 에러 없음.

```bash
git add -A && git commit -m "refactor: per-query 매직 상수 스코어링 모듈 삭제"
```

- [ ] **Step 4: 클러스터 C 삭제 — 구 오케스트레이션 모듈**

```bash
cd src/play_book_studio/retrieval
git rm retriever_rerank.py retriever_plan.py retriever_pipeline.py retriever_search.py
```

Run: `pytest -q && python -c "import play_book_studio.retrieval.retriever"`
Expected: 수집 에러 없음 (Task 9에서 `retrieve` 가 이미 `hybrid_search` 경로로 전환됨).

```bash
git add -A && git commit -m "refactor: 구 retriever 오케스트레이션 모듈 삭제"
```

- [ ] **Step 5: 깨진 테스트 처리**

`tests/test_chat_grounding_quality.py` 에서 삭제 모듈(`build_intent_profile`,
`_rebalance_intent_profile_hits`, `fuse_ranked_hits` 의 v0xx 매직 상수 단언)에 의존하는
테스트를 제거한다. 각 테스트의 `query` 문자열은 `tests/eval/retrieval_eval_set.jsonl` 에
**자연스러운 사용자 말투로 다시 쓴** eval 케이스로 옮긴다 (v0xx 토픽 체크리스트 활용 —
spec 5절). 순수 동작 테스트(`assemble_context`, `suggest_follow_up_questions`,
`strip_ungrounded_code_blocks` 등)는 유지.

```bash
git add -A && git commit -m "test: v0xx 매직 상수 테스트를 eval 케이스로 전환"
```

- [ ] **Step 6: 최종 확인**

Run: `pytest -q && python -c "import play_book_studio.retrieval.retriever"`
Expected: 전체 통과, import 성공.

---

## Phase 6 — A′/B′ 결정

### Task 13: recall 프로브 최종 측정 + 리랭커 기본값 결정

**Files:**
- Modify: `src/play_book_studio/config/settings.py` (줄 351 `reranker_enabled` 기본값)
- Modify: `deploy/openshift/core.yaml` (`RERANKER_ENABLED` 환경변수)

- [ ] **Step 1: eval셋을 30~50개로 확장**

`tests/eval/retrieval_eval_set.jsonl` 에 케이스를 추가한다. 소스: corpus의
`starter_question_candidates`(아래 명령으로 추출), v0xx 토픽을 사용자 말투로 재작성한 질문.

Run (starter 후보 추출 예):
```bash
python -c "import json; [print(json.loads(l).get('starter_question_candidates')) for l in open('corpus/sources/official/imported-gold/gold_corpus_ko/chunks.jsonl', encoding='utf-8')][:50]"
```

- [ ] **Step 2: 리랭커 OFF / ON 양쪽 측정**

Run:
```bash
python scripts/run_recall_probe.py
```
recall@8 (stage-1 hybrid 기준)을 기록. 리랭커는 stage-1 recall@8을 바꾸지 않으므로
프로브 값이 곧 A′ 기준. 추가로 답변 레벨 eval(`answer_eval.py`)을 리랭커 ON/OFF로
각각 돌려 응답 지연·정확도를 비교.

- [ ] **Step 3: 기본값 설정**

- recall@8 ≥ 0.90 → `settings.py` 줄 351 `RERANKER_ENABLED` 기본값 `"false"` 유지(A′),
  `deploy/openshift/core.yaml` 의 `RERANKER_ENABLED` 를 `"false"` 로.
- recall@8 < 0.90 → `"true"` 로 두되 `reranker_top_n`/`reranker_candidate_k` 를 8 로(B′).

- [ ] **Step 4: 커밋**

```bash
git add src/play_book_studio/config/settings.py deploy/openshift/core.yaml tests/eval/retrieval_eval_set.jsonl
git commit -m "chore: eval 측정 결과로 RERANKER_ENABLED 기본값 확정 (recall@8=<측정값>)"
```

---

## 완료 기준

- `pytest -q` 전체 통과, `import play_book_studio.retrieval.retriever` 성공
- `python scripts/run_recall_probe.py` 의 recall@8 이 Task 4 baseline 대비 상승
- eval셋에서 `ocp-login`, `pdb-all-ns` 케이스 PASS
- retrieval 디렉터리에서 `intent_profile` / `scoring_adjustments` / `book_adjustment`
  / `query_signal_pipeline` 계열 모듈이 모두 제거됨

> **측정 입도 주의:** 기존 `reports/v012_retrieval_eval_after.json` 의 `hit@5=0.9444` 는
> `book_slug` 단위 측정이다 (`retrieval_eval.py` 의 `hit_at_k` 가 `top_book_slugs` 를 봄).
> 맞는 *책*이 상위에 들어도 실제 정답 *청크/명령*은 누락될 수 있어, 이 값이 높아도
> 사용자 체감 실패와 모순되지 않는다. 새 recall 프로브는 command/section/chunk 단위로
> 매칭하므로 **v012 의 0.94 와 새 recall@8 을 직접 비교하지 말 것.** 성공 판단은
> 절대 평균이 아니라 baseline 대비 상승 + 특정 실패 질문 PASS + landing/rank + latency 로 한다.

## 범위 밖 (이번 계획 비포함)

- `embedding_text` 강화 및 코퍼스 재임베딩 — 별도 후속
- corpus `cli_commands` 마크업 누수 / `k8s_objects` 오라벨링 정리 — 별도 후속
- 리랭커 GPU 서빙 전환 — 인프라 가용 시
