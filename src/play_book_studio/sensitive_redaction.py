from __future__ import annotations

import re

SENSITIVE_NETWORK_NOTICE = (
    "운영 도메인/hosts 원문은 보안 보호를 위해 화면에서 마스킹했습니다. "
    "필요한 경우 승인된 보안 채널의 원본 문서를 확인하세요."
)

_SENSITIVE_NETWORK_CONTEXT_RE = re.compile(
    r"\bhosts?\b|host\s*file|\bdns\b|\bdomain\b|운영\s*도메인|도메인\s*hosts|hosts\s*내용|도메인\s*구성|서비스\s*도메인|네트워크\s*매핑|서버\s*목록",
    re.IGNORECASE,
)
_IPV4_RE = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"
)
_PRIVATE_IPV4_RE = re.compile(
    r"\b(?:10\.(?:25[0-5]|2[0-4]\d|1?\d?\d)\.(?:25[0-5]|2[0-4]\d|1?\d?\d)\.(?:25[0-5]|2[0-4]\d|1?\d?\d)"
    r"|192\.168\.(?:25[0-5]|2[0-4]\d|1?\d?\d)\.(?:25[0-5]|2[0-4]\d|1?\d?\d)"
    r"|172\.(?:1[6-9]|2\d|3[0-1])\.(?:25[0-5]|2[0-4]\d|1?\d?\d)\.(?:25[0-5]|2[0-4]\d|1?\d?\d))\b"
)
_DOMAIN_RE = re.compile(
    r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"(?:com|net|org|io|dev|app|cloud|local|internal|corp|kr|co\.kr)\b",
    re.IGNORECASE,
)
_HOST_MAPPING_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\s+[a-z0-9.-]+\.[a-z]{2,}\b", re.IGNORECASE)


def _count_unique(pattern: re.Pattern[str], text: str) -> int:
    return len({match.group(0).lower() for match in pattern.finditer(text)})


def looks_like_sensitive_network_block(text: str, *, context: str = "") -> bool:
    normalized_text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(normalized_text) < 24:
        return False
    normalized_context = re.sub(r"\s+", " ", str(context or "")).strip()
    has_network_context = bool(_SENSITIVE_NETWORK_CONTEXT_RE.search(f"{normalized_context} {normalized_text}"))
    ipv4_count = _count_unique(_IPV4_RE, normalized_text)
    private_ipv4_count = _count_unique(_PRIVATE_IPV4_RE, normalized_text)
    domain_count = _count_unique(_DOMAIN_RE, normalized_text)
    host_mapping_count = len(_HOST_MAPPING_RE.findall(normalized_text))
    if has_network_context and (ipv4_count > 0 or domain_count > 1 or host_mapping_count > 0):
        return True
    if has_network_context and domain_count >= 5:
        return True
    if domain_count >= 5 and len(normalized_text) < 2000:
        return True
    if private_ipv4_count >= 2 and domain_count > 0:
        return True
    return ipv4_count >= 3 and domain_count >= 2


def redact_sensitive_network_text_for_display(text: str, *, context: str = "") -> str:
    raw = str(text or "")
    if looks_like_sensitive_network_block(raw, context=context):
        return SENSITIVE_NETWORK_NOTICE
    return raw
