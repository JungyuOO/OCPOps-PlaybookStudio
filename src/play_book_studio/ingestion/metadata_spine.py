"""Deterministic metadata spine for answer-ready wiki chunks."""

from __future__ import annotations

import re
from typing import Any

from .metadata_extraction import extract_text_metadata


TOPIC_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("install", ("install", "installation", "설치", "bootstrap", "upi", "ipi")),
    ("networking", ("network", "route", "ingress", "service", "dns", "네트워크", "라우트")),
    ("security", ("scc", "rbac", "rolebinding", "clusterrole", "security", "권한", "보안")),
    ("storage", ("storage", "pvc", "pv", "ceph", "odf", "스토리지", "볼륨")),
    ("monitoring", ("monitor", "prometheus", "alert", "metric", "모니터링", "알람")),
    ("troubleshooting", ("error", "failed", "crashloop", "backoff", "troubleshoot", "장애", "오류", "실패")),
    ("ops", ("operator", "upgrade", "backup", "restore", "운영", "점검", "검증")),
)

SEMANTIC_ROLES = frozenset({"concept", "procedure", "command", "config", "troubleshooting", "reference"})
YAML_SIGNAL_RE = re.compile(r"(?m)^\s*(?:apiVersion|kind|metadata|spec|rules|subjects|roleRef)\s*:")
CODE_FENCE_RE = re.compile(r"```")
COMMAND_RE = re.compile(r"(?m)^\s*(?:[$#][ \t]*)?(?:oc|kubectl|helm|curl|podman|docker)[ \t]+")
COMMAND_LINE_RE = re.compile(r"^\s*(?:[$#][ \t]*)?(?:oc|kubectl|helm|curl|podman|docker)[ \t]+\S+", re.IGNORECASE)


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(normalized)
    return output


def _clean_cli_commands(values: list[str]) -> list[str]:
    output: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or "\n" in normalized or "[/CODE]" in normalized or "[CODE]" in normalized:
            continue
        if not COMMAND_LINE_RE.match(normalized):
            continue
        output.append(normalized)
    return _ordered_unique(output)


def _clean_answerable_questions(values: list[str]) -> list[str]:
    output: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or "\n" in normalized or "[/CODE]" in normalized or "[CODE]" in normalized:
            continue
        output.append(normalized)
    return _ordered_unique(output)


def infer_topic(text: str, *, section_path: tuple[str, ...] = (), filename: str = "") -> str:
    haystack = " ".join([filename, *section_path, text]).lower()
    for topic, keywords in TOPIC_KEYWORDS:
        if any(keyword.lower() in haystack for keyword in keywords):
            return topic
    return "ops"


def infer_semantic_role(text: str, *, block_kinds: tuple[str, ...] = (), existing: str = "") -> str:
    normalized_existing = str(existing or "").strip().lower()
    if normalized_existing in SEMANTIC_ROLES:
        return normalized_existing
    kinds = {str(item or "").strip().lower() for item in block_kinds if str(item or "").strip()}
    lower_text = text.lower()
    if "code" in kinds or YAML_SIGNAL_RE.search(text):
        return "config"
    if COMMAND_RE.search(text):
        return "command"
    if any(token in lower_text for token in ("crashloop", "imagepull", "error", "failed", "forbidden", "오류", "실패", "장애")):
        return "troubleshooting"
    if any(token in lower_text for token in ("step", "procedure", "다음", "순서", "실행", "확인합니다")):
        return "procedure"
    if any(kind in {"table", "reference"} for kind in kinds):
        return "reference"
    return "concept"


def build_answerable_questions(
    *,
    topic: str,
    semantic_role: str,
    section_path: tuple[str, ...],
    k8s_objects: list[str],
    cli_commands: list[str],
    error_strings: list[str],
) -> list[str]:
    title = next((part for part in reversed(section_path) if str(part).strip()), "")
    subject = title or (k8s_objects[0] if k8s_objects else topic)
    questions: list[str] = []
    if subject:
        questions.append(f"{subject}는 무엇을 확인해야 하나요?")
    if semantic_role in {"procedure", "command", "config"} and cli_commands:
        questions.append(f"{cli_commands[0]} 명령은 언제 사용하나요?")
    if semantic_role == "troubleshooting" or error_strings:
        target = error_strings[0] if error_strings else subject
        questions.append(f"{target} 문제가 나면 무엇부터 봐야 하나요?")
    if k8s_objects:
        questions.append(f"{k8s_objects[0]} 관련 상태는 어떻게 검증하나요?")
    return _ordered_unique(questions)[:4]


def metadata_confidence(
    *,
    semantic_role: str,
    topic: str,
    k8s_objects: list[str],
    cli_commands: list[str],
    verification_hints: list[str],
    answerable_questions: list[str],
) -> str:
    score = 0
    if topic:
        score += 1
    if semantic_role and semantic_role != "unknown":
        score += 1
    if k8s_objects:
        score += 1
    if cli_commands:
        score += 1
    if verification_hints:
        score += 1
    if answerable_questions:
        score += 1
    if score >= 5:
        return "high"
    if score >= 3:
        return "medium"
    return "low"


def build_chunk_metadata_spine(
    text: str,
    *,
    section_path: tuple[str, ...] = (),
    filename: str = "",
    source_scope: str = "",
    block_kinds: tuple[str, ...] = (),
    existing_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    existing = dict(existing_metadata or {})
    extracted = extract_text_metadata(text)
    cli_commands = _clean_cli_commands([*list(existing.get("cli_commands") or []), *list(extracted.cli_commands)])
    error_strings = _ordered_unique([*list(existing.get("error_strings") or []), *list(extracted.error_strings)])
    k8s_objects = _ordered_unique([*list(existing.get("k8s_objects") or []), *list(extracted.k8s_objects)])
    if "SecurityContextConstraints" in k8s_objects and "SCC" not in k8s_objects:
        k8s_objects.append("SCC")
    if re.search(r"RBAC|Role-?Based Access Control|역할 기반", text, re.IGNORECASE) and "RBAC" not in k8s_objects:
        k8s_objects.append("RBAC")
    operator_names = _ordered_unique([*list(existing.get("operator_names") or []), *list(extracted.operator_names)])
    verification_hints = _ordered_unique([*list(existing.get("verification_hints") or []), *list(extracted.verification_hints)])
    semantic_role = infer_semantic_role(
        text,
        block_kinds=block_kinds,
        existing=str(existing.get("semantic_role") or ""),
    )
    topic = str(existing.get("topic") or "").strip() or infer_topic(text, section_path=section_path, filename=filename)
    answerable_questions = _clean_answerable_questions(
        [
            *list(existing.get("answerable_questions") or []),
            *build_answerable_questions(
                topic=topic,
                semantic_role=semantic_role,
                section_path=section_path,
                k8s_objects=k8s_objects,
                cli_commands=cli_commands,
                error_strings=error_strings,
            ),
        ]
    )
    confidence = metadata_confidence(
        semantic_role=semantic_role,
        topic=topic,
        k8s_objects=k8s_objects,
        cli_commands=cli_commands,
        verification_hints=verification_hints,
        answerable_questions=answerable_questions,
    )
    if CODE_FENCE_RE.search(text) or YAML_SIGNAL_RE.search(text):
        block_kinds = tuple(_ordered_unique([*list(block_kinds), "code"]))
    return {
        "metadata_spine_schema": "metadata_spine_v1",
        "topic": topic,
        "semantic_role": semantic_role,
        "k8s_objects": k8s_objects,
        "cli_commands": cli_commands,
        "error_strings": error_strings,
        "operator_names": operator_names,
        "verification_hints": verification_hints,
        "answerable_questions": answerable_questions,
        "metadata_confidence": confidence,
        "source_scope": str(source_scope or existing.get("source_scope") or "").strip(),
        "block_kinds": list(block_kinds),
    }


__all__ = [
    "build_chunk_metadata_spine",
    "build_answerable_questions",
    "infer_semantic_role",
    "infer_topic",
    "metadata_confidence",
]
