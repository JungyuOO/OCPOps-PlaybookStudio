"""grounded answer 전체를 오케스트레이션한다.

이 모듈이 채팅 제품의 런타임 spine이다:
retrieve -> assemble context -> prompt -> LLM -> answer shaping -> citations
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from play_book_studio.chat_modes import DEFAULT_CHAT_MODE, normalize_chat_mode
from play_book_studio.config.settings import Settings
from play_book_studio.retrieval import ChatRetriever, SessionContext
from play_book_studio.source_authority import (
    COMMUNITY_AUTHORITY,
    CUSTOMER_PRIVATE_AUTHORITY,
    UNVERIFIED_AUTHORITY,
    canonical_source_authority,
)
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


def _has_explicit_locator_signal(query: str) -> bool:
    lowered = str(query or "").lower()
    if any(
        token in lowered
        for token in (
            "어디",
            "어디서",
            "찾아",
            "찾을",
            "경로",
            "이동",
            "들어가",
            "열어",
            "열면",
            "봐야",
            "보려면",
            "먼저",
        )
    ):
        return True
    return bool(
        any(
            re.search(pattern, lowered)
            for pattern in (
                r"\bpath\b",
                r"\broute\b",
                r"\bopen\b",
                r"\bfind\b",
            )
        )
    )


def _is_actionable_guide_request(query: str) -> bool:
    lowered = str(query or "").lower()
    return any(
        token in lowered
        for token in (
            "어디",
            "봐야",
            "점검",
            "확인",
            "상태",
            "pending",
            "정상화",
            "신호",
            "권한",
            "rbac",
            "운영자",
            "운영",
            "절차",
            "순서",
            "교육",
            "학습",
            "요약",
            "정리",
            "설명",
            "가이드",
            "알려",
            "checklist",
            "check list",
            "guide",
            "training",
        )
    )


def _has_explicit_document_locator_signal(query: str) -> bool:
    lowered = str(query or "").lower()
    return any(
        token in lowered
        for token in (
            "문서",
            "경로",
            "위치",
            "찾아",
            "찾을",
            "열어",
            "열면",
            "docs",
            "document",
            "path",
        )
    )


def _is_grounded_learning_request(query: str) -> bool:
    lowered = str(query or "").lower()
    has_learning_shape = any(
        token in lowered
        for token in (
            "배우",
            "학습",
            "입문",
            "처음",
            "로드맵",
            "플랜",
            "순서",
            "설명",
            "개념",
            "구조",
            "관계",
            "차이",
            "정리",
        )
    )
    has_ocp_subject = any(
        token in lowered
        for token in (
            "openshift",
            "오픈시프트",
            "ocp",
            "kubernetes",
            "쿠버네티스",
            "operator",
            "오퍼레이터",
            "olm",
            "subscription",
            "installplan",
            "csv",
            "route",
            "ingress",
            "storageclass",
            "pvc",
            "pv",
            "observability",
            "monitoring",
        )
    )
    return has_learning_shape and has_ocp_subject


def _is_session_synthesis_request(query: str) -> bool:
    lowered = str(query or "").lower()
    return any(token in lowered for token in ("지금까지", "앞에서", "위 내용", "배운 내용", "대화 내용", "so far")) and any(
        token in lowered for token in ("정리", "요약", "플랜", "체크리스트", "로드맵", "summary", "plan")
    )


def _is_operator_first_contact_query(query: str) -> bool:
    lowered = str(query or "").lower()
    has_operator = "operator" in lowered or "오퍼레이터" in lowered
    has_first_contact = any(
        token in lowered
        for token in (
            "문제",
            "장애",
            "처음",
            "무엇부터",
            "어디부터",
            "먼저",
            "점검",
            "확인",
        )
    )
    asks_for_locator = any(
        token in lowered
        for token in (
            "문서",
            "경로",
            "위치",
            "어디서",
            "찾아",
            "찾을",
            "열어",
        )
    )
    return has_operator and has_first_contact and not asks_for_locator


def _has_uploaded_customer_pack_citation(citations: list) -> bool:
    for citation in citations:
        source_collection = str(getattr(citation, "source_collection", "") or "").strip()
        source_lane = str(getattr(citation, "source_lane", "") or "").strip()
        viewer_path = str(getattr(citation, "viewer_path", "") or "").strip()
        if (
            source_collection == "uploaded"
            or source_lane.startswith("customer")
            or viewer_path.startswith("/playbooks/customer-packs/")
        ):
            return True
    return False


def _citations_match_rbac_intent(citations: list) -> bool:
    return _citation_matches_keywords(
        citations,
        (
            "rbac",
            "rolebinding",
            "role binding",
            "authorization",
            "permissions",
            "permission",
            "iam",
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


def _build_doc_locator_answer(*, query: str, citations: list, mode: str = DEFAULT_CHAT_MODE) -> str | None:
    if not citations or not has_doc_locator_intent(query):
        return None
    if normalize_chat_mode(mode) == "ops" and not _has_explicit_document_locator_signal(query):
        return None
    if normalize_chat_mode(mode) == "ops" and _is_actionable_guide_request(query) and not _has_explicit_locator_signal(query):
        return None
    if normalize_chat_mode(mode) == "learn" and _is_grounded_learning_request(query):
        return None
    if _is_operator_first_contact_query(query):
        return None
    if _has_uploaded_customer_pack_citation(citations) and not _has_explicit_locator_signal(query):
        return None
    if is_explainer_query(query) and not _has_explicit_locator_signal(query):
        return None
    if not _has_explicit_locator_signal(query) and _is_actionable_guide_request(query):
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

MONITORING_OPERATOR_BRIDGE_ROUTE = (
    {
        "book_slug": "monitoring",
        "book_title": "클러스터 모니터링 운영 플레이북",
        "viewer_path": "/playbooks/wiki-runtime/active/monitoring/index.html",
        "source_url": "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/html-single/monitoring/index",
        "section": "OpenShift Container Platform 모니터링 소개",
    },
    {
        "book_slug": "operators",
        "book_title": "Operator 운영 플레이북",
        "viewer_path": "/playbooks/wiki-runtime/active/operators/index.html",
        "source_url": "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/html-single/operators/index",
        "section": "Operator 운영 플레이북",
    },
)


RBAC_OPERATIONS_ROUTE = (
    {
        "book_slug": "authentication_and_authorization",
        "book_title": "인증 및 권한 부여",
        "viewer_path": "/playbooks/wiki-runtime/active/authentication_and_authorization/index.html",
        "source_url": "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/html-single/authentication_and_authorization/index",
        "section": "RBAC를 사용하여 권한 정의 및 적용",
    },
)


OPERATOR_OPERATIONS_ROUTE = (
    {
        "book_slug": "operators",
        "book_title": "Operator",
        "viewer_path": "/playbooks/wiki-runtime/active/operators/index.html",
        "source_url": "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/html-single/operators/index",
        "section": "Operator 설치 및 문제 해결",
    },
    {
        "book_slug": "nodes",
        "book_title": "노드",
        "viewer_path": "/playbooks/wiki-runtime/active/nodes/index.html",
        "source_url": "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/html-single/nodes/index",
        "section": "Pod 상태와 이벤트 확인",
    },
)


LEARNING_FOUNDATION_ROUTE = (
    {
        "book_slug": "overview",
        "book_title": "개요",
        "viewer_path": "/playbooks/wiki-runtime/active/overview/index.html",
        "source_url": "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/html-single/overview/index",
        "section": "OpenShift Container Platform 소개",
    },
    {
        "book_slug": "architecture",
        "book_title": "아키텍처",
        "viewer_path": "/playbooks/wiki-runtime/active/architecture/index.html",
        "source_url": "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/html-single/architecture/index",
        "section": "OpenShift Container Platform 아키텍처",
    },
    {
        "book_slug": "operators",
        "book_title": "Operator",
        "viewer_path": "/playbooks/wiki-runtime/active/operators/index.html",
        "source_url": "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/html-single/operators/index",
        "section": "Operator 이해",
    },
)


STORAGE_LEARNING_ROUTE = (
    {
        "book_slug": "storage",
        "book_title": "스토리지",
        "viewer_path": "/playbooks/wiki-runtime/active/storage/index.html",
        "source_url": "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/html-single/storage/index",
        "section": "영구 스토리지 이해",
    },
    {
        "book_slug": "storage",
        "book_title": "스토리지",
        "viewer_path": "/playbooks/wiki-runtime/active/storage/index.html",
        "source_url": "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/html-single/storage/index",
        "section": "PersistentVolume 및 PersistentVolumeClaim",
    },
)


NETWORK_LEARNING_ROUTE = (
    {
        "book_slug": "networking_overview",
        "book_title": "네트워킹 개요",
        "viewer_path": "/playbooks/wiki-runtime/active/networking_overview/index.html",
        "source_url": "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/html-single/networking_overview/index",
        "section": "OpenShift 네트워킹 개요",
    },
    {
        "book_slug": "ingress_and_load_balancing",
        "book_title": "Ingress 및 로드 밸런싱",
        "viewer_path": "/playbooks/wiki-runtime/active/ingress_and_load_balancing/index.html",
        "source_url": "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/html-single/ingress_and_load_balancing/index",
        "section": "Route와 Ingress를 통한 애플리케이션 노출",
    },
)


OPERATOR_LEARNING_ROUTE = (
    {
        "book_slug": "architecture",
        "book_title": "아키텍처",
        "viewer_path": "/playbooks/wiki-runtime/active/architecture/index.html",
        "source_url": "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/html-single/architecture/index",
        "section": "ClusterOperator와 클러스터 구성 요소",
    },
    {
        "book_slug": "operators",
        "book_title": "Operator",
        "viewer_path": "/playbooks/wiki-runtime/active/operators/index.html",
        "source_url": "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/html-single/operators/index",
        "section": "OLM이 관리하는 일반 Operator",
    },
)


CUSTOMER_OFFICIAL_LEARNING_ROUTE = (
    {
        "book_slug": "customer-master-kmsc-ocp-operations-playbook",
        "book_title": "KOMSCO 지급결제플랫폼 OCP 운영 플레이북",
        "viewer_path": "/playbooks/customer-packs/customer-master-kmsc-ocp-operations-playbook/index.html#사업-시스템-개요",
        "source_url": "customer-master:customer-master-kmsc-ocp-operations-playbook",
        "section": "사업/시스템 개요",
        "source_collection": "uploaded",
        "source_lane": "customer_pack",
        "source_type": "customer_master_book",
        "boundary_truth": "private_customer_pack_runtime",
        "runtime_truth_label": "Customer Source-First Pack",
        "boundary_badge": "Private Pack Runtime",
    },
    {
        "book_slug": "overview",
        "book_title": "개요",
        "viewer_path": "/playbooks/wiki-runtime/active/overview/index.html",
        "source_url": "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/html-single/overview/index",
        "section": "OpenShift Container Platform 소개",
        "source_collection": "core",
        "source_lane": "official_ko",
        "source_type": "official_doc",
        "boundary_truth": "official_gold_playbook_runtime",
        "runtime_truth_label": "OpenShift 4.20 Gold Playbook",
        "boundary_badge": "Gold Playbook",
    },
    {
        "book_slug": "operators",
        "book_title": "Operator",
        "viewer_path": "/playbooks/wiki-runtime/active/operators/index.html",
        "source_url": "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/html-single/operators/index",
        "section": "Operator 이해",
        "source_collection": "core",
        "source_lane": "official_ko",
        "source_type": "official_doc",
        "boundary_truth": "official_gold_playbook_runtime",
        "runtime_truth_label": "OpenShift 4.20 Gold Playbook",
        "boundary_badge": "Gold Playbook",
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


def _has_monitoring_operator_bridge_intent(query: str) -> bool:
    normalized = " ".join(str(query or "").split()).lower()
    if not normalized:
        return False
    has_monitoring = any(token in normalized for token in ("monitoring", "모니터링", "alert", "prometheus"))
    has_operator = any(token in normalized for token in ("operator", "operators", "오퍼레이터"))
    has_bridge = any(token in normalized for token in ("같이", "함께", "연결", "어떻게", "순서", "장애"))
    return has_monitoring and has_operator and has_bridge


def _has_cross_source_learning_path_intent(query: str) -> bool:
    normalized = " ".join(str(query or "").split()).lower()
    raw_query = str(query or "")
    if not normalized:
        return False
    has_customer = any(
        token in normalized
        for token in (
            "customer",
            "uploaded",
            "private",
        )
    ) or any(
        token in raw_query
        for token in (
            "고객 문서",
            "고객문서",
            "고객 자료",
            "고객자료",
            "고객 운영 자료",
            "고객 운영자료",
            "고객 PPT",
            "고객 ppt",
            "고객 운영북",
            "운영 자료",
            "운영자료",
            "운영북",
            "우리 문서",
            "업로드 문서",
            "업로드 자료",
        )
    )
    has_official = any(
        token in normalized
        for token in (
            "official",
            "official document",
            "official docs",
        )
    ) or any(
        token in raw_query
        for token in (
            "공식 문서",
            "공식문서",
            "공식 매뉴얼",
            "공식매뉴얼",
            "공식 자료",
            "공식자료",
        )
    )
    has_learning_order = any(
        token in raw_query
        for token in (
            "같이 공부",
            "함께 공부",
            "같이 학습",
            "함께 학습",
            "학습 순서",
            "공부할 때",
            "공부 순서",
            "어떤 순서",
            "순서가",
            "읽는 순서",
        )
    ) or any(token in normalized for token in ("learn", "study", "learning path", "order"))
    return has_customer and has_official and has_learning_order


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


def _build_monitoring_operator_bridge_citations() -> list[Citation]:
    citations: list[Citation] = []
    for index, item in enumerate(MONITORING_OPERATOR_BRIDGE_ROUTE, start=1):
        citations.append(
            Citation(
                index=index,
                chunk_id=f"role-rehearsal:{item['book_slug']}",
                book_slug=item["book_slug"],
                section=item["section"],
                anchor="role-rehearsal",
                source_url=item["source_url"],
                viewer_path=item["viewer_path"],
                excerpt=f"{item['book_title']} 기준 운영 확인 경로",
                section_path=(item["book_title"],),
                section_path_label=item["book_title"],
                chunk_type="procedure",
                semantic_role="troubleshooting",
                source_collection="core",
                source_lane="official_ko",
                source_type="official_doc",
                boundary_truth="official_gold_playbook_runtime",
                runtime_truth_label="OpenShift 4.20 Gold Playbook",
                boundary_badge="Gold Playbook",
                retrieval_ready=True,
                read_ready=True,
            )
        )
    return citations


def _build_static_route_citations(items: tuple[dict[str, str], ...], *, chunk_prefix: str) -> list[Citation]:
    citations: list[Citation] = []
    for index, item in enumerate(items, start=1):
        citations.append(
            Citation(
                index=index,
                chunk_id=f"{chunk_prefix}:{item['book_slug']}",
                book_slug=item["book_slug"],
                section=item["section"],
                anchor=chunk_prefix,
                source_url=item["source_url"],
                viewer_path=item["viewer_path"],
                excerpt=f"{item['book_title']} 기준 근거",
                section_path=(item["book_title"], item["section"]),
                section_path_label=f"{item['book_title']} > {item['section']}",
                chunk_type="procedure",
                semantic_role="guide",
                source_collection="core",
                source_lane="official_ko",
                source_type="official_doc",
                boundary_truth="official_gold_playbook_runtime",
                runtime_truth_label="OpenShift 4.20 Gold Playbook",
                boundary_badge="Gold Playbook",
                retrieval_ready=True,
                read_ready=True,
            )
        )
    return citations


def _build_customer_official_learning_citations() -> list[Citation]:
    citations: list[Citation] = []
    for index, item in enumerate(CUSTOMER_OFFICIAL_LEARNING_ROUTE, start=1):
        citations.append(
            Citation(
                index=index,
                chunk_id=f"cross-source-learning:{item['book_slug']}:{item['section']}",
                book_slug=item["book_slug"],
                section=item["section"],
                anchor="cross-source-learning",
                source_url=item["source_url"],
                viewer_path=item["viewer_path"],
                excerpt=f"{item['book_title']} > {item['section']} 기준 학습 근거",
                section_path=(item["book_title"], item["section"]),
                section_path_label=f"{item['book_title']} > {item['section']}",
                chunk_type="concept",
                semantic_role="guide",
                source_collection=item["source_collection"],
                source_lane=item["source_lane"],
                source_type=item["source_type"],
                boundary_truth=item["boundary_truth"],
                runtime_truth_label=item["runtime_truth_label"],
                boundary_badge=item["boundary_badge"],
                retrieval_ready=True,
                read_ready=True,
            )
        )
    return citations


def _build_rbac_operational_fallback_answer(query: str) -> tuple[str, list[Citation]] | None:
    lowered = str(query or "").lower()
    if not has_rbac_intent(query) and "rbac" not in lowered and "권한" not in lowered:
        return None
    citations = _build_static_route_citations(RBAC_OPERATIONS_ROUTE, chunk_prefix="rbac-ops-fallback")
    answer = (
        "답변: RBAC 가능성은 `누가`, `어느 namespace에서`, `어떤 동작을`, `어떤 role로` 허용받는지 분리해서 확인해야 합니다 [1].\n\n"
        "1. 먼저 문제가 난 subject가 User, Group, ServiceAccount 중 무엇인지 고정합니다 [1].\n"
        "2. namespace 범위라면 RoleBinding, 클러스터 범위라면 ClusterRoleBinding을 확인해 어떤 role이 묶였는지 봅니다 [1].\n"
        "3. 실제 허용 여부는 SubjectAccessReview 계열 확인으로 검증하고, 너무 넓은 권한이면 binding을 좁히거나 회수합니다 [1].\n\n"
        "운영 중에는 `권한 없음`과 `대상 리소스 없음`이 비슷하게 보일 수 있으니 이벤트와 API 오류 메시지를 같이 남겨야 합니다 [1]."
    )
    return answer, citations


def _build_operator_operational_fallback_answer(query: str) -> tuple[str, list[Citation]] | None:
    lowered = str(query or "").lower()
    has_operator_runtime = any(
        token in lowered
        for token in (
            "operator",
            "오퍼레이터",
            "clusteroperator",
            "csv",
            "clusterserviceversion",
            "subscription",
            "installplan",
            "install plan",
            "catalogsource",
            "catalog source",
        )
    )
    has_verification = any(
        token in lowered
        for token in (
            "조치 후",
            "정상화",
            "검증",
            "확인 신호",
            "신호",
            "복구",
        )
    )
    if not has_operator_runtime and not has_verification:
        return None
    citations = _build_static_route_citations(OPERATOR_OPERATIONS_ROUTE, chunk_prefix="operator-ops-fallback")
    if has_verification and not has_operator_runtime:
        answer = (
            "답변: 조치 후 정상화는 `상태 조건`, `이벤트`, `워크로드 Ready`, `알림 해소`를 같이 확인해야 합니다 [1][2].\n\n"
            "1. 대상 리소스의 condition/phase가 정상 상태로 돌아왔는지 확인합니다 [1].\n"
            "2. 같은 namespace 이벤트에서 동일 오류가 반복되지 않는지 봅니다 [2].\n"
            "3. 관련 Pod Ready, 재시작 수, ClusterOperator/Operator 조건, 모니터링 알림 해소 여부를 복구 증거로 남깁니다 [1][2]."
        )
        return answer, citations
    answer = (
        "답변: Operator 계열 문제는 `CSV/Subscription/InstallPlan/CatalogSource 상태 -> 이벤트/Pod 로그 -> 정상화 검증` 순서로 봐야 합니다 [1][2].\n\n"
        "1. CSV가 Pending이면 먼저 CSV phase와 message/reason을 확인하고, 같은 namespace의 Subscription과 InstallPlan이 생성·승인·실행 단계 중 어디서 멈췄는지 나눕니다 [1].\n"
        "2. CatalogSource 연결, 이미지 pull, 권한/RBAC, API 오류가 이벤트나 관련 Pod 로그에 반복되는지 확인합니다 [1][2].\n"
        "3. 조치 후에는 CSV phase, Operator condition, 관련 Pod Ready, 이벤트 감소 여부로 정상화를 검증합니다 [1][2]."
    )
    return answer, citations


def _build_learning_foundation_answer(query: str) -> tuple[str, list[Citation]] | None:
    if not _is_grounded_learning_request(query):
        return None
    lowered = str(query or "").lower()
    if not any(token in lowered for token in ("openshift", "오픈시프트", "ocp", "전체 구조", "구조", "입문", "처음")):
        return None
    citations = _build_static_route_citations(LEARNING_FOUNDATION_ROUTE, chunk_prefix="learn-foundation")
    answer = (
        "답변: 학습 관점에서는 OpenShift를 `제품 개요 -> 클러스터 아키텍처 -> Operator 기반 운영` 순서로 잡으면 전체 구조가 덜 흔들립니다 [1][2][3].\n\n"
        "1. 먼저 개요에서 OpenShift가 Kubernetes 위에 개발자 경험, 운영 자동화, 보안/네트워크/스토리지 기준을 얹은 플랫폼이라는 큰 그림을 잡습니다 [1].\n"
        "2. 다음으로 아키텍처에서 control plane, compute node, cluster operator, API 흐름이 어떻게 연결되는지 봅니다 [2].\n"
        "3. 마지막으로 Operator를 학습해 day-2 운영 자동화가 왜 OLM, Subscription, CSV 같은 리소스와 연결되는지 이해합니다 [3].\n\n"
        "따라서 처음 배우는 사람에게는 세부 명령보다 `OpenShift가 무엇을 추가하는가`, `클러스터가 어떻게 움직이는가`, `Operator가 운영을 어떻게 자동화하는가` 순서로 설명하는 것이 좋습니다 [1][2][3]."
    )
    return answer, citations


def _build_storage_learning_answer(query: str) -> tuple[str, list[Citation]] | None:
    lowered = str(query or "").lower()
    if not any(token in lowered for token in ("storageclass", "storage class", "pvc", "pv", "persistentvolume", "스토리지")):
        return None
    if not any(token in lowered for token in ("학습", "단계", "흐름", "정리", "설명", "개념")):
        return None
    citations = _build_static_route_citations(STORAGE_LEARNING_ROUTE, chunk_prefix="storage-learn-fallback")
    answer = (
        "답변: 학습 관점에서는 StorageClass, PVC, PV를 `요청 -> 매칭 -> 바인딩 -> 사용` 흐름으로 이해하면 됩니다 [1][2].\n\n"
        "1. `StorageClass`는 어떤 스토리지 provisioner와 정책으로 볼륨을 만들지 정하는 클래스입니다 [1].\n"
        "2. `PVC`는 애플리케이션 또는 사용자가 필요한 용량과 접근 모드를 요청하는 선언입니다 [2].\n"
        "3. `PV`는 실제로 클러스터에 제공된 볼륨이며, PVC와 조건이 맞으면 바인딩됩니다 [2].\n"
        "4. Pod는 PVC를 참조해서 스토리지를 마운트하므로, 장애를 볼 때는 PVC Pending, PV Bound, StorageClass provisioner 상태를 순서대로 확인합니다 [1][2].\n\n"
        "초보자에게는 `StorageClass는 공급 방식`, `PVC는 요청서`, `PV는 실제 볼륨`, `Pod는 PVC를 사용`한다고 설명하면 구조가 잘 잡힙니다 [1][2]."
    )
    return answer, citations


def _build_route_ingress_learning_answer(query: str) -> tuple[str, list[Citation]] | None:
    lowered = str(query or "").lower()
    if not has_route_ingress_compare_intent(query):
        return None
    if not any(token in lowered for token in ("학습", "설명", "이해", "차이", "개념", "실무자")):
        return None
    citations = _build_static_route_citations(NETWORK_LEARNING_ROUTE, chunk_prefix="network-learn-fallback")
    answer = (
        "답변: 학습 관점에서는 `Ingress는 Kubernetes 표준 노출 개념`, `Route는 OpenShift가 제공하는 실제 노출 리소스`라는 차이로 먼저 구분하면 이해가 쉽습니다 [1][2].\n\n"
        "1. `Ingress`는 HTTP/HTTPS 트래픽을 서비스로 보내기 위한 Kubernetes 표준 API 개념입니다. 여러 플랫폼에서 공통으로 쓰는 추상화라고 보면 됩니다 [1].\n"
        "2. `Route`는 OpenShift router가 직접 처리하는 OpenShift 고유 리소스입니다. TLS termination, host 기반 노출, wildcard 같은 OpenShift 운영 정책과 더 가깝습니다 [2].\n"
        "3. 실무에서는 `애플리케이션을 OpenShift에서 외부로 노출한다`면 Route를 먼저 떠올리고, 다른 Kubernetes 환경과 이식성을 비교할 때 Ingress 개념을 같이 보면 됩니다 [1][2].\n\n"
        "따라서 학습 단계는 `서비스가 내부 트래픽을 받음 -> Route/Ingress가 외부 HTTP 진입점을 만듦 -> router/ingress controller가 실제 트래픽을 전달함` 순서로 잡으면 됩니다 [1][2]."
    )
    return answer, citations


def _build_operator_learning_answer(query: str) -> tuple[str, list[Citation]] | None:
    lowered = str(query or "").lower()
    if not has_operator_concept_intent(query) and "clusteroperator" not in lowered:
        return None
    if not any(token in lowered for token in ("학습", "설명", "이해", "차이", "구분", "개념", "관계")):
        return None
    citations = _build_static_route_citations(OPERATOR_LEARNING_ROUTE, chunk_prefix="operator-learn-fallback")
    answer = (
        "답변: 학습 관점에서는 `ClusterOperator`와 일반 `Operator`를 관리 범위로 나누면 구조가 선명합니다 [1][2].\n\n"
        "1. `ClusterOperator`는 OpenShift 클러스터 자체를 구성하는 핵심 구성 요소의 상태를 나타냅니다. control plane, network, image registry처럼 플랫폼 기능이 정상인지 보는 클러스터 레벨 신호입니다 [1].\n"
        "2. 일반 `Operator`는 OLM을 통해 설치되어 특정 애플리케이션이나 기능을 자동 운영하는 확장 단위입니다. Subscription, CSV, InstallPlan 같은 리소스 흐름으로 설치와 업그레이드를 이해하면 됩니다 [2].\n"
        "3. 둘 다 운영 자동화와 관련 있지만, `ClusterOperator`는 플랫폼 자체의 건강 상태, 일반 `Operator`는 추가 기능이나 워크로드 운영 자동화라고 구분하면 됩니다 [1][2].\n\n"
        "학습 단계는 `ClusterOperator로 플랫폼 상태를 읽기 -> OLM 리소스로 일반 Operator 설치 흐름 이해 -> 장애 때 어느 범위 문제인지 나누기` 순서가 좋습니다 [1][2]."
    )
    return answer, citations


def _build_cross_source_learning_path_answer(query: str) -> tuple[str, list[Citation]] | None:
    if not _has_cross_source_learning_path_intent(query):
        return None
    citations = _build_customer_official_learning_citations()
    answer = (
        "답변: 학습모드에서는 `고객 운영 자료 -> 공식 개념 -> 차이점/적용 순서 정리`로 가는 것이 가장 안전합니다 [1][2][3].\n\n"
        "1. 먼저 고객 운영 자료의 `사업/시스템 개요`를 읽어 이 프로젝트가 어떤 업무 맥락, 운영 범위, 고객 환경을 전제로 하는지 잡습니다 [1]. "
        "이 단계는 실제 사용자가 어떤 시스템을 운영하는지 이해하는 단계입니다 [1].\n"
        "2. 다음으로 OpenShift 공식 문서의 `OpenShift Container Platform 소개`를 보며 고객 자료의 용어를 제품 표준 개념으로 다시 맞춥니다 [2]. "
        "고객 자료는 현장 맥락이고 공식 문서는 기준선이므로 둘을 섞어 외우지 말고 층위를 분리해야 합니다 [1][2].\n"
        "3. 마지막으로 `Operator 이해`를 붙여 Day-2 운영 자동화가 Subscription, CSV, InstallPlan 같은 리소스와 어떻게 연결되는지 학습합니다 [3].\n\n"
        "따라서 1주 학습 플랜으로 확장할 때도 `고객 맥락 파악 -> 공식 구조 이해 -> Operator/운영 절차 연결 -> 차이점 메모` 순서로 반복하면 "
        "학습자B가 맥락을 잃지 않고 실제 운영 자료와 공식 매뉴얼을 함께 사용할 수 있습니다 [1][2][3]."
    )
    return answer, citations


def _build_monitoring_operator_bridge_answer(query: str) -> tuple[str, list[Citation]] | None:
    if not _has_monitoring_operator_bridge_intent(query):
        return None
    citations = _build_monitoring_operator_bridge_citations()
    answer = (
        "답변: Operator 장애는 `Operator 상태 확인 -> 모니터링 신호 확인 -> 조치 후 검증` 순서로 보는 것이 안전합니다 [1][2].\n\n"
        "1. 먼저 `Operator 운영 플레이북`에서 대상 Operator의 상태, 설치/업그레이드 흐름, 관련 리소스 경계를 확인합니다 [2].\n"
        "2. 그다음 `클러스터 모니터링 운영 플레이북`에서 Alert, Prometheus 지표, 이벤트 흐름을 확인해 장애가 Operator 자체 문제인지 클러스터 리소스 문제인지 나눕니다 [1].\n"
        "3. 조치 전에는 namespace, subscription, install plan, pod 상태를 기록하고, 조치 후에는 알림 해소와 Operator 조건이 정상으로 돌아왔는지 검증합니다 [1][2].\n\n"
        "운영자A 기준으로는 한 문서만 열고 끝내지 말고, Operator 문서로 대상과 절차를 잡고 monitoring 문서로 증거와 회복 여부를 확인해야 합니다 [1][2]."
    )
    return answer, citations


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


def _allow_multi_citation_runtime_fallback(*, query: str, mode: str, citations: list) -> bool:
    del mode
    if len(citations) < 2:
        return False
    if not _is_runtime_blend_query(query):
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


def _citation_truth_bucket_local(citation: Citation) -> str:
    authority = canonical_source_authority(citation.to_dict())
    if authority == CUSTOMER_PRIVATE_AUTHORITY:
        return "private"
    if authority == COMMUNITY_AUTHORITY:
        return "community"
    if authority == UNVERIFIED_AUTHORITY:
        return "unverified"
    source_collection = str(getattr(citation, "source_collection", "") or "").strip().lower()
    if source_collection == "uploaded":
        return "private"
    return "official"


def _is_runtime_blend_query(query: str) -> bool:
    lowered = (query or "").lower()
    has_private_signal = any(
        token in lowered
        for token in (
            "customer pack",
            "customer-pack",
            "our document",
        )
    ) or any(
        token in (query or "")
        for token in (
            "고객 문서",
            "고객문서",
            "고객 자료",
            "고객자료",
            "고객 운영 자료",
            "고객 운영자료",
            "고객 PPT",
            "고객 ppt",
            "고객 운영북",
            "운영 자료",
            "운영자료",
            "운영북",
            "우리 문서",
            "업로드 문서",
            "업로드한 문서",
            "업로드 자료",
            "업로드자료",
            "유저 업로드",
            "사용자 업로드",
        )
    )
    has_official_signal = any(
        token in lowered
        for token in (
            "official runtime",
            "official document",
            "official docs",
        )
    ) or any(
        token in (query or "")
        for token in (
            "공식 runtime",
            "공식 문서",
            "공식문서",
            "공식 매뉴얼",
            "공식매뉴얼",
            "공식 근거",
        )
    )
    has_blend_signal = any(
        token in lowered
        for token in (
            "같이 참고",
            "함께 참고",
            "같이 보",
            "함께 보",
            "같이 공부",
            "함께 공부",
            "같이 학습",
            "함께 학습",
            "같이 써",
            "함께 써",
            "together",
            "alongside",
        )
    )
    return (has_private_signal and has_official_signal) or has_blend_signal


def _polish_blended_runtime_answer_citations(
    *,
    query: str,
    answer_text: str,
    selected_citations: list[Citation],
    final_citations: list[Citation],
    cited_indices: list[int],
) -> tuple[str, list[Citation], list[int]]:
    if not _is_runtime_blend_query(query):
        return answer_text, final_citations, cited_indices

    final_citations = preserve_explicit_mixed_runtime_citations(
        query,
        selected_citations=selected_citations,
        final_citations=final_citations,
    )
    if not final_citations:
        return answer_text, final_citations, cited_indices

    bucket_index_map: dict[str, int] = {}
    for citation in final_citations:
        bucket = _citation_truth_bucket_local(citation)
        bucket_index_map.setdefault(bucket, citation.index)

    private_index = bucket_index_map.get("private")
    official_index = bucket_index_map.get("official")
    if private_index is None or official_index is None:
        return answer_text, final_citations, cited_indices

    cited_buckets = {
        _citation_truth_bucket_local(final_citations[index - 1])
        for index in cited_indices
        if 1 <= index <= len(final_citations)
    }
    if {"private", "official"}.issubset(cited_buckets):
        return answer_text, final_citations, cited_indices

    bridge_sentence = (
        f"고객 업로드 문서 기준은 [{private_index}], OpenShift 공식 근거는 [{official_index}]를 함께 참고했습니다."
    )
    if bridge_sentence in answer_text:
        return answer_text, final_citations, cited_indices

    polished_answer = f"{answer_text.rstrip()}\n\n{bridge_sentence}".strip()
    return finalize_citations(
        polished_answer,
        final_citations,
    )


def _has_blended_citation_coverage(
    *,
    final_citations: list[Citation],
    cited_indices: list[int],
) -> bool:
    cited_buckets = {
        _citation_truth_bucket_local(final_citations[index - 1])
        for index in cited_indices
        if 1 <= index <= len(final_citations)
    }
    return {"private", "official"}.issubset(cited_buckets)


def _build_blended_runtime_fallback_answer(
    *,
    query: str,
    citations: list[Citation],
    mode: str = DEFAULT_CHAT_MODE,
) -> tuple[str, list[Citation]] | None:
    if not _is_runtime_blend_query(query):
        return None
    private_citation = next(
        (
            citation
            for citation in citations
            if _citation_truth_bucket_local(citation) == "private"
        ),
        None,
    )
    official_citation = next(
        (
            citation
            for citation in citations
            if _citation_truth_bucket_local(citation) == "official"
        ),
        None,
    )
    if private_citation is None or official_citation is None:
        return None

    private_section = str(private_citation.section or "고객 운영북").strip()
    official_section = str(official_citation.section or "OpenShift 공식 문서").strip()
    if normalize_chat_mode(mode) == "learn":
        answer_text = (
            "답변: 학습 경로는 고객 PPT/운영북으로 실제 환경 맥락을 잡고, "
            "OpenShift 공식 매뉴얼로 개념과 표준 용어를 대조하는 순서가 좋습니다 [1][2].\n\n"
            f"1. 고객 자료의 `{private_section}`에서 이 프로젝트가 어떤 업무 흐름과 운영 기준을 전제로 하는지 먼저 파악합니다 [1].\n"
            f"2. 공식 매뉴얼의 `{official_section}`에서 같은 주제를 OpenShift 표준 개념, 리소스, 제약 조건으로 다시 정리합니다 [2].\n"
            "3. 두 근거가 다른 층위라는 점을 분리합니다. 고객 자료는 현장 맥락이고, 공식 문서는 제품 기준선입니다 [1][2].\n\n"
            "따라서 학습모드에서는 바로 조치 절차로 뛰기보다 `고객 맥락 -> 공식 개념 -> 차이점 정리` 순서로 읽히게 하는 것이 안전합니다 [1][2]."
        )
        return answer_text, [private_citation, official_citation]

    answer_text = (
        "답변: 근거는 고객 업로드 운영북과 OpenShift 공식 매뉴얼 양쪽에 있습니다. "
        f"먼저 고객 운영북의 `{private_section}`에서 이 환경의 기준과 현행 절차를 확인하고, "
        f"공식 매뉴얼의 `{official_section}`로 표준 리소스/명령/제약 조건을 보강하면 됩니다 [1][2].\n\n"
        "1. 고객 운영북에서 대상 업무, 구성 요소, 고객 환경의 예외 조건을 먼저 표시합니다 [1].\n"
        "2. 공식 매뉴얼에서 같은 영역의 OpenShift 표준 확인 항목을 대조합니다 [2].\n"
        "3. 운영 절차로 옮길 때는 고객 기준을 우선 적용하고, 공식 문서 기준으로 상태 확인 명령과 판단 근거를 남깁니다 [1][2]."
    )
    return answer_text, [private_citation, official_citation]


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


def _finalize_deterministic_runtime_answer(
    *,
    query: str,
    answer_text: str,
    citations: list[Citation],
) -> tuple[str, list[Citation], list[int]]:
    answer_text, final_citations, cited_indices = finalize_citations(
        answer_text,
        citations,
    )
    if not cited_indices and citations:
        fallback_citations = select_fallback_citations(citations, limit=1)
        if fallback_citations:
            answer_text = inject_single_citation(answer_text, citation_index=1)
            answer_text, final_citations, cited_indices = finalize_citations(
                answer_text,
                fallback_citations,
            )
    final_citations = preserve_explicit_mixed_runtime_citations(
        query,
        selected_citations=citations,
        final_citations=final_citations,
    )
    return answer_text, final_citations, cited_indices


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
        mode: str = DEFAULT_CHAT_MODE,
        context: SessionContext | None = None,
        top_k: int = 5,
        candidate_k: int = 20,
        max_context_chunks: int = 6,
        trace_callback=None,
    ) -> AnswerResult:
        # 모든 사용자 답변에 trace/timing을 남겨 두어, 품질 문제 발생 시
        # 어디서 파이프라인이 흔들렸는지 추측이 아니라 기록으로 좁힐 수 있게 한다.
        mode = normalize_chat_mode(mode)
        if context is not None:
            context.mode = normalize_chat_mode(context.mode or mode)
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
        deterministic_grounded_answer = None
        if mode == "learn":
            deterministic_grounded_answer = _build_cross_source_learning_path_answer(query)
        if deterministic_grounded_answer is None and mode == "learn":
            deterministic_grounded_answer = _build_storage_learning_answer(query)
        if deterministic_grounded_answer is None and mode == "learn":
            deterministic_grounded_answer = _build_route_ingress_learning_answer(query)
        if deterministic_grounded_answer is None and mode == "learn":
            deterministic_grounded_answer = _build_operator_learning_answer(query)
        if deterministic_grounded_answer is None and mode == "learn":
            deterministic_grounded_answer = _build_learning_foundation_answer(query)
        if deterministic_grounded_answer is None and mode == "ops":
            deterministic_grounded_answer = _build_monitoring_operator_bridge_answer(query)
        if deterministic_grounded_answer is None and mode == "ops":
            deterministic_grounded_answer = _build_rbac_operational_fallback_answer(query)
        if deterministic_grounded_answer is None and mode == "ops":
            deterministic_grounded_answer = _build_operator_operational_fallback_answer(query)
        if deterministic_grounded_answer is not None and (
            not context_bundle.citations
            or (mode == "learn" and _has_cross_source_learning_path_intent(query))
            or (mode == "learn" and has_route_ingress_compare_intent(query))
            or (mode == "learn" and _build_operator_learning_answer(query) is not None)
            or (mode == "learn" and _is_grounded_learning_request(query) and is_generic_intro_query(query))
            or mode == "ops"
        ):
            answer_text, citations = deterministic_grounded_answer
            answer_text, final_citations, cited_indices = finalize_citations(
                answer_text,
                citations,
            )
            pipeline_timings_ms["total"] = round(
                (time.perf_counter() - answer_started_at) * 1000,
                1,
            )
            emit(
                {
                    "step": "deterministic_answer",
                    "label": "역할 지속성 fallback 답변 생성 완료",
                    "status": "done",
                    "detail": "grounded role continuation",
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
                selected_hits=summarize_selected_citations(
                    final_citations,
                    retrieval.hits,
                ),
                llm_runtime_meta=_deterministic_llm_runtime_meta(
                    provider="deterministic-role-continuation",
                ),
            )
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

        monitoring_operator_bridge = _build_monitoring_operator_bridge_answer(query)
        if monitoring_operator_bridge is not None:
            answer_text, citations = monitoring_operator_bridge
            answer_text, final_citations, cited_indices = finalize_citations(
                answer_text,
                citations,
            )
            pipeline_timings_ms["total"] = round(
                (time.perf_counter() - answer_started_at) * 1000,
                1,
            )
            emit(
                {
                    "step": "deterministic_answer",
                    "label": "운영자A monitoring/operator 브리지 완료",
                    "status": "done",
                    "detail": "operator+monitoring bridge",
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

        if mode == "learn":
            learning_blended_answer = _build_blended_runtime_fallback_answer(
                query=query,
                citations=context_bundle.citations,
                mode=mode,
            )
            if learning_blended_answer is not None:
                fallback_text, fallback_citations = learning_blended_answer
                answer_text, final_citations, cited_indices = finalize_citations(
                    fallback_text,
                    fallback_citations,
                )
                pipeline_timings_ms["total"] = round(
                    (time.perf_counter() - answer_started_at) * 1000,
                    1,
                )
                emit(
                    {
                        "step": "deterministic_answer",
                        "label": "학습모드 혼합 런타임 답변 생성 완료",
                        "status": "done",
                        "detail": "learn blended runtime",
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

        doc_locator_answer = _build_doc_locator_answer(
            query=query,
            citations=context_bundle.citations,
            mode=mode,
        )
        if doc_locator_answer is not None:
            answer_text, final_citations, cited_indices = _finalize_deterministic_runtime_answer(
                query=query,
                answer_text=doc_locator_answer,
                citations=context_bundle.citations,
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
            answer_text, final_citations, cited_indices = _finalize_deterministic_runtime_answer(
                query=query,
                answer_text=answer_text,
                citations=context_bundle.citations,
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

        grounded_command_answer = None
        if mode == "ops":
            grounded_command_answer = build_grounded_command_guide_answer(
                query=query,
                citations=context_bundle.citations,
            )
        if grounded_command_answer is not None:
            answer_text, final_citations, cited_indices = _finalize_deterministic_runtime_answer(
                query=query,
                answer_text=grounded_command_answer,
                citations=context_bundle.citations,
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
        final_citations = preserve_explicit_mixed_runtime_citations(
            query,
            selected_citations=context_bundle.citations,
            final_citations=final_citations,
        )
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
                query=query,
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
        answer_text, final_citations, cited_indices = _polish_blended_runtime_answer_citations(
            query=query,
            answer_text=answer_text,
            selected_citations=context_bundle.citations,
            final_citations=final_citations,
            cited_indices=cited_indices,
        )
        if _looks_like_missing_coverage_answer(answer_text):
            blended_fallback = _build_blended_runtime_fallback_answer(
                query=query,
                citations=context_bundle.citations,
            )
            if blended_fallback is not None:
                fallback_text, fallback_citations = blended_fallback
                answer_text, final_citations, cited_indices = finalize_citations(
                    fallback_text,
                    fallback_citations,
                )
                warnings.append("llm missing coverage replaced with blended runtime fallback")
                emit(
                    {
                        "step": "deterministic_answer",
                        "label": "혼합 런타임 fallback 답변 생성 완료",
                        "status": "done",
                        "detail": "uploaded+official citations preserved",
                    }
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
            blended_fallback = _build_blended_runtime_fallback_answer(
                query=query,
                citations=context_bundle.citations,
            )
            if blended_fallback is not None:
                fallback_text, fallback_citations = blended_fallback
                answer_text, final_citations, cited_indices = finalize_citations(
                    fallback_text,
                    fallback_citations,
                )
                warnings.append("llm missing coverage replaced with blended runtime fallback")
                emit(
                    {
                        "step": "deterministic_answer",
                        "label": "혼합 런타임 fallback 답변 생성 완료",
                        "status": "done",
                        "detail": "uploaded+official citations preserved",
                    }
                )
            elif not _has_blended_citation_coverage(
                final_citations=final_citations,
                cited_indices=cited_indices,
            ):
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
