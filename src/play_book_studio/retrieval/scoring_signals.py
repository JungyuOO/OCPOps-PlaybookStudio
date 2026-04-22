# fusion/scoring에서 반복 계산하는 질의 신호를 한 곳에 모은다.
from __future__ import annotations

from dataclasses import dataclass

from .models import SessionContext
from .query import (
    OC_LOGIN_RE,
    has_backup_restore_intent,
    has_certificate_monitor_intent,
    has_cluster_node_usage_intent,
    has_doc_locator_intent,
    has_hosted_control_plane_signal,
    has_machine_config_reboot_intent,
    has_mco_concept_intent,
    has_node_drain_intent,
    has_openshift_kubernetes_compare_intent,
    has_operator_concept_intent,
    has_project_finalizer_intent,
    has_project_scoped_rbac_intent,
    has_project_terminating_intent,
    has_pod_lifecycle_concept_intent,
    has_pod_pending_troubleshooting_intent,
    has_rbac_assignment_intent,
    has_rbac_intent,
    has_crash_loop_troubleshooting_intent,
    has_update_doc_locator_intent,
    is_generic_intro_query,
    query_book_adjustments,
)
from .ranking import extract_structured_query_terms as _extract_structured_query_terms


@dataclass(slots=True)
class ScoreSignals:
    query: str
    context_text: str
    structured_query_terms: tuple[str, ...]
    book_boosts: dict[str, float]
    book_penalties: dict[str, float]
    doc_locator_intent: bool
    update_doc_locator_intent: bool
    backup_restore_intent: bool
    certificate_monitor_intent: bool
    cluster_node_usage_intent: bool
    compare_intent: bool
    operator_concept_intent: bool
    mco_concept_intent: bool
    node_drain_intent: bool
    project_terminating_intent: bool
    project_finalizer_intent: bool
    rbac_intent: bool
    project_scoped_rbac: bool
    rbac_assignment: bool
    hosted_signal: bool
    machine_config_reboot_intent: bool
    pod_pending_intent: bool
    crash_loop_intent: bool
    pod_lifecycle_intent: bool
    oc_login_intent: bool
    concept_like_intent: bool
    generic_intro_intent: bool


def build_score_signals(query: str, *, context: SessionContext) -> ScoreSignals:
    structured_query_terms = tuple(_extract_structured_query_terms(query))
    book_boosts, book_penalties = query_book_adjustments(query, context=context)
    compare_intent = has_openshift_kubernetes_compare_intent(query)
    operator_concept_intent = has_operator_concept_intent(query)
    mco_concept_intent = has_mco_concept_intent(query)
    pod_lifecycle_intent = has_pod_lifecycle_concept_intent(query)
    generic_intro_intent = is_generic_intro_query(query)
    context_text = " ".join(
        [context.current_topic or "", *context.open_entities, context.unresolved_question or ""]
    ).lower()
    return ScoreSignals(
        query=query,
        context_text=context_text,
        structured_query_terms=structured_query_terms,
        book_boosts=book_boosts,
        book_penalties=book_penalties,
        doc_locator_intent=has_doc_locator_intent(query),
        update_doc_locator_intent=has_update_doc_locator_intent(query),
        backup_restore_intent=has_backup_restore_intent(query),
        certificate_monitor_intent=has_certificate_monitor_intent(query),
        cluster_node_usage_intent=has_cluster_node_usage_intent(query),
        compare_intent=compare_intent,
        operator_concept_intent=operator_concept_intent,
        mco_concept_intent=mco_concept_intent,
        node_drain_intent=has_node_drain_intent(query),
        project_terminating_intent=has_project_terminating_intent(query),
        project_finalizer_intent=has_project_finalizer_intent(query),
        rbac_intent=has_rbac_intent(query),
        project_scoped_rbac=has_project_scoped_rbac_intent(query),
        rbac_assignment=has_rbac_assignment_intent(query),
        hosted_signal=has_hosted_control_plane_signal(query),
        machine_config_reboot_intent=has_machine_config_reboot_intent(query),
        pod_pending_intent=has_pod_pending_troubleshooting_intent(query),
        crash_loop_intent=has_crash_loop_troubleshooting_intent(query),
        pod_lifecycle_intent=pod_lifecycle_intent,
        oc_login_intent=bool(OC_LOGIN_RE.search(query)),
        concept_like_intent=any(
            (
                generic_intro_intent,
                compare_intent,
                operator_concept_intent,
                mco_concept_intent,
                pod_lifecycle_intent,
            )
        ),
        generic_intro_intent=generic_intro_intent,
    )
