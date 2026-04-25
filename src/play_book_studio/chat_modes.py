from __future__ import annotations

from typing import Any

CHAT_MODE_LEARN = "learn"
CHAT_MODE_OPS = "ops"
DEFAULT_CHAT_MODE = CHAT_MODE_OPS
SUPPORTED_CHAT_MODES = (CHAT_MODE_LEARN, CHAT_MODE_OPS)
LEGACY_CHAT_MODES = {
    "chat": CHAT_MODE_OPS,
    "guided_tour": CHAT_MODE_LEARN,
    "atlas_canvas": CHAT_MODE_OPS,
    "encyclopedia_world": CHAT_MODE_LEARN,
}


def normalize_chat_mode(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in SUPPORTED_CHAT_MODES:
        return raw
    return LEGACY_CHAT_MODES.get(raw, DEFAULT_CHAT_MODE)


def chat_mode_contract() -> dict[str, object]:
    return {
        "default_mode": DEFAULT_CHAT_MODE,
        "supported_modes": [
            {
                "id": CHAT_MODE_LEARN,
                "label": "학습 모드",
                "contract": "개념, 구조, 교육 경로, 공식/고객 근거 비교를 citation 기반으로 설명한다.",
                "hallucination_guard": "근거에 없는 명령이나 절차를 운영 지시처럼 만들지 않는다.",
            },
            {
                "id": CHAT_MODE_OPS,
                "label": "운영 모드",
                "contract": "점검 순서, 장애 대응, 명령, 검증 포인트를 근거 기반으로 제시한다.",
                "hallucination_guard": "근거 없는 원인 단정과 미검증 조치 지시를 차단한다.",
            },
        ],
        "legacy_mode_mapping": dict(LEGACY_CHAT_MODES),
    }


__all__ = [
    "CHAT_MODE_LEARN",
    "CHAT_MODE_OPS",
    "DEFAULT_CHAT_MODE",
    "SUPPORTED_CHAT_MODES",
    "chat_mode_contract",
    "normalize_chat_mode",
]
