from __future__ import annotations

import re
from typing import Any


DESIGN_ID_RE = re.compile(r"DSGN-005-\d{3}", re.IGNORECASE)
UNIT_TEST_ID_RE = re.compile(r"TEST-UN-OCP-\d{2}-\d{2}", re.IGNORECASE)
CHAPTER_COUNTER_RE = re.compile(r"\b[IVX]+\b.*\(\d+/\d+\)", re.IGNORECASE)
CHAPTER_HEADING_RE = re.compile(r"[ⅠⅡⅢⅣⅤⅥIVX]+\.", re.IGNORECASE)
PERF_KEYWORDS = ("성능", "부하", "튜닝", "throughput", "latency", "TPS")
INTEGRATION_KEYWORDS = ("통합", "integration", "시나리오", "연계")
UNIT_TEST_KEYWORDS = ("단위 테스트", "unit test", "단위테스트")


def classify_template_family(slides: list[dict[str, Any]]) -> str:
    deck_text = " ".join(str(item.get("text_blob") or "") for item in slides).strip()
    if not deck_text:
        return "unknown"
    if DESIGN_ID_RE.search(deck_text):
        return "architecture"
    if UNIT_TEST_ID_RE.search(deck_text):
        return "unit_test"
    lowered = deck_text.lower()
    if CHAPTER_COUNTER_RE.search(deck_text) or sum(1 for slide in slides if CHAPTER_HEADING_RE.search(str(slide.get("text_blob") or ""))) >= 3:
        return "completion_report"
    if any(keyword.lower() in lowered for keyword in UNIT_TEST_KEYWORDS):
        return "unit_test"
    if any(keyword.lower() in lowered for keyword in PERF_KEYWORDS):
        return "perf_test"
    if any(keyword.lower() in lowered for keyword in INTEGRATION_KEYWORDS):
        return "integration_test"
    return "unknown"


__all__ = ["classify_template_family", "DESIGN_ID_RE", "UNIT_TEST_ID_RE"]
