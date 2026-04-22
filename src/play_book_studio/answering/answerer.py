"""grounded answer 전체를 오케스트레이션한다.

이 모듈이 채팅 제품의 런타임 spine이다:
retrieve -> assemble context -> prompt -> LLM -> answer shaping -> citations
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from play_book_studio.config.settings import Settings
from play_book_studio.retrieval import ChatRetriever, SessionContext
from play_book_studio.retrieval.query import (
    has_backup_restore_intent,
    has_cluster_node_usage_intent,
    has_command_request,
    has_corrective_follow_up,
    has_deployment_scaling_intent,
    has_doc_locator_intent,
    has_follow_up_entity_ambiguity,
    has_follow_up_reference,
    has_mco_concept_intent,
    has_node_drain_intent,
    has_openshift_kubernetes_compare_intent,
    has_operator_concept_intent,
    has_pod_lifecycle_concept_intent,
    has_rbac_intent,
    has_route_ingress_compare_intent,
    is_explainer_query,
    is_generic_intro_query,
)

from .answer_text_commands import (
    build_deployment_scaling_answer,
    build_grounded_command_guide_answer,
    has_sufficient_command_grounding,
    shape_etcd_backup_answer,
)
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
from .llm import LLMClient
from .models import AnswerResult, Citation
from .pipeline_helpers import (
    build_answer_result,
    build_follow_up_clarification_answer,
    finalize_deployment_scaling_answer,
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


def _build_doc_locator_answer(*, query: str, citations: list) -> str | None:
    if not citations or not has_doc_locator_intent(query):
        return None
    if any(
        (
            has_command_request(query),
            has_corrective_follow_up(query),
            has_backup_restore_intent(query),
            has_cluster_node_usage_intent(query),
            has_node_drain_intent(query),
            has_rbac_intent(query),
            has_deployment_scaling_intent(query),
            has_openshift_kubernetes_compare_intent(query),
        )
    ):
        return None
    if _requires_console_grounding(query) and not _citations_match_console_intent(citations):
        return None
    if _requires_rbac_grounding(query) and not _citations_match_rbac_intent(citations):
        return None
    primary = citations[0]
    section_label = str(getattr(primary, "section_path_label", "") or getattr(primary, "section", "") or "").strip()
    if not section_label:
        return None
    lowered = str(query or "").lower()
    follow_up = ""
    if any(token in lowered for token in ("시작", "먼저", "first")):
        follow_up = " 이 경로를 먼저 열고 같은 문서 안의 절차를 순서대로 따라가면 됩니다 [1]."
    elif any(token in lowered for token in ("순서", "이동", "흐름", "route")):
        follow_up = " 이 경로를 먼저 열고 문제 해결 섹션을 순서대로 따라가면 됩니다 [1]."
    elif any(token in lowered for token in ("경로", "path", "route")):
        follow_up = " 이 경로를 기준으로 연결 문서와 다음 절차를 이어가면 됩니다 [1]."
    return f"답변: 먼저 `{section_label}` 문서를 여는 것이 맞습니다 [1].{follow_up}"


INTRO_PLAYBOOK_ROUTE = (
    {
        "book_slug": "overview",
        "book_title": "개요",
        "viewer_path": "/playbooks/wiki-runtime/active/overview/index.html",
        "source_url": "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/html-single/overview/index",
        "source_label": "개요",
        "section": "개요",
    },
    {
        "book_slug": "architecture",
        "book_title": "아키텍처",
        "viewer_path": "/playbooks/wiki-runtime/active/architecture/index.html",
        "source_url": "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/html-single/architecture/index",
        "source_label": "아키텍처",
        "section": "아키텍처",
    },
    {
        "book_slug": "operators",
        "book_title": "Operator 운영 플레이북",
        "viewer_path": "/playbooks/wiki-runtime/active/operators/index.html",
        "source_url": "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/html-single/operators/index",
        "source_label": "Operator 운영 플레이북",
        "section": "Operator 운영 플레이북",
    },
)


def _has_intro_playbook_route_intent(query: str) -> bool:
    normalized = " ".join(str(query or "").split()).lower()
    if not normalized:
        return False
    has_pack_target = any(token in normalized for token in ("플레이북", "playbook", "문서"))
    has_intro_signal = any(token in normalized for token in ("입문", "처음", "먼저", "start"))
    has_count_signal = any(token in normalized for token in ("3개", "세 개", "3권", "세 권", "top 3"))
    has_route_signal = any(token in normalized for token in ("봐야", "읽", "추천", "알려줘", "추천해"))
    return has_pack_target and has_intro_signal and has_count_signal and has_route_signal


def _build_intro_playbook_route_citations() -> list[Citation]:
    citations: list[Citation] = []
    for index, item in enumerate(INTRO_PLAYBOOK_ROUTE, start=1):
        citations.append(
            Citation(
                index=index,
                chunk_id=f"intro-playbook-route-{item['book_slug']}",
                book_slug=item["book_slug"],
                section=item["section"],
                anchor="",
                source_url=item["source_url"],
                viewer_path=item["viewer_path"],
                excerpt="운영 입문용 기본 Playbook route",
                section_path=(item["section"],),
                section_path_label=item["section"],
                chunk_type="concept",
                semantic_role="guide",
                source_collection="core",
            )
        )
    return citations


def _build_intro_playbook_route_answer(query: str) -> tuple[str, list[Citation]] | None:
    if not _has_intro_playbook_route_intent(query):
        return None
    citations = _build_intro_playbook_route_citations()
    answer = (
        "답변: 운영 입문이면 아래 3권 순서로 시작하는 게 가장 자연스럽습니다.\n\n"
        "1. `개요`부터 엽니다. 제품 범위와 기본 용어를 먼저 잡는 단계입니다 [1].\n"
        "2. `아키텍처`로 넘어갑니다. 클러스터 구성과 핵심 컴포넌트가 어떻게 맞물리는지 이해하는 단계입니다 [2].\n"
        "3. `Operator 운영 플레이북`으로 마무리합니다. 실제 운영 흐름을 붙이기 좋은 출발점입니다 [3].\n\n"
        "읽는 순서도 그대로 `개요 -> 아키텍처 -> Operator 운영 플레이북`으로 가면 됩니다 [1] [2] [3]."
    )
    return answer, citations


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


def _deterministic_llm_runtime_meta(*, provider: str) -> dict[str, object]:
    return {
        "preferred_provider": provider,
        "fallback_enabled": False,
        "last_provider": provider,
        "last_fallback_used": False,
        "last_attempted_providers": [provider],
        "last_requested_max_tokens": 0,
        "provider_round_trip_ms": 0.0,
        "post_process_ms": 0.0,
        "raw_output_chars": 0,
        "final_output_chars": 0,
        "requested_max_tokens": 0,
    }


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
    return min(default_max_tokens, 256)


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
        return cls(
            settings=settings,
            retriever=ChatRetriever.from_settings(settings, enable_vector=True),
            llm_client=LLMClient(settings),
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
        candidate_k: int = 20,
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

        intro_playbook_route = _build_intro_playbook_route_answer(query)
        if intro_playbook_route is not None:
            answer_text, route_citations = intro_playbook_route
            answer_text, final_citations, cited_indices = finalize_citations(
                answer_text,
                route_citations,
            )
            pipeline_timings_ms["total"] = round(
                (time.perf_counter() - answer_started_at) * 1000,
                1,
            )
            emit(
                {
                    "step": "deterministic_answer",
                    "label": "입문 Playbook route 정리 완료",
                    "status": "done",
                    "detail": f"추천 3권, 총 {pipeline_timings_ms['total']}ms",
                    "duration_ms": pipeline_timings_ms["total"],
                }
            )
            return build_answer_result(
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
            )

        doc_locator_answer = _build_doc_locator_answer(
            query=query,
            citations=context_bundle.citations,
        )
        if doc_locator_answer is not None:
            answer_text, final_citations, cited_indices = finalize_deployment_scaling_answer(
                doc_locator_answer,
                context_bundle.citations,
            )
            pipeline_timings_ms["total"] = round(
                (time.perf_counter() - answer_started_at) * 1000,
                1,
            )
            emit(
                {
                    "step": "deterministic_answer",
                    "label": "문서 경로 답변 생성 완료",
                    "status": "done",
                    "detail": "doc locator",
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
                rewritten_query=retrieval.rewritten_query,
                response_kind="rag",
                citations=final_citations,
                cited_indices=cited_indices,
                warnings=warnings,
                retrieval_trace=retrieval.trace,
                pipeline_events=pipeline_events,
                pipeline_timings_ms=pipeline_timings_ms,
                selected_hits=selected_hits,
            )

        deployment_scaling_answer = build_deployment_scaling_answer(
            query=query,
            context=context,
            citations=context_bundle.citations,
        )
        if deployment_scaling_answer is not None:
            answer_text = deployment_scaling_answer
            answer_text, final_citations, cited_indices = finalize_deployment_scaling_answer(
                answer_text,
                context_bundle.citations,
            )
            pipeline_timings_ms["total"] = round(
                (time.perf_counter() - answer_started_at) * 1000,
                1,
            )
            emit(
                {
                    "step": "deterministic_answer",
                    "label": "전용 명령 답변 생성 완료",
                    "status": "done",
                    "detail": "deployment scaling",
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
                rewritten_query=retrieval.rewritten_query,
                response_kind="clarification" if "숫자가 현재 질문에 없습니다" in answer_text else "rag",
                citations=final_citations,
                cited_indices=cited_indices,
                warnings=warnings,
                retrieval_trace=retrieval.trace,
                pipeline_events=pipeline_events,
                pipeline_timings_ms=pipeline_timings_ms,
                selected_hits=selected_hits,
            )

        grounded_command_answer = build_grounded_command_guide_answer(
            query=query,
            citations=context_bundle.citations,
        )
        if grounded_command_answer is not None:
            answer_text, final_citations, cited_indices = finalize_deployment_scaling_answer(
                grounded_command_answer,
                context_bundle.citations,
            )
            pipeline_timings_ms["total"] = round(
                (time.perf_counter() - answer_started_at) * 1000,
                1,
            )
            emit(
                {
                    "step": "deterministic_answer",
                    "label": "명령 우선 답변 생성 완료",
                    "status": "done",
                    "detail": "grounded command guide",
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
                rewritten_query=retrieval.rewritten_query,
                response_kind="rag",
                citations=final_citations,
                cited_indices=cited_indices,
                warnings=warnings,
                retrieval_trace=retrieval.trace,
                pipeline_events=pipeline_events,
                pipeline_timings_ms=pipeline_timings_ms,
                selected_hits=selected_hits,
            )

        answer_text = ""
        llm_runtime_meta: dict[str, object]
        etcd_fast_path_answer = ""
        if has_backup_restore_intent(query):
            etcd_fast_path_answer = shape_etcd_backup_answer(
                "",
                query=query,
                citations=context_bundle.citations,
            )

        if etcd_fast_path_answer:
            answer_text = etcd_fast_path_answer
            pipeline_timings_ms["prompt_build"] = 0.0
            pipeline_timings_ms["llm_generate_total"] = 0.0
            pipeline_timings_ms["llm_provider_round_trip"] = 0.0
            pipeline_timings_ms["llm_post_process"] = 0.0
            llm_runtime_meta = _deterministic_llm_runtime_meta(
                provider="deterministic-fast-path",
            )
            emit(
                {
                    "step": "deterministic_answer",
                    "label": "전용 절차 답변 생성 완료",
                    "status": "done",
                    "detail": "pre-llm etcd backup/restore fast path",
                }
            )
            emit(
                {
                    "step": "prompt_build",
                    "label": "프롬프트 조립 생략",
                    "status": "done",
                    "detail": "deterministic etcd backup/restore fast path",
                    "duration_ms": pipeline_timings_ms["prompt_build"],
                }
            )
            emit(
                {
                    "step": "llm_runtime",
                    "label": "LLM 호출 생략",
                    "status": "done",
                    "detail": (
                        f"provider={llm_runtime_meta.get('last_provider') or llm_runtime_meta.get('preferred_provider')} "
                        f"fallback={str(bool(llm_runtime_meta.get('last_fallback_used', False))).lower()}"
                    ),
                    "meta": llm_runtime_meta,
                }
            )
        else:
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
