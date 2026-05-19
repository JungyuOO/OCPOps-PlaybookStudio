"""grounded answer 전체를 오케스트레이션한다.

이 모듈이 채팅 제품의 런타임 spine이다:
retrieve -> assemble context -> prompt -> LLM -> answer shaping -> citations
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from play_book_studio.config.settings import Settings
from play_book_studio.retrieval import ChatRetriever, SessionContext
from play_book_studio.retrieval.query import (
    has_backup_restore_intent,
    has_command_request,
    has_corrective_follow_up,
    has_doc_locator_intent,
    has_follow_up_entity_ambiguity,
    has_follow_up_reference,
    has_mco_concept_intent,
    has_openshift_kubernetes_compare_intent,
    has_operator_concept_intent,
    has_pod_lifecycle_concept_intent,
    has_crash_loop_troubleshooting_intent,
    has_pod_pending_troubleshooting_intent,
    has_rbac_intent,
    has_route_ingress_compare_intent,
    is_explainer_query,
    is_generic_intro_query,
)
from play_book_studio.retrieval.korean_text import normalized_token_set
from play_book_studio.retrieval.query_understanding import has_beginner_troubleshooting_intent

from .answer_text_commands import has_sufficient_command_grounding, strip_ungrounded_code_blocks
from .answer_text_formatting import summarize_session_context
from .citations import (
    finalize_citations,
    inject_citation_indices,
    inject_single_citation,
    preserve_explicit_mixed_runtime_citations,
    select_fallback_citations,
    summarize_selected_citations,
)
from .context import assemble_context
from .doc_locator_intent import is_document_sequence_query as _shared_is_document_sequence_query
from .llm import LLMClient
from .models import AnswerResult, Citation
from .pipeline_helpers import (
    build_answer_result,
    build_follow_up_clarification_answer,
    generate_grounded_answer_text,
)
from .prompt import build_messages
from .router import route_non_rag


def _looks_like_missing_coverage_answer(answer: str) -> bool:
    normalized = " ".join(str(answer or "").split()).lower()
    missing_patterns = (
        "제공된 근거에 포함되어 있지 않습니다",
        "제공된 문서는",
        "포함되어 있지 않습니다",
        "직접 제공하지 않습니다",
        "제공되지 않습니다",
        "근거에 없습니다",
    )
    if not any(pattern in normalized for pattern in missing_patterns):
        return False
    return any(
        anchor in normalized
        for anchor in (
            "예시는 제공",
            "설명하고 있습니다",
            "방식만 설명",
            "대신",
            "만 설명",
        )
    )


_CONFIDENCE_STOPWORDS = {
    "어떻게",
    "어떤",
    "먼저",
    "확인",
    "알려줘",
    "설명해줘",
    "기준",
    "순서",
    "문제",
    "상태",
    "방법",
    "where",
    "what",
    "how",
    "the",
    "and",
    "for",
}


def _confidence_tokens(*texts: str) -> set[str]:
    return {
        token
        for token in normalized_token_set(*texts)
        if token not in _CONFIDENCE_STOPWORDS
    }


def _selected_hit_score(selected_hits: list[dict] | None, key: str) -> float:
    if not selected_hits:
        return 0.0
    values = []
    for item in selected_hits:
        value = item.get(key)
        if isinstance(value, int | float):
            values.append(float(value))
    return max(values, default=0.0)


def _citation_token_coverage(query: str, citations: list[Citation]) -> float:
    query_tokens = _confidence_tokens(query)
    if len(query_tokens) < 3 or not citations:
        return 1.0
    citation_tokens = _confidence_tokens(
        *[
            " ".join(
                [
                    citation.book_slug,
                    citation.section,
                    citation.excerpt,
                    " ".join(citation.section_path),
                    " ".join(citation.cli_commands),
                    " ".join(citation.k8s_objects),
                    " ".join(citation.operator_names),
                ]
            )
            for citation in citations
        ]
    )
    if not citation_tokens:
        return 0.0
    overlap = query_tokens & citation_tokens
    return len(overlap) / max(1, min(len(query_tokens), 8))


def _low_confidence_example_questions(selected_hits: list[dict] | None) -> list[str]:
    examples: list[str] = []
    seen: set[str] = set()
    for item in selected_hits or []:
        section = _clean_low_confidence_subject(str(item.get("section") or "").strip())
        book_slug = str(item.get("book_slug") or "").strip()
        if not section or section.lower() in {"additional resources", "추가 리소스", "릴리스 노트"}:
            continue
        subject = section
        if book_slug and book_slug not in section:
            subject = f"{section}"
        for candidate in (
            f"{subject} 기준으로 먼저 확인할 절차를 알려줘",
            f"{subject}에서 상태 확인 명령과 판단 기준을 알려줘",
        ):
            if candidate not in seen:
                seen.add(candidate)
                examples.append(candidate)
        if len(examples) >= 3:
            break
    return examples[:3]


def _clean_low_confidence_subject(section: str) -> str:
    subject = re.sub(r"\s+", " ", str(section or "").strip())
    subject = re.sub(r"^\d+(?:\.\d+)*\.?\s*", "", subject)
    subject = re.sub(r"^\d+\s*장\.\s*", "", subject)
    subject = re.sub(r"^(chapter|section)\s+\d+(?:\.\d+)*\.?\s*", "", subject, flags=re.IGNORECASE)
    subject = subject.strip(" .>-")
    if not subject or re.match(r"^\d", subject):
        return ""
    return subject


_GUIDED_LEARNING_QUESTION_RE = re.compile(
    r"("
    r"OCP를\s*처음\s*시작|"
    r"Installation\s+overview|"
    r"단계에서는.*(?:기준|문서).*(?:학습|이해|순서)|"
    r"(?:학습|입문).*(?:순서|로드맵|단계)|"
    r"(?:무엇부터|어디부터).*(?:이해|학습)"
    r")",
    re.IGNORECASE,
)
V016_LOW_CONFIDENCE_BYPASS_RE = re.compile(
    r"(?<![a-z0-9])(?:pdb|poddisruptionbudget|hpa|horizontalpodautoscaler|vpa|verticalpodautoscaler|hsts|localvolume|localvolumeset|localvolumediscovery)(?![a-z0-9])|"
    r"Local\s*Storage\s*Operator|Vertical\s*Pod\s*Autoscaler\s*Operator|로컬\s*스토리지|중단\s*예산|스케일링\s*정책|도메인별\s*HSTS",
    re.IGNORECASE,
)


def _is_guided_learning_question(query: str) -> bool:
    return bool(_GUIDED_LEARNING_QUESTION_RE.search(query or ""))


def _is_install_overview_question(query: str) -> bool:
    lowered = str(query or "").lower()
    has_product = (
        "ocp" in lowered
        or "openshift" in lowered
        or "오픈시프트" in str(query or "")
        or "오픈 시프트" in str(query or "")
    )
    has_install = (
        "설치" in str(query or "")
        or "구축" in str(query or "")
        or "install" in lowered
        or "installation" in lowered
        or "installer" in lowered
    )
    return has_product and has_install


def _retrieval_hits_for_clarification(hits: list) -> list[dict]:
    rows: list[dict] = []
    for hit in hits[:3]:
        row = {
            "section": str(getattr(hit, "section", "") or "").strip(),
            "book_slug": str(getattr(hit, "book_slug", "") or "").strip(),
            "fused_score": float(getattr(hit, "fused_score", 0.0) or 0.0),
        }
        component_scores = getattr(hit, "component_scores", {}) or {}
        if isinstance(component_scores, dict):
            for key in ("pre_rerank_fused_score", "vector_score", "bm25_score"):
                value = component_scores.get(key)
                if isinstance(value, int | float):
                    row[key] = float(value)
        rows.append(row)
    return rows


def _low_confidence_clarification_answer(
    *,
    selected_hits: list[dict] | None,
) -> str:
    examples = _low_confidence_example_questions(selected_hits)
    lines = [
        "답변: 지금 질문은 현재 공식 문서 근거와 정확히 맞물리는 점수가 낮습니다.",
        "엉뚱한 절차를 단정하지 않도록, 대상 리소스나 증상, 하고 싶은 작업을 한 단계만 더 좁혀 주세요.",
    ]
    if examples:
        lines.extend(["", "이런 식으로 물어보면 더 정확히 안내할 수 있습니다."])
        lines.extend([f"- {example}" for example in examples])
    return "\n".join(lines)


def _is_low_confidence_retrieval(
    *,
    query: str,
    citations: list[Citation],
    selected_hits: list[dict] | None,
) -> bool:
    if not citations:
        return False
    normalized_query = (query or "").lower()
    if V016_LOW_CONFIDENCE_BYPASS_RE.search(query or ""):
        return False
    citation_haystack = " ".join(
        " ".join(
            str(value or "")
            for value in (
                citation.book_slug,
                citation.section,
                citation.section_path_label,
                citation.excerpt,
            )
        )
        for citation in citations
    ).lower()
    if has_backup_restore_intent(query) and any(token in citation_haystack for token in ("etcd", "backup", "restore", "백업", "복원")):
        return False
    if ("route" in normalized_query or "ingress" in normalized_query) and any(
        token in citation_haystack
        for token in ("ingress_and_load_balancing", "ingress", "route", "networking")
    ):
        return False
    if any(token in normalized_query for token in ("ocp-certificates", "인증서", "certificate", "cert")) and any(
        token in citation_haystack
        for token in ("certificate", "인증서", "security_and_compliance", "authentication")
    ):
        return False
    if (
        has_doc_locator_intent(query)
        or is_generic_intro_query(query)
        or is_explainer_query(query)
        or _is_guided_learning_question(query)
        or _is_supported_ops_learning_question(query)
    ):
        return False
    if has_beginner_troubleshooting_intent(query) and any(
        token in citation_haystack
        for token in (
            "troubleshooting",
            "events",
            "describe",
            "logs",
            "secret",
            "configmap",
            "configuration",
            "pod",
            "workloads",
            "applications",
            "상태",
            "오류",
        )
    ):
        return False
    operational_token_pairs = (
        ("imagepullbackoff", ("imagepullbackoff", "errimagepull", "pull secret", "registry")),
        ("errimagepull", ("imagepullbackoff", "errimagepull", "pull secret", "registry")),
        ("networkpolicy", ("networkpolicy", "network policy", "ingress", "egress")),
        ("machine config", ("machine config", "machineconfigpool", "mco")),
        ("machineconfigpool", ("machine config", "machineconfigpool", "mco")),
        ("cluster version", ("clusterversion", "cluster version", "cvo")),
        ("clusterversion", ("clusterversion", "cluster version", "cvo")),
        ("must-gather", ("must-gather", "must gather", "support", "diagnostic")),
        ("oc adm inspect", ("oc adm inspect", "inspect", "namespace", "resource")),
        ("finalizer", ("finalizer", "finalizers", "terminating", "namespace")),
        ("observability", ("observability", "monitoring", "logging")),
        ("리소스", ("oc adm top pod", "top pod", "metrics", "cpu", "memory")),
        ("사용량", ("oc adm top pod", "top pod", "metrics", "cpu", "memory")),
        ("잡아먹", ("oc adm top pod", "top pod", "metrics", "cpu", "memory")),
    )
    if any(
        query_token in normalized_query and any(citation_token in citation_haystack for citation_token in citation_tokens)
        for query_token, citation_tokens in operational_token_pairs
    ):
        return False
    coverage = _citation_token_coverage(query, citations)
    max_fused = _selected_hit_score(selected_hits, "fused_score")
    max_pre_rerank = _selected_hit_score(selected_hits, "pre_rerank_fused_score")
    max_vector = _selected_hit_score(selected_hits, "vector_score")
    has_command_grounding = any(citation.cli_commands for citation in citations)
    if has_command_request(query) and has_command_grounding and coverage >= 0.2:
        return False
    if has_command_request(query) and has_command_grounding and max(max_fused, max_pre_rerank, max_vector) >= 0.02:
        return False
    if any(token in normalized_query for token in ("bootstrap", "부트스트랩")) and any(
        token in citation_haystack
        for token in ("bootstrap-complete", "wait-for bootstrap", "openshift-install", "waiting for the bootstrap")
    ):
        return False
    if _is_install_overview_question(query) and any(
        token in citation_haystack
        for token in (
            "installation_overview",
            "install_modes",
            "installing_on_any_platform",
            "installing_on_bare_metal",
            "installing_with_agent_based_installer",
            "assisted installer",
            "agent-based installer",
            "single-node",
            "single node",
            "openshift-install",
            "설치",
        )
    ):
        return False
    weighted_score = (coverage * 0.62) + (max(max_pre_rerank, max_vector) * 1.8) + (0.12 if max_fused > 0 else 0)
    return coverage < 0.28 and weighted_score < 0.46


def _citation_matches_keywords(citations: list, keywords: tuple[str, ...]) -> bool:
    normalized_keywords = tuple(str(keyword or "").strip().lower() for keyword in keywords if str(keyword or "").strip())
    if not normalized_keywords:
        return False
    for citation in citations:
        haystack = " ".join(
            [
                str(getattr(citation, "book_slug", "") or ""),
                str(getattr(citation, "section", "") or ""),
                str(getattr(citation, "source_label", "") or ""),
                str(getattr(citation, "book_title", "") or ""),
            ]
        ).lower()
        if any(keyword in haystack for keyword in normalized_keywords):
            return True
    return False


def _requires_monitoring_backup_grounding(query: str) -> bool:
    lowered = str(query or "").lower()
    return has_backup_restore_intent(query) and any(token in lowered for token in ("monitoring", "모니터링"))


def _requires_console_grounding(query: str) -> bool:
    lowered = str(query or "").lower()
    return any(token in lowered for token in ("웹 콘솔", "web console", "console"))


def _requires_rbac_grounding(query: str) -> bool:
    lowered = str(query or "").lower()
    return any(
        token in lowered
        for token in (
            "권한",
            "rbac",
            "rolebinding",
            "cluster-admin",
            "clusterrole",
            "cluster role",
        )
    )


def _citations_match_rbac_intent(citations: list) -> bool:
    return _citation_matches_keywords(
        citations,
        (
            "rbac",
            "rolebinding",
            "role binding",
            "authorization",
            "auth can-i",
            "oc auth can-i",
            "can-i",
            "권한",
            "사용자 역할",
            "clusterrole",
            "cluster role",
        ),
    )


def _citations_match_console_intent(citations: list) -> bool:
    for citation in citations:
        haystack = " ".join(
            [
                str(getattr(citation, "book_slug", "") or ""),
                str(getattr(citation, "section", "") or ""),
                str(getattr(citation, "excerpt", "") or ""),
            ]
        ).lower()
        if any(token in haystack for token in ("웹 콘솔", "web console", "console", "콘솔")):
            return True
    return False


def _is_document_sequence_query(query: str) -> bool:
    return _shared_is_document_sequence_query(query)


def _is_supported_ops_learning_question(query: str) -> bool:
    normalized = (query or "").lower()
    if any(
        (
            has_crash_loop_troubleshooting_intent(query),
            has_pod_pending_troubleshooting_intent(query),
            has_rbac_intent(query),
            has_openshift_kubernetes_compare_intent(query),
            has_mco_concept_intent(query),
            has_operator_concept_intent(query),
        )
    ):
        return True
    return any(
        token in normalized
        for token in (
            "oc auth can-i",
            "delete 할 수",
            "pods를 delete",
            "pod를 delete",
            "특정 namespace",
            "securitycontextconstraints",
            "scc",
            "machineconfigpool",
            "machine config pool",
            "clusteroperator",
            "cluster operator",
            "image registry",
            "internal registry",
            "openshift와 kubernetes",
            "kubernetes 차이",
            "pending 상태",
            "crashloopbackoff",
            "view 권한",
            "권한만",
            "업데이트 전에",
            "paused 상태",
            "권한 문제",
        )
    )


def _allow_single_citation_fallback(*, query: str, citations: list) -> bool:
    return bool(citations) and any(
        (
            has_backup_restore_intent(query),
            has_command_request(query),
            has_doc_locator_intent(query),
        )
    )


def _allow_multi_citation_runtime_fallback(*, mode: str, citations: list) -> bool:
    if mode == "learn":
        return False
    if len(citations) < 2:
        return False
    return bool(select_fallback_citations(citations, limit=2))


def _is_standard_etcd_backup_query(query: str) -> bool:
    lowered = str(query or "").lower()
    return (
        has_backup_restore_intent(query)
        and "etcd" in lowered
        and any(token in query for token in ("표준", "표준적", "정석"))
        and not any(token in lowered for token in ("복원", "restore", "recovery"))
    )


def _prune_provenance_noise_citations(*, query: str, citations: list) -> list:
    if not citations:
        return citations

    pruned = list(citations)
    if has_mco_concept_intent(query):
        strong_preferred_books = {
            "machine_configuration",
            "machine_management",
            "operators",
        }
        if any(citation.book_slug in strong_preferred_books for citation in pruned):
            pruned = [citation for citation in pruned if citation.book_slug in strong_preferred_books]
        else:
            preferred_books = {
                "machine_configuration",
                "machine_management",
                "operators",
                "updating_clusters",
                "architecture",
                "overview",
            }
            if any(citation.book_slug in preferred_books for citation in pruned):
                pruned = [citation for citation in pruned if citation.book_slug in preferred_books]

    if _requires_rbac_grounding(query):
        preferred_books = {
            "authentication_and_authorization",
            "cli_tools",
        }
        if any(citation.book_slug in preferred_books for citation in pruned):
            pruned = [citation for citation in pruned if citation.book_slug in preferred_books]

    if _is_standard_etcd_backup_query(query):
        preferred_books = {"postinstallation_configuration", "hosted_control_planes"}
        if any(citation.book_slug in preferred_books for citation in pruned):
            pruned = [citation for citation in pruned if citation.book_slug in preferred_books]

    return pruned or citations


def _is_explanation_query(query: str) -> bool:
    return any(
        (
            is_explainer_query(query),
            is_generic_intro_query(query),
            has_openshift_kubernetes_compare_intent(query),
            has_route_ingress_compare_intent(query),
            has_operator_concept_intent(query),
            has_mco_concept_intent(query),
            has_pod_lifecycle_concept_intent(query),
        )
    )


def _llm_max_tokens_override(*, query: str, default_max_tokens: int) -> int | None:
    if default_max_tokens <= 0 or not _is_explanation_query(query):
        return None
    lowered = str(query or "").lower()
    if any(token in lowered for token in ("한 문단", "한문단", "one paragraph", "single paragraph")):
        return min(default_max_tokens, 192)
    return min(default_max_tokens, 560)


class ChatAnswerer:
    """CLI, UI, eval 파이프라인이 공통으로 쓰는 최상위 answer 서비스."""

    def __init__(
        self,
        settings: Settings,
        retriever: ChatRetriever,
        llm_client: LLMClient,
    ) -> None:
        self.settings = settings
        self.retriever = retriever
        self.llm_client = llm_client

    @classmethod
    def from_settings(cls, settings: Settings) -> "ChatAnswerer":
        llm_client = LLMClient(settings)
        retriever = ChatRetriever.from_settings(settings, enable_vector=True)
        if settings.query_signal_llm_enabled:
            retriever.query_signal_llm_client = llm_client
        return cls(
            settings=settings,
            retriever=retriever,
            llm_client=llm_client,
        )

    def default_log_path(self) -> Path:
        return self.settings.answer_log_path

    def append_log(self, result: AnswerResult, log_path: Path | None = None) -> Path:
        target = log_path or self.default_log_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result.to_dict(), ensure_ascii=False) + "\n")
        return target

    def _build_grounding_blocked_result(
        self,
        *,
        query: str,
        mode: str,
        rewritten_query: str,
        answer: str,
        warnings: list[str],
        retrieval_trace: dict,
        pipeline_events: list[dict],
        pipeline_timings_ms: dict[str, float],
        selected_hits: list[dict] | None = None,
        llm_runtime_meta: dict | None = None,
    ) -> AnswerResult:
        return build_answer_result(
            query=query,
            mode=mode,
            answer=answer,
            rewritten_query=rewritten_query,
            response_kind="no_answer",
            citations=[],
            cited_indices=[],
            warnings=warnings,
            retrieval_trace=retrieval_trace,
            pipeline_events=pipeline_events,
            pipeline_timings_ms=pipeline_timings_ms,
            selected_hits=selected_hits,
            llm_runtime_meta=llm_runtime_meta,
        )

    def answer(
        self,
        query: str,
        *,
        mode: str = "chat",
        context: SessionContext | None = None,
        top_k: int = 5,
        candidate_k: int = 10,
        max_context_chunks: int = 6,
        trace_callback=None,
    ) -> AnswerResult:
        # 모든 사용자 답변에 trace/timing을 남겨 두어, 품질 문제 발생 시
        # 어디서 파이프라인이 흔들렸는지 추측이 아니라 기록으로 좁힐 수 있게 한다.
        answer_started_at = time.perf_counter()
        pipeline_timings_ms: dict[str, float] = {}
        pipeline_events: list[dict] = []

        def emit(event: dict) -> None:
            payload = dict(event)
            payload.setdefault("type", "trace")
            payload.setdefault(
                "timestamp_ms",
                round((time.perf_counter() - answer_started_at) * 1000, 1),
            )
            pipeline_events.append(payload)
            if trace_callback is not None:
                trace_callback(payload)

        route_started_at = time.perf_counter()
        emit(
            {
                "step": "route_query",
                "label": "질문 라우팅 중",
                "status": "running",
                "detail": query[:180],
            }
        )
        is_follow_up = has_follow_up_reference(query)
        routed_response = None
        if not is_follow_up:
            routed_response = route_non_rag(
                query,
                corpus_label=self.settings.active_pack.product_label,
                corpus_version=self.settings.active_pack.version,
            )
        pipeline_timings_ms["route_query"] = round(
            (time.perf_counter() - route_started_at) * 1000,
            1,
        )
        if routed_response is not None:
            emit(
                {
                    "step": "route_query",
                    "label": "질문 라우팅 완료",
                    "status": "done",
                    "detail": f"non-rag route={routed_response.route}",
                    "duration_ms": pipeline_timings_ms["route_query"],
                }
            )
            pipeline_timings_ms["total"] = round(
                (time.perf_counter() - answer_started_at) * 1000,
                1,
            )
            emit(
                {
                    "step": "pipeline_complete",
                    "label": "답변 생성 완료",
                    "status": "done",
                    "detail": f"총 {pipeline_timings_ms['total']}ms",
                    "duration_ms": pipeline_timings_ms["total"],
                }
            )
            return build_answer_result(
                query=query,
                mode=mode,
                answer=routed_response.answer.strip(),
                rewritten_query=query,
                response_kind=routed_response.route,
                citations=[],
                cited_indices=[],
                warnings=[],
                retrieval_trace={"route": routed_response.route, "warnings": []},
                pipeline_events=pipeline_events,
                pipeline_timings_ms=pipeline_timings_ms,
            )

        if is_follow_up and has_follow_up_entity_ambiguity(query, context):
            answer_text = build_follow_up_clarification_answer(context)
            pipeline_timings_ms["total"] = round(
                (time.perf_counter() - answer_started_at) * 1000,
                1,
            )
            emit(
                {
                    "step": "route_query",
                    "label": "질문 라우팅 완료",
                    "status": "done",
                    "detail": "follow-up clarification",
                    "duration_ms": pipeline_timings_ms["route_query"],
                }
            )
            emit(
                {
                    "step": "pipeline_complete",
                    "label": "답변 생성 완료",
                    "status": "done",
                    "detail": f"총 {pipeline_timings_ms['total']}ms",
                    "duration_ms": pipeline_timings_ms["total"],
                }
            )
            return build_answer_result(
                query=query,
                mode=mode,
                answer=answer_text,
                rewritten_query=query,
                response_kind="clarification",
                citations=[],
                cited_indices=[],
                warnings=[],
                retrieval_trace={"route": "follow_up_clarification", "warnings": []},
                pipeline_events=pipeline_events,
                pipeline_timings_ms=pipeline_timings_ms,
            )

        emit(
            {
                "step": "route_query",
                "label": "질문 라우팅 완료",
                "status": "done",
                "detail": "rag",
                "duration_ms": pipeline_timings_ms["route_query"],
            }
        )
        emit(
            {
                "step": "retrieval",
                "label": "근거 검색 시작",
                "status": "running",
                "detail": query[:180],
            }
        )
        retrieval_started_at = time.perf_counter()
        retrieval = self.retriever.retrieve(
            query,
            context=context,
            top_k=top_k,
            candidate_k=candidate_k,
            trace_callback=emit,
        )
        pipeline_timings_ms["retrieval_total"] = round(
            (time.perf_counter() - retrieval_started_at) * 1000,
            1,
        )
        emit(
            {
                "step": "retrieval",
                "label": "근거 검색 완료",
                "status": "done",
                "detail": f"상위 근거 {len(retrieval.hits)}개",
                "duration_ms": pipeline_timings_ms["retrieval_total"],
            }
        )

        context_started_at = time.perf_counter()
        emit(
            {
                "step": "context_assembly",
                "label": "citation 컨텍스트 조립 중",
                "status": "running",
            }
        )
        context_bundle = assemble_context(
            retrieval.hits,
            query=query,
            session_context=context,
            root_dir=self.settings.root_dir,
            max_chunks=max_context_chunks,
        )
        pipeline_timings_ms["context_assembly"] = round(
            (time.perf_counter() - context_started_at) * 1000,
            1,
        )
        emit(
            {
                "step": "context_assembly",
                "label": "citation 컨텍스트 조립 완료",
                "status": "done",
                "detail": f"citation {len(context_bundle.citations)}개",
                "duration_ms": pipeline_timings_ms["context_assembly"],
                "meta": {
                    "selected": len(context_bundle.citations),
                    "selected_hits": summarize_selected_citations(
                        context_bundle.citations,
                        retrieval.hits,
                    ),
                },
            }
        )
        warnings: list[str] = []
        if not context_bundle.citations:
            warnings.append("no context citations assembled")
            clarification_hits = _retrieval_hits_for_clarification(retrieval.hits)
            emit(
                {
                    "step": "grounding_guard",
                    "label": "근거 검증 차단",
                    "status": "error",
                    "detail": "선택된 citation이 없습니다",
                }
            )
            pipeline_timings_ms["total"] = round(
                (time.perf_counter() - answer_started_at) * 1000,
                1,
            )
            emit(
                {
                    "step": "pipeline_complete",
                    "label": "답변 생성 중단",
                    "status": "done",
                    "detail": f"총 {pipeline_timings_ms['total']}ms",
                    "duration_ms": pipeline_timings_ms["total"],
                }
            )
            if clarification_hits and not _is_guided_learning_question(query):
                warnings.append("low retrieval confidence")
                return build_answer_result(
                    query=query,
                    mode=mode,
                    answer=_low_confidence_clarification_answer(selected_hits=clarification_hits),
                    rewritten_query=retrieval.rewritten_query,
                    response_kind="clarification",
                    citations=[],
                    cited_indices=[],
                    warnings=warnings,
                    retrieval_trace=retrieval.trace,
                    pipeline_events=pipeline_events,
                    pipeline_timings_ms=pipeline_timings_ms,
                    selected_hits=clarification_hits,
                )
            return self._build_grounding_blocked_result(
                query=query,
                mode=mode,
                rewritten_query=retrieval.rewritten_query,
                answer=(
                    "답변: 현재 Playbook Library에 해당 자료가 없습니다. "
                    "자료 추가가 필요합니다."
                ),
                warnings=warnings,
                retrieval_trace=retrieval.trace,
                pipeline_events=pipeline_events,
                pipeline_timings_ms=pipeline_timings_ms,
            )
        selected_hits = summarize_selected_citations(
            context_bundle.citations,
            retrieval.hits,
        )
        actionable_command_query = has_command_request(query) or has_corrective_follow_up(query)
        if actionable_command_query and not has_sufficient_command_grounding(
            query=query,
            citations=context_bundle.citations,
        ):
            warnings.append("insufficient command grounding coverage")
            emit(
                {
                    "step": "grounding_guard",
                    "label": "근거 검증 차단",
                    "status": "error",
                    "detail": "명령형 질문을 뒷받침하는 근거 범위가 부족합니다",
                }
            )
            pipeline_timings_ms["total"] = round(
                (time.perf_counter() - answer_started_at) * 1000,
                1,
            )
            emit(
                {
                    "step": "pipeline_complete",
                    "label": "답변 생성 중단",
                    "status": "done",
                    "detail": f"총 {pipeline_timings_ms['total']}ms",
                    "duration_ms": pipeline_timings_ms["total"],
                }
            )
            return self._build_grounding_blocked_result(
                query=query,
                mode=mode,
                rewritten_query=retrieval.rewritten_query,
                answer=(
                    "답변: 현재 Playbook Library에 해당 자료가 없습니다. "
                    "자료 추가가 필요합니다."
                ),
                warnings=warnings,
                retrieval_trace=retrieval.trace,
                pipeline_events=pipeline_events,
                pipeline_timings_ms=pipeline_timings_ms,
                selected_hits=selected_hits,
            )
        if _requires_monitoring_backup_grounding(query) and not _citation_matches_keywords(
            context_bundle.citations,
            ("monitoring", "모니터링", "backup_and_restore", "백업", "복원"),
        ):
            warnings.append("insufficient monitoring/backup grounding coverage")
            emit(
                {
                    "step": "grounding_guard",
                    "label": "근거 검증 차단",
                    "status": "error",
                    "detail": "비교형 질문을 뒷받침하는 monitoring/backup 근거가 부족합니다",
                }
            )
            pipeline_timings_ms["total"] = round(
                (time.perf_counter() - answer_started_at) * 1000,
                1,
            )
            emit(
                {
                    "step": "pipeline_complete",
                    "label": "답변 생성 중단",
                    "status": "done",
                    "detail": f"총 {pipeline_timings_ms['total']}ms",
                    "duration_ms": pipeline_timings_ms["total"],
                }
            )
            return self._build_grounding_blocked_result(
                query=query,
                mode=mode,
                rewritten_query=retrieval.rewritten_query,
                answer=(
                    "답변: 현재 Playbook Library에 해당 자료가 없습니다. "
                    "자료 추가가 필요합니다."
                ),
                warnings=warnings,
                retrieval_trace=retrieval.trace,
                pipeline_events=pipeline_events,
                pipeline_timings_ms=pipeline_timings_ms,
                selected_hits=selected_hits,
            )

        if _is_low_confidence_retrieval(
            query=query,
            citations=context_bundle.citations,
            selected_hits=selected_hits,
        ):
            warnings.append("low retrieval confidence")
            emit(
                {
                    "step": "grounding_guard",
                    "label": "근거 점수 낮음",
                    "status": "warning",
                    "detail": "질문과 선택 citation의 토큰/점수 결합 신뢰도가 낮습니다",
                }
            )
            pipeline_timings_ms["total"] = round(
                (time.perf_counter() - answer_started_at) * 1000,
                1,
            )
            emit(
                {
                    "step": "pipeline_complete",
                    "label": "구체화 요청으로 전환",
                    "status": "done",
                    "detail": f"총 {pipeline_timings_ms['total']}ms",
                    "duration_ms": pipeline_timings_ms["total"],
                }
            )
            return build_answer_result(
                query=query,
                mode=mode,
                answer=_low_confidence_clarification_answer(selected_hits=selected_hits),
                rewritten_query=retrieval.rewritten_query,
                response_kind="clarification",
                citations=[],
                cited_indices=[],
                warnings=warnings,
                retrieval_trace=retrieval.trace,
                pipeline_events=pipeline_events,
                pipeline_timings_ms=pipeline_timings_ms,
                selected_hits=selected_hits,
            )

        answer_text = ""
        llm_runtime_meta: dict[str, object]
        prompt_started_at = time.perf_counter()
        emit(
            {
                "step": "prompt_build",
                "label": "프롬프트 조립 중",
                "status": "running",
            }
        )
        messages = build_messages(
            query=query,
            mode=mode,
            context_bundle=context_bundle,
            session_summary=summarize_session_context(context),
        )
        pipeline_timings_ms["prompt_build"] = round(
            (time.perf_counter() - prompt_started_at) * 1000,
            1,
        )
        emit(
            {
                "step": "prompt_build",
                "label": "프롬프트 조립 완료",
                "status": "done",
                "detail": f"messages {len(messages)}개",
                "duration_ms": pipeline_timings_ms["prompt_build"],
            }
        )

        llm_started_at = time.perf_counter()
        max_tokens_override = _llm_max_tokens_override(
            query=query,
            default_max_tokens=self.settings.llm_max_tokens,
        )
        answer_text, llm_runtime_meta, llm_phase_timings = generate_grounded_answer_text(
            self.llm_client,
            messages,
            query=query,
            mode=mode,
            citations=context_bundle.citations,
            trace_callback=emit,
            max_tokens_override=max_tokens_override,
        )
        pipeline_timings_ms["llm_generate_total"] = round(
            (time.perf_counter() - llm_started_at) * 1000,
            1,
        )
        pipeline_timings_ms["llm_provider_round_trip"] = llm_phase_timings["llm_provider_round_trip"]
        pipeline_timings_ms["llm_post_process"] = llm_phase_timings["llm_post_process"]
        emit(
            {
                "step": "llm_runtime",
                "label": "LLM 런타임 확인",
                "status": "done",
                "detail": (
                    f"provider={llm_runtime_meta.get('last_provider') or llm_runtime_meta.get('preferred_provider')} "
                    f"fallback={str(bool(llm_runtime_meta.get('last_fallback_used', False))).lower()}"
                ),
                "meta": llm_runtime_meta,
            }
        )

        finalize_started_at = time.perf_counter()
        emit(
            {
                "step": "citation_finalize",
                "label": "citation 정리 중",
                "status": "running",
            }
        )
        answer_text, final_citations, cited_indices = finalize_citations(
            answer_text,
            context_bundle.citations,
        )
        final_citations = preserve_explicit_mixed_runtime_citations(
            query,
            selected_citations=context_bundle.citations,
            final_citations=final_citations,
        )
        pruned_citations = _prune_provenance_noise_citations(
            query=query,
            citations=final_citations,
        )
        if len(pruned_citations) != len(final_citations):
            answer_text, final_citations, cited_indices = finalize_citations(
                answer_text,
                pruned_citations,
            )
        else:
            final_citations = pruned_citations
        if not cited_indices and final_citations and _allow_single_citation_fallback(
            query=query,
            citations=final_citations,
        ):
            answer_text = inject_single_citation(answer_text, citation_index=1)
            answer_text, final_citations, cited_indices = finalize_citations(
                answer_text,
                final_citations,
            )
        if (
            not cited_indices
            and _allow_multi_citation_runtime_fallback(
                mode=mode,
                citations=context_bundle.citations,
            )
            and not _looks_like_missing_coverage_answer(answer_text)
        ):
            fallback_citations = select_fallback_citations(
                final_citations or context_bundle.citations,
                limit=2,
            )
            if fallback_citations:
                answer_text = inject_citation_indices(
                    answer_text,
                    citation_indices=list(range(1, len(fallback_citations) + 1)),
                )
                answer_text, final_citations, cited_indices = finalize_citations(
                    answer_text,
                    fallback_citations,
                )
        guarded_answer_text = strip_ungrounded_code_blocks(
            answer_text,
            citations=final_citations or context_bundle.citations,
        )
        if guarded_answer_text != answer_text:
            answer_text = guarded_answer_text
            answer_text, final_citations, cited_indices = finalize_citations(
                answer_text,
                final_citations or context_bundle.citations,
            )
        if not cited_indices:
            warnings.append("answer has no inline citations")
        pipeline_timings_ms["citation_finalize"] = round(
            (time.perf_counter() - finalize_started_at) * 1000,
            1,
        )
        emit(
            {
                "step": "citation_finalize",
                "label": "citation 정리 완료",
                "status": "done",
                "detail": f"최종 citation {len(final_citations)}개",
                "duration_ms": pipeline_timings_ms["citation_finalize"],
            }
        )
        if not cited_indices:
            emit(
                {
                    "step": "grounding_guard",
                    "label": "근거 검증 차단",
                    "status": "error",
                    "detail": "생성 답변에 inline citation이 없습니다",
                }
            )
            pipeline_timings_ms["total"] = round(
                (time.perf_counter() - answer_started_at) * 1000,
                1,
            )
            emit(
                {
                    "step": "pipeline_complete",
                    "label": "답변 생성 중단",
                    "status": "done",
                    "detail": f"총 {pipeline_timings_ms['total']}ms",
                    "duration_ms": pipeline_timings_ms["total"],
                }
            )
            return self._build_grounding_blocked_result(
                query=query,
                mode=mode,
                rewritten_query=retrieval.rewritten_query,
                answer=(
                    "답변: 현재 Playbook Library에 해당 자료가 없습니다. "
                    "자료 추가가 필요합니다."
                ),
                warnings=warnings,
                retrieval_trace=retrieval.trace,
                pipeline_events=pipeline_events,
                pipeline_timings_ms=pipeline_timings_ms,
                selected_hits=selected_hits,
                llm_runtime_meta=llm_runtime_meta,
            )
        if _requires_console_grounding(query) and not _citations_match_console_intent(final_citations):
            warnings.append("insufficient web console grounding coverage")
            emit(
                {
                    "step": "grounding_guard",
                    "label": "근거 검증 차단",
                    "status": "error",
                    "detail": "웹 콘솔 질문을 뒷받침하는 근거가 부족합니다",
                }
            )
            pipeline_timings_ms["total"] = round(
                (time.perf_counter() - answer_started_at) * 1000,
                1,
            )
            emit(
                {
                    "step": "pipeline_complete",
                    "label": "답변 생성 중단",
                    "status": "done",
                    "detail": f"총 {pipeline_timings_ms['total']}ms",
                    "duration_ms": pipeline_timings_ms["total"],
                }
            )
            return self._build_grounding_blocked_result(
                query=query,
                mode=mode,
                rewritten_query=retrieval.rewritten_query,
                answer=(
                    "답변: 현재 Playbook Library에 해당 자료가 없습니다. "
                    "자료 추가가 필요합니다."
                ),
                warnings=warnings,
                retrieval_trace=retrieval.trace,
                pipeline_events=pipeline_events,
                pipeline_timings_ms=pipeline_timings_ms,
                selected_hits=selected_hits,
                llm_runtime_meta=llm_runtime_meta,
            )
        if _requires_rbac_grounding(query) and not _citations_match_rbac_intent(final_citations):
            warnings.append("insufficient rbac grounding coverage")
            emit(
                {
                    "step": "grounding_guard",
                    "label": "근거 검증 차단",
                    "status": "error",
                    "detail": "RBAC 질문을 뒷받침하는 근거가 부족합니다",
                }
            )
            pipeline_timings_ms["total"] = round(
                (time.perf_counter() - answer_started_at) * 1000,
                1,
            )
            emit(
                {
                    "step": "pipeline_complete",
                    "label": "답변 생성 중단",
                    "status": "done",
                    "detail": f"총 {pipeline_timings_ms['total']}ms",
                    "duration_ms": pipeline_timings_ms["total"],
                }
            )
            return self._build_grounding_blocked_result(
                query=query,
                mode=mode,
                rewritten_query=retrieval.rewritten_query,
                answer=(
                    "답변: 현재 Playbook Library에 해당 자료가 없습니다. "
                    "자료 추가가 필요합니다."
                ),
                warnings=warnings,
                retrieval_trace=retrieval.trace,
                pipeline_events=pipeline_events,
                pipeline_timings_ms=pipeline_timings_ms,
                selected_hits=selected_hits,
                llm_runtime_meta=llm_runtime_meta,
            )

        if _looks_like_missing_coverage_answer(answer_text):
            warnings.append("answer indicates missing corpus coverage")
            emit(
                {
                    "step": "grounding_guard",
                    "label": "근거 범위 차단",
                    "status": "error",
                    "detail": "생성 답변이 코퍼스 부재를 직접 인정했습니다",
                }
            )
            pipeline_timings_ms["total"] = round(
                (time.perf_counter() - answer_started_at) * 1000,
                1,
            )
            emit(
                {
                    "step": "pipeline_complete",
                    "label": "답변 생성 중단",
                    "status": "done",
                    "detail": f"총 {pipeline_timings_ms['total']}ms",
                    "duration_ms": pipeline_timings_ms["total"],
                }
            )
            return self._build_grounding_blocked_result(
                query=query,
                mode=mode,
                rewritten_query=retrieval.rewritten_query,
                answer=(
                    "답변: 현재 Playbook Library에 해당 자료가 없습니다. "
                    "자료 추가가 필요합니다."
                ),
                warnings=warnings,
                retrieval_trace=retrieval.trace,
                pipeline_events=pipeline_events,
                pipeline_timings_ms=pipeline_timings_ms,
                selected_hits=selected_hits,
                llm_runtime_meta=llm_runtime_meta,
            )

        pipeline_timings_ms["total"] = round(
            (time.perf_counter() - answer_started_at) * 1000,
            1,
        )
        emit(
            {
                "step": "pipeline_complete",
                "label": "답변 생성 완료",
                "status": "done",
                "detail": f"총 {pipeline_timings_ms['total']}ms",
                "duration_ms": pipeline_timings_ms["total"],
            }
        )

        result = build_answer_result(
            query=query,
            mode=mode,
            answer=answer_text,
            rewritten_query=retrieval.rewritten_query,
            response_kind="rag",
            citations=final_citations,
            cited_indices=cited_indices,
            warnings=warnings,
            retrieval_trace=retrieval.trace,
            pipeline_events=pipeline_events,
            pipeline_timings_ms=pipeline_timings_ms,
            selected_hits=selected_hits,
            llm_runtime_meta=llm_runtime_meta,
        )
        return result
