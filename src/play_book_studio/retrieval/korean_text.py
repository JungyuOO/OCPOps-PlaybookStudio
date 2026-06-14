"""Shared lightweight Korean text normalization for retrieval signals."""

from __future__ import annotations

import re


TOKEN_RE = re.compile(r"[\uac00-\ud7a3]+|[A-Za-z0-9_.-]+")
HANGUL_RE = re.compile(r"^[\uac00-\ud7a3]+$")

KOREAN_SUFFIXES: tuple[str, ...] = tuple(
    sorted(
        {
            "에서는",
            "에게서",
            "부터",
            "까지",
            "으로는",
            "으로",
            "에게",
            "한테",
            "처럼",
            "마다",
            "보다",
            "라고",
            "에서",
            "은",
            "는",
            "이",
            "가",
            "을",
            "를",
            "와",
            "과",
            "의",
            "도",
            "만",
            "로",
            "에",
        },
        key=len,
        reverse=True,
    )
)


def normalize_korean_token(token: str) -> str:
    normalized = str(token or "").strip().lower()
    if not normalized or not HANGUL_RE.fullmatch(normalized):
        return normalized
    for suffix in KOREAN_SUFFIXES:
        if normalized.endswith(suffix) and len(normalized) - len(suffix) >= 2:
            return normalized[: -len(suffix)]
    return normalized


def tokenize_normalized_text(text: str) -> list[str]:
    tokens: list[str] = []
    for raw_token in TOKEN_RE.findall(text or ""):
        normalized = normalize_korean_token(raw_token)
        if len(normalized) >= 2:
            tokens.append(normalized)
    return tokens


def normalized_token_set(*texts: str) -> set[str]:
    return set(tokenize_normalized_text(" ".join(str(text or "") for text in texts)))


__all__ = ["normalize_korean_token", "normalized_token_set", "tokenize_normalized_text"]
