"""answerer의 중간 결과 조립과 후처리를 보조한다."""

from __future__ import annotations

import time
from typing import Any

from play_book_studio.retrieval import SessionContext

from .answer_text import (
    align_answer_to_grounded_commands,
    ensure_korean_product_terms,
    guard_first_step_grounding,
    normalize_answer_markup_blocks,
    normalize_answer_text,
    restore_readable_paragraphs,
    reshape_ops_answer_text,
    shape_actionable_ops_answer,
    shape_rbac_follow_up_answer,
    shape_certificate_monitor_answer,
    shape_etcd_backup_answer,
    shape_project_termination_answer,
    shape_pod_lifecycle_explainer,
    shape_pod_pending_troubleshooting,
    strip_intro_offtopic_noise,
    strip_structured_key_extra_guidance,
    strip_weak_additional_guidance,
    trim_productization_noise,
)
from .citations import (
    finalize_citations,
    inject_single_citation,
    select_fallback_citations,
)
from .models import AnswerResult


def build_follow_up_clarification_answer(context: SessionContext | None) -> str:
    leading_entities = [entity for entity in (context.open_entities if context else []) if str(entity).strip()][:2]
    if len(leading_entities) == 2:
        scope_hint = f"{leading_entities[0]} 쪽인지, {leading_entities[1]} 쪽인지"
    else:
        scope_hint = "어느 항목을 가리키는지"
    return (
        "답변: 지금은 열린 주제가 둘 이상이라 어느 설정을 말씀하시는지 먼저 정해야 합니다. "
        f"{scope_hint} 먼저 확인해 주시겠어요?"
    )


def generate_grounded_answer_text(
    llm_client,
    messages: list[dict[str, str]],
    *,
    query: str,
    mode: str,
    citations: list[dict],
    trace_callback=None,
    max_tokens_override: int | None = None,
) -> tuple[str, dict[str, Any], dict[str, float]]:
    provider_started_at = time.perf_counter()
    try:
        if max_tokens_override is not None:
            raw_answer_text = llm_client.generate(
                messages,
                trace_callback=trace_callback,
                max_tokens=max_tokens_override,
            )
        else:
            raw_answer_text = llm_client.generate(messages, trace_callback=trace_callback)
    except TypeError:
        raw_answer_text = llm_client.generate(messages, trace_callback=trace_callback)
    provider_round_trip_ms = round(
        (time.perf_counter() - provider_started_at) * 1000,
        1,
    )

    post_process_started_at = time.perf_counter()
    answer_text = reshape_ops_answer_text(
        normalize_answer_text(
            normalize_answer_markup_blocks(raw_answer_text)
        ),
        mode=mode,
    )
    answer_text = ensure_korean_product_terms(answer_text, query=query)
    answer_text = align_answer_to_grounded_commands(
        answer_text,
        query=query,
        citations=citations,
    )
    answer_text = shape_rbac_follow_up_answer(
        answer_text,
        query=query,
        citations=citations,
    )
    answer_text = shape_etcd_backup_answer(
        answer_text,
        query=query,
        citations=citations,
    )
    answer_text = shape_project_termination_answer(
        answer_text,
        query=query,
        citations=citations,
    )
    answer_text = shape_certificate_monitor_answer(
        answer_text,
        query=query,
        citations=citations,
    )
    answer_text = shape_actionable_ops_answer(
        answer_text,
        query=query,
        citations=citations,
    )
    answer_text = guard_first_step_grounding(
        answer_text,
        query=query,
        citations=citations,
    )
    answer_text = shape_pod_lifecycle_explainer(
        answer_text,
        query=query,
        mode=mode,
        citations=citations,
    )
    answer_text = shape_pod_pending_troubleshooting(
        answer_text,
        query=query,
        mode=mode,
        citations=citations,
    )
    answer_text = strip_weak_additional_guidance(
        answer_text,
        mode=mode,
        citations=citations,
    )
    answer_text = strip_structured_key_extra_guidance(
        answer_text,
        query=query,
        mode=mode,
    )
    answer_text = trim_productization_noise(answer_text)
    answer_text = strip_intro_offtopic_noise(answer_text, query=query)
    answer_text = restore_readable_paragraphs(answer_text)
    llm_runtime_meta = (
        llm_client.runtime_metadata()
        if hasattr(llm_client, "runtime_metadata")
        else {
            "preferred_provider": "unknown",
            "fallback_enabled": False,
            "last_provider": None,
            "last_fallback_used": False,
            "last_attempted_providers": [],
        }
    )
    post_process_ms = round(
        (time.perf_counter() - post_process_started_at) * 1000,
        1,
    )
    llm_runtime_meta = {
        **llm_runtime_meta,
        "provider_round_trip_ms": provider_round_trip_ms,
        "post_process_ms": post_process_ms,
        "raw_output_chars": len(raw_answer_text),
        "final_output_chars": len(answer_text),
        "requested_max_tokens": (
            max_tokens_override
            if max_tokens_override is not None
            else llm_runtime_meta.get("last_requested_max_tokens", getattr(llm_client, "max_tokens", None))
        ),
    }
    return answer_text, llm_runtime_meta, {
        "llm_provider_round_trip": provider_round_trip_ms,
        "llm_post_process": post_process_ms,
    }


def finalize_deployment_scaling_answer(
    answer_text: str,
    citations: list[dict],
) -> tuple[str, list[dict], list[int]]:
    final_citations = select_fallback_citations(citations, limit=1)
    answer_text, final_citations, cited_indices = finalize_citations(
        answer_text,
        final_citations,
    )
    if not cited_indices and final_citations:
        answer_text = inject_single_citation(answer_text, citation_index=1)
        answer_text, final_citations, cited_indices = finalize_citations(
            answer_text,
            final_citations,
        )
    return answer_text, final_citations, cited_indices


def build_answer_result(
    *,
    query: str,
    mode: str,
    answer: str,
    rewritten_query: str,
    response_kind: str,
    citations: list[dict],
    cited_indices: list[int],
    warnings: list[str],
    retrieval_trace: dict[str, Any],
    pipeline_events: list[dict[str, Any]],
    pipeline_timings_ms: dict[str, float],
    selected_hits: list[dict[str, Any]] | None = None,
    llm_runtime_meta: dict[str, Any] | None = None,
) -> AnswerResult:
    trace = retrieval_trace or {}
    pipeline_trace: dict[str, Any] = {
        "events": pipeline_events,
        "timings_ms": {
            **trace.get("timings_ms", {}),
            **pipeline_timings_ms,
        },
    }
    if selected_hits is not None:
        pipeline_trace["selection"] = {"selected_hits": selected_hits}
    if llm_runtime_meta is not None:
        pipeline_trace["llm"] = llm_runtime_meta
    return AnswerResult(
        query=query,
        mode=mode,
        answer=answer,
        rewritten_query=rewritten_query,
        response_kind=response_kind,
        citations=citations,
        cited_indices=cited_indices,
        warnings=list(warnings) + list(trace.get("warnings", [])),
        retrieval_trace=trace,
        pipeline_trace=pipeline_trace,
    )
