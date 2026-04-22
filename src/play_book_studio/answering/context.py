"""답변 단계에서 최종 context chunk와 citation을 고른다.

retriever는 많은 후보를 반환할 수 있고, 그중 무엇을 LLM에 보여도 안전한지,
언제 clarification이 더 안전한지를 이 파일이 결정한다.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from play_book_studio.app.wiki_user_overlay import build_wiki_overlay_signal_payload
from play_book_studio.retrieval.intake_overlay import has_active_customer_pack_selection
from play_book_studio.retrieval.models import RetrievalHit
from play_book_studio.retrieval.models import SessionContext
from play_book_studio.retrieval.query import (
    has_backup_restore_intent,
    has_cluster_node_usage_intent,
    has_crash_loop_troubleshooting_intent,
    has_deployment_scaling_intent,
    has_doc_locator_intent,
    has_follow_up_reference,
    has_mco_concept_intent,
    has_node_drain_intent,
    has_openshift_kubernetes_compare_intent,
    has_operator_concept_intent,
    has_registry_storage_ops_intent,
    has_pod_lifecycle_concept_intent,
    has_project_finalizer_intent,
    has_project_terminating_intent,
    has_rbac_intent,
    is_generic_intro_query,
)

from .models import Citation, ContextBundle


SPACE_RE = re.compile(r"\s+")
SECTION_PREFIX_RE = re.compile(r"^\d+(?:\.\d+)*\.?\s*")
INTRO_RECOMMENDATION_COUNT_RE = re.compile(r"(\d+\s*개|세\s*개|3\s*개|목록|리스트|top\s*\d+)", re.IGNORECASE)
MAX_PROMPT_CLI_COMMANDS = 4


def _normalize_excerpt(text: str) -> str:
    return SPACE_RE.sub(" ", (text or "").strip())


def _section_core(section: str) -> str:
    normalized = SPACE_RE.sub(" ", (section or "").strip()).lower()
    return SECTION_PREFIX_RE.sub("", normalized)


def _anchor_root(anchor: str) -> str:
    normalized = (anchor or "").strip().lower()
    if not normalized:
        return ""
    return normalized.split("_", 1)[0]


def _hit_score(hit: RetrievalHit) -> float:
    if hit.source == "hybrid_reranked":
        pre_rerank_fused = hit.component_scores.get("pre_rerank_fused_score")
        if pre_rerank_fused is not None:
            return float(pre_rerank_fused)
    if hit.fused_score > 0:
        return float(hit.fused_score)
    return float(hit.raw_score)


def _crash_loop_priority(hit: RetrievalHit) -> int:
    lowered_section = (hit.section or "").lower()
    lowered_text = (hit.text or "").lower()
    if (
        "애플리케이션 오류 조사" in hit.section
        or "애플리케이션 진단 데이터 수집" in hit.section
        or "oc describe pod/" in lowered_text
        or "oc logs -f pod/" in lowered_text
        or "애플리케이션 pod와 관련된 이벤트" in hit.text
    ):
        return 0
    if (
        "이벤트 목록" in hit.section
        or ("이벤트" in hit.section and "backoff" in lowered_text)
        or "back-off restarting failed container" in lowered_text
    ):
        return 1
    if (
        "상태 점검 이해" in hit.section
        or "상태 점검 구성" in hit.section
        or "livenessprobe" in lowered_text
        or "readinessprobe" in lowered_text
    ):
        return 2
    if (
        "oom 종료 정책" in hit.section
        or "oomkilled" in lowered_text
        or "restartcount" in lowered_text
    ):
        return 3
    if (
        "operator 문제 해결" in hit.section
        or "카탈로그 소스 상태 보기" in hit.section
        or "실패한 서브스크립션 새로 고침" in hit.section
        or (
            ("imagepullbackoff" in lowered_text or "errimagepull" in lowered_text)
            and "crashloopbackoff" not in lowered_text
            and "애플리케이션" not in hit.text
        )
    ):
        return 9
    return 5


def _procedure_chunk_priority(hit: RetrievalHit) -> int:
    if hit.cli_commands:
        return 0
    if hit.chunk_type == "command":
        return 1
    if hit.semantic_role == "procedure":
        return 2
    return 3


def _session_mentions_mco(session_context: SessionContext | None) -> bool:
    if session_context is None:
        return False
    haystack = " ".join(
        [
            session_context.current_topic or "",
            *session_context.open_entities,
            session_context.user_goal or "",
            session_context.unresolved_question or "",
        ]
    ).lower()
    return any(
        token in haystack
        for token in (
            "machine config operator",
            "machine configuration",
            "mco",
            "머신 구성 오퍼레이터",
            "머신 컨피그 오퍼레이터",
        )
    )


def _session_mentions_rbac(session_context: SessionContext | None) -> bool:
    if session_context is None:
        return False
    haystack = " ".join(
        [
            session_context.current_topic or "",
            *session_context.open_entities,
            session_context.user_goal or "",
            session_context.unresolved_question or "",
        ]
    ).lower()
    return any(
        token in haystack
        for token in (
            "rbac",
            "권한",
            "authorization",
            "cluster-admin",
            "clusterrole",
            "rolebinding",
        )
    )


def _mco_signal(hit: RetrievalHit) -> bool:
    lowered_section = (hit.section or "").lower()
    lowered_anchor = (hit.anchor or "").lower()
    lowered_text = (hit.text or "").lower()
    return (
        hit.book_slug in {"machine_configuration", "operators", "machine_management"}
        or "machine config operator" in lowered_section
        or "machine config operator" in lowered_text
        or "machine config pool" in lowered_section
        or "machine config pool" in lowered_text
        or "machineconfigpool" in lowered_section
        or "machineconfigpool" in lowered_text
        or lowered_anchor.startswith("about-mco")
        or lowered_anchor.endswith("mco")
    )


def _rbac_signal(hit: RetrievalHit) -> bool:
    lowered_section = (hit.section or "").lower()
    lowered_anchor = (hit.anchor or "").lower()
    lowered_text = (hit.text or "").lower()
    haystack = " ".join((lowered_section, lowered_anchor, lowered_text))
    return (
        hit.book_slug in {"authentication_and_authorization", "cli_tools"}
        or (
            hit.book_slug == "postinstallation_configuration"
            and any(
                token in haystack
                for token in (
                    "rbac",
                    "authorization",
                    "rolebinding",
                    "role binding",
                    "clusterrole",
                    "cluster-admin",
                    "selfsubjectaccessreview",
                    "selfsubjectrulesreview",
                    "oc auth can-i",
                )
            )
        )
    )


def _is_troubleshooting_doc_locator_query(query: str) -> bool:
    normalized = (query or "").lower()
    if not has_doc_locator_intent(normalized):
        return False
    return any(
        token in normalized
        for token in (
            "문제 해결",
            "트러블슈팅",
            "문제가 생기면",
            "문제 생기면",
            "문제가 나면",
            "오류가 나면",
            "장애가 나면",
            "위키",
            "wiki",
        )
    )


def _compare_context_priority(hit: RetrievalHit) -> tuple[int, int]:
    book_priority = {
        "overview": 0,
        "architecture": 1,
        "security_and_compliance": 4,
    }.get(hit.book_slug, 8)
    lowered_section = (hit.section or "").lower()
    lowered_anchor = (hit.anchor or "").lower()
    positive_rank = 0 if any(
        token in lowered_section or token in lowered_anchor
        for token in (
            "유사점",
            "차이점",
            "개요",
            "소개",
            "similarities",
            "differences",
            "overview",
            "introduction",
        )
    ) else 1
    return (book_priority, positive_rank)


def _backup_only_etcd_context_priority(hit: RetrievalHit) -> tuple[int, int]:
    lowered_section = (hit.section or "").lower()
    lowered_text = (hit.text or "").lower()
    is_backup = any(token in lowered_section for token in ("백업", "backup")) or any(
        token in lowered_text for token in ("cluster-backup.sh", "oc debug --as-root node", "chroot /host")
    )
    is_restore = any(token in lowered_section for token in ("복원", "restore")) or any(
        token in lowered_text for token in ("cluster-restore.sh", "snapshot restore", "이전 클러스터 상태로 복원")
    )
    book_priority = {
        "postinstallation_configuration": 0,
        "hosted_control_planes": 1,
        "backup_and_restore": 2,
        "etcd": 3,
    }.get(hit.book_slug, 8)
    phase_priority = 0 if is_backup else 2 if is_restore else 1
    return (phase_priority, book_priority)


def _is_backup_only_etcd_query(query: str) -> bool:
    lowered = (query or "").lower()
    return "etcd" in lowered and "백업" in query and not any(
        token in lowered for token in ("복원", "복구", "restore", "recovery")
    )


def _is_customer_pack_explicit_query(query: str) -> bool:
    lowered = (query or "").lower()
    return any(
        token in lowered
        for token in (
            "업로드 문서",
            "업로드한 문서",
            "고객 문서",
            "고객문서",
            "우리 문서",
            "our document",
            "customer pack",
            "customer-pack",
        )
    )


def _is_intro_recommendation_query(query: str) -> bool:
    normalized = (query or "").strip()
    lowered = normalized.lower()
    if not normalized:
        return False

    asks_for_intro = any(
        token in normalized
        for token in (
            "입문",
            "처음",
            "처음 볼",
            "처음 봐야",
            "먼저 봐야",
            "먼저 볼",
            "추천",
            "순서",
            "로드맵",
            "뭐부터",
            "시작",
        )
    )
    asks_for_list = bool(INTRO_RECOMMENDATION_COUNT_RE.search(normalized))
    mentions_playbook_surface = any(
        token in normalized
        for token in (
            "플레이북",
            "문서",
            "가이드",
            "책",
        )
    )
    mentions_runtime_scope = any(
        token in lowered
        for token in (
            "openshift",
            "ocp",
            "오픈시프트",
            "운영",
        )
    )

    return (asks_for_intro and mentions_playbook_surface) or (
        asks_for_list and mentions_playbook_surface and mentions_runtime_scope
    )


def _generic_intro_priority(hit: RetrievalHit) -> tuple[int, int, int, int]:
    lowered_section = (hit.section or "").lower()
    lowered_anchor = (hit.anchor or "").lower()
    lowered_text = (hit.text or "").lower()
    book_priority = {
        "overview": 0,
        "architecture": 1,
        "extensions": 2,
        "operators": 3,
    }.get(hit.book_slug, 8)
    positive_markers = (
        "개요",
        "소개",
        "정의",
        "overview",
        "introduction",
        "platform-definition",
        "architecture-overview",
        "ocp-overview",
    )
    negative_markers = (
        "용어집",
        "glossary",
        "사용자 정의 운영 체제",
        "custom-os",
        "rhcos",
        "cri-o",
        "기타 주요 기능",
        "라이프사이클",
    )
    positive_rank = 0 if any(
        marker in lowered_section or marker in lowered_anchor or marker in lowered_text
        for marker in positive_markers
    ) else 1
    negative_rank = 1 if any(
        marker in lowered_section or marker in lowered_anchor or marker in lowered_text
        for marker in negative_markers
    ) else 0
    section_depth = (hit.section or "").count(".")
    return (
        negative_rank,
        book_priority,
        positive_rank,
        section_depth,
    )


def _hit_identity(hit: RetrievalHit) -> tuple[str, str, str]:
    return (
        hit.book_slug,
        _section_core(hit.section),
        _anchor_root(hit.anchor),
    )


def _unique_top_hits(hits: list[RetrievalHit], *, limit: int) -> list[RetrievalHit]:
    unique: list[tuple[int, RetrievalHit]] = []
    seen: set[tuple[str, str, str]] = set()
    for order, hit in enumerate(hits):
        identity = _hit_identity(hit)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append((order, hit))
    unique.sort(key=lambda item: (-_hit_score(item[1]), item[0]))
    return [hit for _, hit in unique[:limit]]


def _load_overlay_preference_payload(
    *,
    root_dir: Path | None,
    user_id: str,
) -> dict[str, Any]:
    if root_dir is None or not user_id.strip():
        return {}
    try:
        return build_wiki_overlay_signal_payload(root_dir, user_id=user_id.strip())
    except Exception:  # noqa: BLE001
        return {}


def _overlay_target_ref_scores(
    payload: dict[str, Any],
) -> tuple[dict[str, int], dict[str, int]]:
    exact_scores: dict[str, int] = {}
    book_scores: dict[str, int] = {}
    user_focus = payload.get("user_focus") if isinstance(payload, dict) else None
    recent_targets = user_focus.get("recent_targets") if isinstance(user_focus, dict) else None
    if not isinstance(recent_targets, list):
        return exact_scores, book_scores
    for index, item in enumerate(recent_targets[:12]):
        if not isinstance(item, dict):
            continue
        target_ref = str(item.get("target_ref") or "").strip()
        if not target_ref:
            continue
        base_score = max(10, 80 - index * 6)
        exact_scores[target_ref] = max(exact_scores.get(target_ref, 0), base_score)
        if target_ref.startswith("book:"):
            slug = target_ref.split(":", 1)[1].strip()
            if slug:
                book_scores[slug] = max(book_scores.get(slug, 0), base_score)
        elif target_ref.startswith("section:"):
            book_part = target_ref.split(":", 1)[1].split("#", 1)[0].strip()
            if book_part:
                book_scores[book_part] = max(book_scores.get(book_part, 0), base_score - 10)
        elif target_ref.startswith("figure:"):
            figure_parts = target_ref.split(":")
            if len(figure_parts) >= 3:
                book_part = figure_parts[1].strip()
                if book_part:
                    book_scores[book_part] = max(book_scores.get(book_part, 0), base_score - 20)
    return exact_scores, book_scores


def _overlay_hit_boost(
    hit: RetrievalHit,
    *,
    exact_scores: dict[str, int],
    book_scores: dict[str, int],
) -> int:
    score = book_scores.get(hit.book_slug, 0)
    if hit.book_slug:
        score = max(score, exact_scores.get(f"book:{hit.book_slug}", 0))
    anchor_root = _anchor_root(hit.anchor)
    if anchor_root:
        score = max(score, exact_scores.get(f"section:{hit.book_slug}#{anchor_root}", 0))
    if hit.book_slug and any(token in (hit.section or "").lower() for token in ("etcd", "machine config", "prometheus", "proxy", "control plane")):
        lowered_section = (hit.section or "").lower()
        if "etcd" in lowered_section:
            score = max(score, exact_scores.get("entity:etcd", 0) - 10)
        if "machine config" in lowered_section or "mco" in lowered_section:
            score = max(score, exact_scores.get("entity:machine-config-operator", 0) - 10)
        if "prometheus" in lowered_section:
            score = max(score, exact_scores.get("entity:prometheus", 0) - 10)
        if "proxy" in lowered_section:
            score = max(score, exact_scores.get("entity:cluster-wide-proxy", 0) - 10)
        if "control plane" in lowered_section:
            score = max(score, exact_scores.get("entity:control-plane-nodes", 0) - 10)
    return max(score, 0)


def _should_force_clarification(
    hits: list[RetrievalHit],
    *,
    query: str = "",
) -> bool:
    normalized = query or ""
    if has_follow_up_reference(normalized):
        return False
    if any(
        [
            has_doc_locator_intent(normalized),
            has_openshift_kubernetes_compare_intent(normalized),
            is_generic_intro_query(normalized),
            has_operator_concept_intent(normalized),
            has_mco_concept_intent(normalized),
            has_pod_lifecycle_concept_intent(normalized),
            has_rbac_intent(normalized),
            has_backup_restore_intent(normalized),
            has_crash_loop_troubleshooting_intent(normalized),
            has_project_terminating_intent(normalized),
            has_project_finalizer_intent(normalized),
            has_node_drain_intent(normalized),
            has_cluster_node_usage_intent(normalized),
            has_deployment_scaling_intent(normalized),
            has_registry_storage_ops_intent(normalized),
            _is_intro_recommendation_query(normalized),
        ]
    ):
        return False

    top_hits = _unique_top_hits(hits, limit=4)
    if len(top_hits) < 2:
        return False

    top_score = _hit_score(top_hits[0])
    second_score = _hit_score(top_hits[1])
    top_books = {hit.book_slug for hit in top_hits}
    top_book = top_hits[0].book_slug
    top_book_count = sum(int(hit.book_slug == top_book) for hit in hits[:4])
    close_competitor = second_score >= top_score * 0.94 if top_score > 0 else False
    weak_support = top_book_count == 1 or (top_book_count == 2 and len(top_books) >= 3)

    # Use a very conservative absolute floor only when support is weak.
    low_top_score = top_score < 0.018
    low_margin = (top_score - second_score) < 0.0025 if top_score > 0 else True

    return (weak_support and close_competitor) or (
        low_top_score and (weak_support or low_margin)
    )


def _select_hits(
    hits: list[RetrievalHit],
    *,
    query: str = "",
    session_context: SessionContext | None = None,
    max_chunks: int,
) -> list[RetrievalHit]:
    # context 조립은 raw retrieval보다 의도적으로 더 보수적이다.
    # 근거가 약하면 노이즈 hit 하나에 과적합하기보다 clarification을 택한다.
    if not hits:
        return []

    ranked_hits = list(hits)
    if _should_force_clarification(ranked_hits, query=query):
        return []

    normalized = query or ""
    allow_uploaded_hits = (
        _is_customer_pack_explicit_query(normalized)
        or has_active_customer_pack_selection(session_context)
    )
    if not allow_uploaded_hits:
        ranked_hits = [
            hit
            for hit in ranked_hits
            if str(hit.source_collection or "").strip() != "uploaded"
        ]
        if not ranked_hits:
            return []
    is_concept_query = any(
        [
            has_openshift_kubernetes_compare_intent(normalized),
            is_generic_intro_query(normalized),
            _is_intro_recommendation_query(normalized),
            has_operator_concept_intent(normalized),
            has_mco_concept_intent(normalized),
            has_pod_lifecycle_concept_intent(normalized),
        ]
    )
    is_procedure_query = any(
        [
            has_backup_restore_intent(normalized),
            has_crash_loop_troubleshooting_intent(normalized),
            has_rbac_intent(normalized),
            has_project_terminating_intent(normalized),
            has_project_finalizer_intent(normalized),
            has_node_drain_intent(normalized),
            has_cluster_node_usage_intent(normalized),
            has_deployment_scaling_intent(normalized),
            has_registry_storage_ops_intent(normalized),
        ]
    )

    max_chunks = min(max_chunks, 5 if is_procedure_query else 4)
    support_window = ranked_hits[: max(max_chunks * 2, 6)]
    top_score = _hit_score(support_window[0])
    top_book = support_window[0].book_slug

    if has_operator_concept_intent(normalized):
        preferred_order = {
            "operators": 0,
            "extensions": 1,
            "overview": 2,
            "architecture": 3,
            "installation_overview": 4,
        }
        ranked_hits = sorted(
            ranked_hits,
            key=lambda hit: (
                preferred_order.get(hit.book_slug, 9),
                -_hit_score(hit),
                hit.book_slug,
                hit.chunk_id,
            ),
        )
        support_window = ranked_hits[: max(max_chunks * 2, 6)]
        top_score = _hit_score(support_window[0])
        top_book = support_window[0].book_slug
    elif has_openshift_kubernetes_compare_intent(normalized):
        ranked_hits = sorted(
            ranked_hits,
            key=lambda hit: (
                *_compare_context_priority(hit),
                -_hit_score(hit),
                hit.book_slug,
                hit.chunk_id,
            ),
        )
        support_window = ranked_hits[: max(max_chunks * 2, 6)]
        top_score = _hit_score(support_window[0])
        top_book = support_window[0].book_slug
    elif is_generic_intro_query(normalized):
        ranked_hits = sorted(
            ranked_hits,
            key=lambda hit: (
                *_generic_intro_priority(hit),
                -_hit_score(hit),
                hit.book_slug,
                hit.chunk_id,
            ),
        )
        support_window = ranked_hits[: max(max_chunks * 2, 6)]
        top_score = _hit_score(support_window[0])
        top_book = support_window[0].book_slug
    elif _is_intro_recommendation_query(normalized):
        preferred_order = {
            "overview": 0,
            "architecture": 1,
            "installation_overview": 2,
            "operators": 3,
            "extensions": 4,
            "web_console": 5,
            "cli_tools": 6,
        }
        ranked_hits = sorted(
            ranked_hits,
            key=lambda hit: (
                preferred_order.get(hit.book_slug, 9),
                *_generic_intro_priority(hit),
                -_hit_score(hit),
                hit.book_slug,
                hit.chunk_id,
            ),
        )
        support_window = ranked_hits[: max(max_chunks * 2, 8)]
        top_score = _hit_score(support_window[0])
        top_book = support_window[0].book_slug
    elif has_pod_lifecycle_concept_intent(normalized):
        preferred_books = {"nodes", "overview", "architecture", "building_applications"}
        ranked_hits = sorted(
            ranked_hits,
            key=lambda hit: (
                0 if hit.book_slug in preferred_books else 1,
                -_hit_score(hit),
                hit.book_slug,
                hit.chunk_id,
            ),
        )
        support_window = ranked_hits[: max(max_chunks * 2, 6)]
        top_score = _hit_score(support_window[0])
        top_book = support_window[0].book_slug
    elif has_cluster_node_usage_intent(normalized):
        preferred_order = {
            "support": 0,
            "nodes": 1,
            "validation_and_troubleshooting": 2,
            "cli_tools": 3,
        }
        ranked_hits = sorted(
            ranked_hits,
            key=lambda hit: (
                _procedure_chunk_priority(hit),
                preferred_order.get(hit.book_slug, 9),
                -_hit_score(hit),
                hit.book_slug,
                hit.chunk_id,
            ),
        )
        support_window = ranked_hits[: max(max_chunks * 2, 8)]
        top_score = _hit_score(support_window[0])
        top_book = support_window[0].book_slug
    elif has_node_drain_intent(normalized):
        preferred_order = {
            "nodes": 0,
            "support": 1,
            "cli_tools": 2,
            "machine_management": 3,
            "postinstallation_configuration": 4,
            "backup_and_restore": 9,
        }
        ranked_hits = sorted(
            ranked_hits,
            key=lambda hit: (
                _procedure_chunk_priority(hit),
                preferred_order.get(hit.book_slug, 8),
                -_hit_score(hit),
                hit.book_slug,
                hit.chunk_id,
            ),
        )
        support_window = ranked_hits[: max(max_chunks * 2, 8)]
        top_score = _hit_score(support_window[0])
        top_book = support_window[0].book_slug
    elif _is_backup_only_etcd_query(normalized):
        ranked_hits = sorted(
            ranked_hits,
            key=lambda hit: (
                *_backup_only_etcd_context_priority(hit),
                _procedure_chunk_priority(hit),
                -_hit_score(hit),
                hit.book_slug,
                hit.chunk_id,
            ),
        )
        support_window = ranked_hits[: max(max_chunks * 2, 8)]
        top_score = _hit_score(support_window[0])
        top_book = support_window[0].book_slug
    elif has_crash_loop_troubleshooting_intent(normalized):
        preferred_order = {
            "support": 0,
            "validation_and_troubleshooting": 1,
            "building_applications": 2,
            "nodes": 3,
        }
        ranked_hits = sorted(
            ranked_hits,
            key=lambda hit: (
                _crash_loop_priority(hit),
                preferred_order.get(hit.book_slug, 9),
                -_hit_score(hit),
                hit.book_slug,
                hit.chunk_id,
            ),
        )
        support_window = ranked_hits[: max(max_chunks * 2, 8)]
        top_score = _hit_score(support_window[0])
        top_book = support_window[0].book_slug
    elif has_mco_concept_intent(normalized) or (
        _session_mentions_mco(session_context)
        and any(_mco_signal(hit) for hit in ranked_hits[:8])
    ):
        preferred_order = {
            "machine_configuration": 0,
            "operators": 1,
            "machine_management": 2,
            "architecture": 3,
            "overview": 4,
            "postinstallation_configuration": 5,
            "updating_clusters": 6,
        }
        ranked_hits = sorted(
            ranked_hits,
            key=lambda hit: (
                preferred_order.get(hit.book_slug, 9),
                -_hit_score(hit),
                hit.book_slug,
                hit.chunk_id,
            ),
        )
        support_window = ranked_hits[: max(max_chunks * 2, 6)]
        top_score = _hit_score(support_window[0])
        top_book = support_window[0].book_slug
    elif has_rbac_intent(normalized) or (
        _session_mentions_rbac(session_context)
        and any(_rbac_signal(hit) for hit in ranked_hits[:8])
    ):
        preferred_order = {
            "authentication_and_authorization": 0,
            "cli_tools": 1,
            "postinstallation_configuration": 2,
        }
        ranked_hits = sorted(
            ranked_hits,
            key=lambda hit: (
                preferred_order.get(hit.book_slug, 9),
                -_hit_score(hit),
                hit.book_slug,
                hit.chunk_id,
            ),
        )
        support_window = ranked_hits[: max(max_chunks * 2, 8)]
        top_score = _hit_score(support_window[0])
        top_book = support_window[0].book_slug
    elif has_project_terminating_intent(normalized):
        preferred_order = {
            "support": 0,
            "building_applications": 1,
            "project_apis": 2,
            "config_apis": 3,
        }
        ranked_hits = sorted(
            ranked_hits,
            key=lambda hit: (
                preferred_order.get(hit.book_slug, 9),
                -_hit_score(hit),
                hit.book_slug,
                hit.chunk_id,
            ),
        )
        support_window = ranked_hits[: max(max_chunks * 2, 8)]
        top_score = _hit_score(support_window[0])
        top_book = support_window[0].book_slug
    elif has_project_finalizer_intent(normalized):
        preferred_order = {
            "support": 0,
            "project_apis": 1,
            "config_apis": 2,
            "building_applications": 3,
        }
        ranked_hits = sorted(
            ranked_hits,
            key=lambda hit: (
                preferred_order.get(hit.book_slug, 9),
                -_hit_score(hit),
                hit.book_slug,
                hit.chunk_id,
            ),
        )
        support_window = ranked_hits[: max(max_chunks * 2, 8)]
        top_score = _hit_score(support_window[0])
        top_book = support_window[0].book_slug
    elif has_deployment_scaling_intent(normalized):
        preferred_order = {
            "cli_tools": 0,
            "building_applications": 1,
        }
        ranked_hits = sorted(
            ranked_hits,
            key=lambda hit: (
                preferred_order.get(hit.book_slug, 9),
                -_hit_score(hit),
                hit.book_slug,
                hit.chunk_id,
            ),
        )
        support_window = ranked_hits[: max(max_chunks * 2, 8)]
        top_score = _hit_score(support_window[0])
        top_book = support_window[0].book_slug
    elif has_registry_storage_ops_intent(normalized):
        preferred_order = {
            "registry": 0,
            "images": 1,
            "storage": 2,
            "installing_on_any_platform": 3,
            "installation_overview": 4,
        }
        ranked_hits = sorted(
            ranked_hits,
            key=lambda hit: (
                _procedure_chunk_priority(hit),
                preferred_order.get(hit.book_slug, 9),
                -_hit_score(hit),
                hit.book_slug,
                hit.chunk_id,
            ),
        )
        support_window = ranked_hits[: max(max_chunks * 2, 8)]
        top_score = _hit_score(support_window[0])
        top_book = support_window[0].book_slug
    elif _is_troubleshooting_doc_locator_query(normalized):
        preferred_order = {
            "support": 0,
            "validation_and_troubleshooting": 1,
            "cli_tools": 2,
            "overview": 3,
            "architecture": 4,
            "web_console": 7,
            "release_notes": 8,
        }
        ranked_hits = sorted(
            ranked_hits,
            key=lambda hit: (
                preferred_order.get(hit.book_slug, 5),
                -_hit_score(hit),
                hit.book_slug,
                hit.chunk_id,
            ),
        )
        support_window = ranked_hits[: max(max_chunks * 2, 8)]
        top_score = _hit_score(support_window[0])
        top_book = support_window[0].book_slug

    book_counts = Counter(hit.book_slug for hit in support_window)
    best_book_scores: dict[str, float] = defaultdict(float)
    for hit in support_window:
        best_book_scores[hit.book_slug] = max(
            best_book_scores[hit.book_slug],
            _hit_score(hit),
        )

    allowed_books = {top_book}
    locked_allowed_books = False
    if has_operator_concept_intent(normalized):
        operator_family = tuple(
            book_slug
            for book_slug in ("operators", "extensions", "overview")
            if best_book_scores.get(book_slug, 0.0) > 0.0
        )
        if operator_family:
            allowed_books = set(operator_family)
            locked_allowed_books = True
        else:
            for book_slug in ("operators", "extensions", "overview", "architecture", "installation_overview"):
                if best_book_scores.get(book_slug, 0.0) >= top_score * 0.62:
                    allowed_books.add(book_slug)
    if has_openshift_kubernetes_compare_intent(normalized):
        compare_books = tuple(
            book_slug
            for book_slug in ("overview", "architecture")
            if best_book_scores.get(book_slug, 0.0) > 0.0
        )
        if compare_books:
            allowed_books = set(compare_books)
            locked_allowed_books = True
        else:
            for book_slug in ("overview", "architecture", "security_and_compliance"):
                if best_book_scores.get(book_slug, 0.0) >= top_score * 0.62:
                    allowed_books.add(book_slug)
    if is_generic_intro_query(normalized):
        intro_books = tuple(
            book_slug
            for book_slug in ("overview", "architecture", "extensions", "operators")
            if best_book_scores.get(book_slug, 0.0) > 0.0
        )
        if intro_books:
            allowed_books = set(intro_books)
            locked_allowed_books = True
        else:
            for book_slug in ("overview", "architecture", "extensions", "operators"):
                if best_book_scores.get(book_slug, 0.0) >= top_score * 0.56:
                    allowed_books.add(book_slug)
    if _is_intro_recommendation_query(normalized):
        intro_books = tuple(
            book_slug
            for book_slug in (
                "overview",
                "architecture",
                "installation_overview",
                "operators",
                "extensions",
                "web_console",
                "cli_tools",
            )
            if best_book_scores.get(book_slug, 0.0) > 0.0
        )
        if intro_books:
            allowed_books = set(intro_books)
            locked_allowed_books = True
        else:
            for book_slug in (
                "overview",
                "architecture",
                "installation_overview",
                "operators",
                "extensions",
                "web_console",
                "cli_tools",
            ):
                if best_book_scores.get(book_slug, 0.0) >= top_score * 0.5:
                    allowed_books.add(book_slug)
    if has_pod_lifecycle_concept_intent(normalized):
        for book_slug in ("nodes", "overview", "architecture", "building_applications"):
            if best_book_scores.get(book_slug, 0.0) >= top_score * 0.58:
                allowed_books.add(book_slug)
    if has_cluster_node_usage_intent(normalized):
        if best_book_scores.get("support", 0.0) > 0.0:
            allowed_books = {"support"}
            locked_allowed_books = True
        else:
            for book_slug in ("support", "nodes", "validation_and_troubleshooting", "cli_tools"):
                if best_book_scores.get(book_slug, 0.0) >= top_score * 0.52:
                    allowed_books.add(book_slug)
    if has_node_drain_intent(normalized):
        operational_books = tuple(
            book_slug
            for book_slug in (
                "nodes",
                "support",
                "cli_tools",
                "machine_management",
                "postinstallation_configuration",
            )
            if best_book_scores.get(book_slug, 0.0) > 0.0
        )
        if operational_books:
            allowed_books = set(operational_books)
            locked_allowed_books = True
        else:
            for book_slug in (
                "nodes",
                "support",
                "cli_tools",
                "machine_management",
                "postinstallation_configuration",
                "backup_and_restore",
            ):
                if best_book_scores.get(book_slug, 0.0) >= top_score * 0.5:
                    allowed_books.add(book_slug)
    if _is_backup_only_etcd_query(normalized):
        operational_books = tuple(
            book_slug
            for book_slug in (
                "postinstallation_configuration",
                "hosted_control_planes",
                "backup_and_restore",
                "etcd",
                "updating_clusters",
            )
            if best_book_scores.get(book_slug, 0.0) > 0.0
        )
        if operational_books:
            allowed_books = set(operational_books)
            locked_allowed_books = True
        else:
            for book_slug in (
                "postinstallation_configuration",
                "hosted_control_planes",
                "backup_and_restore",
                "etcd",
                "updating_clusters",
            ):
                if best_book_scores.get(book_slug, 0.0) >= top_score * 0.5:
                    allowed_books.add(book_slug)
    if has_crash_loop_troubleshooting_intent(normalized):
        for book_slug in ("support", "validation_and_troubleshooting", "building_applications", "nodes"):
            if best_book_scores.get(book_slug, 0.0) >= top_score * 0.55:
                allowed_books.add(book_slug)
    if has_mco_concept_intent(normalized) or (
        _session_mentions_mco(session_context)
        and any(_mco_signal(hit) for hit in ranked_hits[:8])
    ):
        preferred_mco_books = tuple(
            book_slug
            for book_slug in (
                "machine_configuration",
                "operators",
                "machine_management",
                "architecture",
                "overview",
                "postinstallation_configuration",
                "updating_clusters",
            )
            if best_book_scores.get(book_slug, 0.0) > 0.0
        )
        if preferred_mco_books:
            allowed_books.update(preferred_mco_books)
        else:
            for book_slug in (
                "machine_configuration",
                "operators",
                "machine_management",
                "architecture",
                "overview",
                "postinstallation_configuration",
                "updating_clusters",
            ):
                if best_book_scores.get(book_slug, 0.0) >= top_score * 0.62:
                    allowed_books.add(book_slug)
    if has_rbac_intent(normalized) or (
        _session_mentions_rbac(session_context)
        and any(_rbac_signal(hit) for hit in ranked_hits[:8])
    ):
        for book_slug in ("authentication_and_authorization", "cli_tools", "postinstallation_configuration"):
            if best_book_scores.get(book_slug, 0.0) >= top_score * 0.58:
                allowed_books.add(book_slug)
    if has_project_terminating_intent(normalized):
        for book_slug in ("support", "building_applications", "project_apis", "config_apis"):
            if best_book_scores.get(book_slug, 0.0) >= top_score * 0.46:
                allowed_books.add(book_slug)
    if has_project_finalizer_intent(normalized):
        for book_slug in ("support", "project_apis", "config_apis", "building_applications"):
            if best_book_scores.get(book_slug, 0.0) >= top_score * 0.44:
                allowed_books.add(book_slug)
    if has_deployment_scaling_intent(normalized):
        for book_slug in ("cli_tools", "building_applications"):
            if best_book_scores.get(book_slug, 0.0) >= top_score * 0.52:
                allowed_books.add(book_slug)
    if has_registry_storage_ops_intent(normalized):
        for book_slug in ("registry", "images", "storage", "installing_on_any_platform", "installation_overview"):
            if best_book_scores.get(book_slug, 0.0) >= top_score * 0.5:
                allowed_books.add(book_slug)
    if _is_troubleshooting_doc_locator_query(normalized):
        for book_slug in ("support", "validation_and_troubleshooting", "cli_tools"):
            if best_book_scores.get(book_slug, 0.0) >= top_score * 0.52:
                allowed_books.add(book_slug)
    for book_slug, count in book_counts.items():
        if book_slug == top_book:
            continue
        if locked_allowed_books:
            continue
        threshold = 0.92
        if is_concept_query:
            threshold = 0.72
        elif is_procedure_query:
            threshold = 0.84
        if has_project_terminating_intent(normalized) or has_project_finalizer_intent(normalized):
            threshold = 0.52
        if has_deployment_scaling_intent(normalized):
            threshold = 0.58
        if has_registry_storage_ops_intent(normalized):
            threshold = 0.54
        if count >= 2 and best_book_scores[book_slug] >= top_score * threshold:
            allowed_books.add(book_slug)

    if top_score > 0:
        score_cutoff = top_score * (0.68 if is_concept_query else 0.74 if is_procedure_query else 0.82)
    else:
        score_cutoff = 0.0
    if (has_project_terminating_intent(normalized) or has_project_finalizer_intent(normalized)) and top_score > 0:
        score_cutoff = top_score * 0.44
    if has_deployment_scaling_intent(normalized) and top_score > 0:
        score_cutoff = top_score * 0.5
    if has_registry_storage_ops_intent(normalized) and top_score > 0:
        score_cutoff = top_score * 0.46
    selected: list[RetrievalHit] = []
    per_book_counts: Counter[str] = Counter()
    per_book_limit = 2 if has_crash_loop_troubleshooting_intent(normalized) else 3 if is_procedure_query else 2
    if _is_backup_only_etcd_query(normalized):
        per_book_limit = 2
    seen_sections: set[tuple[str, str]] = set()
    skip_crash_loop_noise = has_crash_loop_troubleshooting_intent(normalized) and any(
        _crash_loop_priority(hit) < 9 for hit in ranked_hits
    )
    uploaded_hits = [
        hit
        for hit in ranked_hits
        if str(hit.source_collection or "").strip() == "uploaded"
    ]
    should_seed_uploaded = bool(uploaded_hits) and allow_uploaded_hits

    if should_seed_uploaded:
        for hit in sorted(
            uploaded_hits,
            key=lambda item: (
                -_hit_score(item),
                item.book_slug,
                item.chunk_id,
            ),
        ):
            if len(selected) >= max_chunks:
                break
            section_signature = (hit.book_slug, _section_core(hit.section))
            if section_signature in seen_sections:
                continue
            selected.append(hit)
            per_book_counts[hit.book_slug] += 1
            seen_sections.add(section_signature)
            allowed_books.add(hit.book_slug)
            break

    for hit in ranked_hits:
        if len(selected) >= max_chunks:
            break
        if hit.book_slug not in allowed_books:
            continue
        if _hit_score(hit) < score_cutoff:
            continue
        if skip_crash_loop_noise and _crash_loop_priority(hit) >= 9:
            continue
        if per_book_counts[hit.book_slug] >= per_book_limit:
            continue
        section_signature = (hit.book_slug, _section_core(hit.section))
        if (
            has_crash_loop_troubleshooting_intent(normalized)
            or has_registry_storage_ops_intent(normalized)
        ) and section_signature in seen_sections:
            continue
        selected.append(hit)
        per_book_counts[hit.book_slug] += 1
        seen_sections.add(section_signature)

    if _is_backup_only_etcd_query(normalized):
        standard_books = ("postinstallation_configuration", "hosted_control_planes")
        if not any(hit.book_slug in standard_books for hit in selected):
            for hit in ranked_hits:
                if hit.book_slug not in standard_books:
                    continue
                section_signature = (hit.book_slug, _section_core(hit.section))
                if section_signature in seen_sections:
                    continue
                selected.insert(0, hit)
                selected = selected[:max_chunks]
                break

    if (
        has_project_terminating_intent(normalized) or has_project_finalizer_intent(normalized)
    ) and len(selected) < min(2, max_chunks):
        preferred_books = (
            ("support", "building_applications", "project_apis", "config_apis")
            if has_project_terminating_intent(normalized)
            else ("support", "project_apis", "config_apis", "building_applications")
        )
        for book_slug in preferred_books:
            for hit in ranked_hits:
                if len(selected) >= min(2, max_chunks):
                    break
                if hit in selected:
                    continue
                if hit.book_slug != book_slug:
                    continue
                section_signature = (hit.book_slug, _section_core(hit.section))
                if section_signature in seen_sections:
                    continue
                selected.append(hit)
                per_book_counts[hit.book_slug] += 1
                seen_sections.add(section_signature)

    return selected[:max_chunks]


def assemble_context(
    hits: list[RetrievalHit],
    *,
    query: str = "",
    session_context: SessionContext | None = None,
    root_dir: Path | None = None,
    max_chunks: int = 6,
    max_chars_per_chunk: int = 900,
) -> ContextBundle:
    citations: list[Citation] = []
    seen_chunk_ids: set[str] = set()
    seen_signatures: set[tuple[str, str, str]] = set()
    seen_mirror_sections: dict[tuple[str, str], str] = {}
    allow_etcd_companion_mirror = _is_backup_only_etcd_query(query)
    etcd_companion_books = {
        "postinstallation_configuration",
        "etcd",
        "backup_and_restore",
    }
    overlay_payload = _load_overlay_preference_payload(
        root_dir=root_dir,
        user_id=str(getattr(session_context, "user_id", "") or ""),
    )
    overlay_exact_scores, overlay_book_scores = _overlay_target_ref_scores(overlay_payload)
    selected_hits = _select_hits(
        hits,
        query=query,
        session_context=session_context,
        max_chunks=max_chunks,
    )
    if overlay_exact_scores or overlay_book_scores:
        selected_hits = sorted(
            selected_hits,
            key=lambda hit: (
                -_overlay_hit_boost(
                    hit,
                    exact_scores=overlay_exact_scores,
                    book_scores=overlay_book_scores,
                ),
                -_hit_score(hit),
                hit.book_slug,
                hit.chunk_id,
            ),
        )

    for hit in selected_hits:
        if hit.chunk_id in seen_chunk_ids:
            continue
        excerpt = _normalize_excerpt(hit.text)
        section_core = _section_core(hit.section)
        anchor_root = _anchor_root(hit.anchor)
        mirror_signature = (section_core, anchor_root)
        prior_book = seen_mirror_sections.get(mirror_signature)
        if (
            prior_book is not None
            and prior_book != hit.book_slug
            and section_core
            and anchor_root
            and not (
                allow_etcd_companion_mirror
                and prior_book in etcd_companion_books
                and hit.book_slug in etcd_companion_books
            )
        ):
            continue
        signature = (
            hit.book_slug,
            hit.section.strip(),
            excerpt[:240],
        )
        if signature in seen_signatures:
            continue
        seen_chunk_ids.add(hit.chunk_id)
        seen_signatures.add(signature)
        if section_core and anchor_root:
            seen_mirror_sections.setdefault(mirror_signature, hit.book_slug)
        citations.append(
            Citation(
                index=len(citations) + 1,
                chunk_id=hit.chunk_id,
                book_slug=hit.book_slug,
                section=hit.section,
                anchor=hit.anchor,
                source_url=hit.source_url,
                viewer_path=hit.viewer_path,
                excerpt=excerpt[:max_chars_per_chunk].strip(),
                section_path=hit.section_path,
                section_path_label=" > ".join(hit.section_path) if hit.section_path else hit.section,
                chunk_type=hit.chunk_type,
                semantic_role=hit.semantic_role,
                source_collection=hit.source_collection,
                block_kinds=hit.block_kinds,
                cli_commands=hit.cli_commands,
                error_strings=hit.error_strings,
                k8s_objects=hit.k8s_objects,
                operator_names=hit.operator_names,
                verification_hints=hit.verification_hints,
            )
        )

    prompt_lines: list[str] = []
    for citation in citations:
        prompt_lines.append(
            f"[{citation.index}] book={citation.book_slug} | section={citation.section} | viewer={citation.viewer_path}"
        )
        prompt_lines.append(citation.excerpt)
        if citation.cli_commands:
            prompt_lines.append("ordered_cli_commands:")
            for step_index, command in enumerate(citation.cli_commands[:MAX_PROMPT_CLI_COMMANDS], start=1):
                prompt_lines.append(f"- step {step_index}: {command}")
        prompt_lines.append("")

    return ContextBundle(
        prompt_context="\n".join(prompt_lines).strip(),
        citations=citations,
    )
