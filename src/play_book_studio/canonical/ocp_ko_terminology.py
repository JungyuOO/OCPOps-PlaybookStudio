"""Preferred OCP Korean terminology for official-source translation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OcpKoTerminologyEntry:
    source: str
    preferred_ko: str
    notes: str = ""


OCP_KO_TERMINOLOGY = (
    OcpKoTerminologyEntry(
        source="Hosted control planes overview",
        preferred_ko="호스팅된 컨트롤 플레인 개요",
    ),
    OcpKoTerminologyEntry(
        source="Hosted control planes",
        preferred_ko="호스팅된 컨트롤 플레인",
    ),
    OcpKoTerminologyEntry(
        source="hosted control planes",
        preferred_ko="호스팅된 컨트롤 플레인",
    ),
    OcpKoTerminologyEntry(
        source="hosted control plane",
        preferred_ko="호스팅된 컨트롤 플레인",
    ),
    OcpKoTerminologyEntry(
        source="control planes",
        preferred_ko="컨트롤 플레인",
    ),
    OcpKoTerminologyEntry(
        source="control plane",
        preferred_ko="컨트롤 플레인",
    ),
    OcpKoTerminologyEntry(
        source="hosted cluster",
        preferred_ko="호스팅된 클러스터",
    ),
    OcpKoTerminologyEntry(
        source="management cluster",
        preferred_ko="관리 클러스터",
    ),
    OcpKoTerminologyEntry(
        source="HyperShift",
        preferred_ko="HyperShift",
        notes="Do not translate product name.",
    ),
    OcpKoTerminologyEntry(
        source="NodePool",
        preferred_ko="NodePool",
        notes="Do not translate resource name.",
    ),
    OcpKoTerminologyEntry(
        source="NodePools",
        preferred_ko="NodePools",
        notes="Do not translate resource name.",
    ),
)


OCP_KO_NORMALIZATION_RULES = (
    ("호스팅 제어 평면 개요", "호스팅된 컨트롤 플레인 개요"),
    ("호스트된 제어 평면 개요", "호스팅된 컨트롤 플레인 개요"),
    ("호스팅 제어 평면", "호스팅된 컨트롤 플레인"),
    ("호스트된 제어 평면", "호스팅된 컨트롤 플레인"),
    ("제어 평면", "컨트롤 플레인"),
)


def ocp_ko_terminology_prompt() -> str:
    lines = [
        "Use the following preferred OpenShift Korean terminology exactly when applicable.",
        "Do not invent alternate Korean paraphrases for these terms.",
    ]
    for entry in OCP_KO_TERMINOLOGY:
        line = f"- {entry.source} -> {entry.preferred_ko}"
        if entry.notes:
            line = f"{line} ({entry.notes})"
        lines.append(line)
    return "\n".join(lines)


def normalize_ocp_ko_terminology(text: str) -> str:
    normalized = text or ""
    for before, after in OCP_KO_NORMALIZATION_RULES:
        normalized = normalized.replace(before, after)
    return normalized
