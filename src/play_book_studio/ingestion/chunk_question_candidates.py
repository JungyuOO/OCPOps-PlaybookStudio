"""Derive beginner starter/follow-up question candidates from chunk content.

The functions here generate questions from chunk metadata and text. They do
not use fixed query-answer mappings and do not expose eval JSONL queries.
"""

from __future__ import annotations

import re
from typing import Any


SPACE_RE = re.compile(r"\s+")
COMMAND_RE = re.compile(r"\b(?:oc|kubectl|openshift-install|etcdctl)\s+[^\n`]+", re.IGNORECASE)


def build_chunk_question_candidates(chunk: dict[str, Any]) -> dict[str, list[str]]:
    title = _clean_title(str(chunk.get("section") or chunk.get("heading_title") or chunk.get("chapter") or ""))
    text = _clean_text(str(chunk.get("text") or chunk.get("markdown") or chunk.get("embedding_text") or ""))
    commands = _commands(chunk, text)
    objects = _objects(chunk, text)
    subject = _subject(title=title, objects=objects, text=text)

    starter: list[str] = []
    followup: list[str] = []
    if commands:
        starter.append(f"{subject} 확인에 먼저 사용할 명령어는 무엇인가요?")
        followup.append(f"{commands[0]} 결과에서 무엇을 보면 좋을까요?")
        followup.append(f"{subject} 명령 결과가 이상하면 다음에는 어디를 확인하면 좋을까요?")
    else:
        starter.append(f"{subject}{_object_particle(subject)} 처음 확인할 때 어디를 보면 좋을까요?")
        followup.append(f"{subject} 다음 단계는 어떻게 이어가면 좋을까요?")
    if _looks_like_troubleshooting(text):
        starter.insert(0, f"{subject} 문제가 생겼을 때 원인을 어디서부터 좁히면 좋을까요?")
        followup.append(f"{subject} 상태가 계속 나쁘면 로그와 이벤트는 어떻게 보면 좋을까요?")
    if _looks_like_authoring(text):
        starter.insert(0, f"{subject}의 기본 구조는 어떻게 잡으면 될까요?")
        followup.append(f"{subject} 적용 후 정상 여부는 어떻게 확인하면 좋을까요?")

    return {
        "starter_question_candidates": _dedupe(starter)[:3],
        "followup_question_candidates": _dedupe(followup)[:4],
    }


def _clean_title(value: str) -> str:
    cleaned = SPACE_RE.sub(" ", value).strip()
    cleaned = re.sub(r"^\d+(?:\.\d+)*\.?\s*", "", cleaned)
    return cleaned


def _clean_text(value: str) -> str:
    return SPACE_RE.sub(" ", value).strip()


def _commands(chunk: dict[str, Any], text: str) -> list[str]:
    values = chunk.get("cli_commands")
    commands = [str(item or "").strip() for item in values if str(item or "").strip()] if isinstance(values, list | tuple) else []
    commands.extend(match.group(0).strip() for match in COMMAND_RE.finditer(text))
    return _dedupe(commands)


def _objects(chunk: dict[str, Any], text: str) -> list[str]:
    values: list[str] = []
    for key in ("k8s_objects", "operator_names"):
        raw = chunk.get(key)
        if isinstance(raw, list | tuple):
            values.extend(str(item or "").strip() for item in raw if str(item or "").strip())
    lowered = text.lower()
    for token, label in (
        ("deployment", "Deployment"),
        ("service", "Service"),
        ("route", "Route"),
        ("endpoint", "Endpoint"),
        ("namespace", "Namespace"),
        ("pod", "Pod"),
        ("secret", "Secret"),
        ("configmap", "ConfigMap"),
        ("pvc", "PVC"),
        ("node", "Node"),
    ):
        if token in lowered:
            values.append(label)
    return _dedupe(values)


def _subject(*, title: str, objects: list[str], text: str) -> str:
    if objects:
        return objects[0]
    if title:
        return title
    lowered = text.lower()
    if "install" in lowered or "설치" in text:
        return "OCP 설치"
    if "troubleshoot" in lowered or "문제" in text:
        return "문제 해결"
    return "이 절차"


def _looks_like_troubleshooting(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in ("error", "fail", "degraded", "pending", "troubleshoot")) or any(
        token in text for token in ("오류", "실패", "문제", "원인", "장애")
    )


def _looks_like_authoring(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in ("apiVersion", "kind:", "yaml", "manifest"))


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = SPACE_RE.sub(" ", str(value or "").strip())
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _has_final_consonant(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    char = stripped[-1]
    code = ord(char)
    if 0xAC00 <= code <= 0xD7A3:
        return (code - 0xAC00) % 28 != 0
    return False


def _object_particle(text: str) -> str:
    return "을" if _has_final_consonant(text) else "를"


__all__ = ["build_chunk_question_candidates"]
