"""코퍼스 범위 밖 질문과 버전 이탈을 판별하는 helper 모듈이다."""

from __future__ import annotations

import re


VERSION_RE = re.compile(r"(?<!\d)4\.(\d+)(?!\d)")
OCP_RE = re.compile(r"(?<![a-z0-9])ocp(?![a-z0-9])", re.IGNORECASE)
OPENSHIFT_RE = re.compile(r"(오픈시프트|openshift)", re.IGNORECASE)
UNSUPPORTED_PRODUCTS = (
    "argo cd",
    "argocd",
    "harbor",
    "eks",
    "aks",
    "gke",
    "anthos",
    "rancher",
)
UNSUPPORTED_INTENT_RE = re.compile(
    r"(설치|install|비교|compare|가격|요금|cost|비용|방법|어떻게)",
    re.IGNORECASE,
)


def detect_unsupported_product(query: str) -> str | None:
    lowered = (query or "").lower()
    if OPENSHIFT_RE.search(query or "") or OCP_RE.search(lowered):
        return None
    if not UNSUPPORTED_INTENT_RE.search(query or ""):
        return None
    for product in UNSUPPORTED_PRODUCTS:
        if product in lowered:
            return product
    return None


def detect_out_of_corpus_version(query: str, *, corpus_version: str = "4.20") -> str | None:
    normalized = query or ""
    if not (OPENSHIFT_RE.search(normalized) or OCP_RE.search(normalized)):
        return None
    corpus_match = VERSION_RE.search(corpus_version)
    corpus_minor = corpus_match.group(1) if corpus_match else "20"
    for match in VERSION_RE.finditer(normalized):
        if match.group(1) != corpus_minor:
            return f"4.{match.group(1)}"
    return None
