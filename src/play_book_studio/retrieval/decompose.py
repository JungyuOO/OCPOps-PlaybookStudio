# retrieval subquery 분해 전용 파일.
# 질문을 더 잘 찾기 쉬운 보조 쿼리들로 나눌 때 이 모듈을 본다.

from __future__ import annotations

import re

from .text_utils import collapse_spaces, dedupe_queries


def decompose_retrieval_queries(query: str) -> list[str]:
    from .query import (
        COMPARE_DECOMPOSE_RE,
        CONJUNCTION_SPLIT_RE,
        NODE_NOTREADY_RE,
        POD_LIFECYCLE_RE,
        ROUTE_TIMEOUT_RE,
        has_deployment_scaling_intent,
        has_update_doc_locator_intent,
        is_explainer_query,
    )

    normalized = collapse_spaces(query)
    if not normalized:
        return []

    if has_update_doc_locator_intent(normalized):
        return dedupe_queries(
            [
                normalized,
                "OpenShift 클러스터 업데이트 가이드",
                "OpenShift 릴리스 노트",
                "업데이트 전 준비 문서",
            ]
        )

    if ROUTE_TIMEOUT_RE.search(normalized):
        return dedupe_queries(
            [
                normalized,
                "haproxy.router.openshift.io/timeout annotation",
                "route timeout duration increase",
            ]
        )

    if NODE_NOTREADY_RE.search(normalized):
        return dedupe_queries(
            [
                normalized,
                "oc describe node nodes",
                "journalctl -u kubelet logs",
                "oc adm node-logs --role worker",
                "troubleshooting worker node NotReady status",
                "node describe journalctl",
            ]
        )

    if has_deployment_scaling_intent(normalized):
        return dedupe_queries(
            [
                normalized,
                "oc scale deployment replicas",
                "deployment 수동 스케일링",
                "oc scale --replicas deployment",
            ]
        )

    if POD_LIFECYCLE_RE.search(normalized) and is_explainer_query(normalized):
        return dedupe_queries(
            [
                normalized,
                "Pod 정의와 Pod phase 개념",
                "Pod status와 phase 차이",
                "파드 생명주기 개념",
            ]
        )

    compare_match = COMPARE_DECOMPOSE_RE.match(normalized)
    if compare_match:
        left = collapse_spaces(compare_match.group("left"))
        right = collapse_spaces(compare_match.group("right"))
        return dedupe_queries(
            [
                normalized,
                f"{left} 개요",
                f"{right} 개요",
            ]
        )

    question_parts = [
        collapse_spaces(part)
        for part in re.split(r"\?\s*", normalized)
        if collapse_spaces(part)
    ]
    if len(question_parts) > 1:
        return dedupe_queries([normalized, *question_parts])

    if "그리고" in normalized or re.search(r"\band\b", normalized, re.IGNORECASE):
        parts = [
            collapse_spaces(part)
            for part in CONJUNCTION_SPLIT_RE.split(normalized)
            if collapse_spaces(part)
        ]
        substantial_parts = [part for part in parts if len(part) >= 6]
        if len(substantial_parts) >= 2:
            return dedupe_queries([normalized, *substantial_parts[:2]])

    return [normalized]
