"""Guard helpers for command grounding in generated answers.

Answer prose is produced by the LLM. This module only checks whether command
content in that prose is supported by the retrieved citations.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any


FENCED_CODE_BLOCK_RE = re.compile(r"```[a-zA-Z0-9_-]*\n.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`([^`]+)`")
SHELL_HEAD_RE = re.compile(
    r"^\s*(?:oc|kubectl|podman|docker|helm|kustomize|openssl|curl|chroot|crictl|ETCDCTL_API=|\./|/usr/)",
    re.IGNORECASE,
)
QUERY_COMMAND_RE = re.compile(
    r"(?:\b(?:oc|kubectl|describe|get|logs|adm|apply|delete|scale|rollout|command)\b|명령|확인|조회|봐)",
    re.IGNORECASE,
)


def _citation_value(citation: Any, key: str, default: Any = None) -> Any:
    if isinstance(citation, dict):
        return citation.get(key, default)
    return getattr(citation, key, default)


def _as_strings(values: Any) -> Iterable[str]:
    if values is None:
        return ()
    if isinstance(values, str):
        return (values,)
    try:
        return tuple(str(value or "") for value in values)
    except TypeError:
        return (str(values or ""),)


def _normalize_command(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _citation_text(citation: Any) -> str:
    parts = [
        str(_citation_value(citation, "excerpt", "") or ""),
        str(_citation_value(citation, "section", "") or ""),
        str(_citation_value(citation, "section_path_label", "") or ""),
    ]
    parts.extend(_as_strings(_citation_value(citation, "cli_commands", ())))
    ordered = _citation_value(citation, "ordered_cli_commands", ()) or ()
    for item in ordered:
        if isinstance(item, dict):
            parts.append(str(item.get("command") or item.get("text") or ""))
        else:
            parts.append(str(item or ""))
    return "\n".join(part for part in parts if part)


def _citation_commands(citation: Any) -> set[str]:
    commands: set[str] = set()
    for value in _as_strings(_citation_value(citation, "cli_commands", ())):
        normalized = _normalize_command(value)
        if normalized:
            commands.add(normalized)
    ordered = _citation_value(citation, "ordered_cli_commands", ()) or ()
    for item in ordered:
        value = item.get("command") if isinstance(item, dict) else item
        normalized = _normalize_command(str(value or ""))
        if normalized:
            commands.add(normalized)
    return commands


def _all_citation_text(citations: Iterable[Any]) -> str:
    return "\n".join(_citation_text(citation) for citation in citations)


def _all_citation_commands(citations: Iterable[Any]) -> set[str]:
    commands: set[str] = set()
    for citation in citations:
        commands.update(_citation_commands(citation))
    return commands


def _code_block_content(block: str) -> str:
    content = re.sub(r"^```[^\n`]*\n?", "", block.strip())
    return re.sub(r"\n?```$", "", content).strip()


def _candidate_commands(text: str) -> list[str]:
    candidates: list[str] = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if line.startswith("$ "):
            line = line[2:].strip()
        if SHELL_HEAD_RE.search(line):
            candidates.append(line)
    if not candidates:
        for match in INLINE_CODE_RE.finditer(text or ""):
            value = match.group(1).strip()
            if SHELL_HEAD_RE.search(value):
                candidates.append(value)
    return candidates


def has_sufficient_command_grounding(*, query: str, citations) -> bool:
    """Return whether a command-oriented query has command evidence."""
    if not QUERY_COMMAND_RE.search(query or ""):
        return bool(citations)
    return bool(_all_citation_commands(citations))


def strip_ungrounded_code_blocks(answer_text: str, *, citations) -> str:
    """Remove fenced code blocks that are not visible in cited evidence."""
    if "```" not in (answer_text or ""):
        return answer_text

    citation_text = _normalize_command(_all_citation_text(citations))
    grounded_commands = _all_citation_commands(citations)

    def is_grounded(block: str) -> bool:
        content = _code_block_content(block)
        if not content:
            return True
        normalized_content = _normalize_command(content)
        if normalized_content and normalized_content in citation_text:
            return True
        commands = _candidate_commands(content)
        if not commands:
            return False
        for command in commands:
            normalized_command = _normalize_command(command)
            if normalized_command in grounded_commands or normalized_command in citation_text:
                continue
            return False
        return True

    removed = False

    def replace(match: re.Match[str]) -> str:
        nonlocal removed
        if is_grounded(match.group(0)):
            return match.group(0)
        removed = True
        return "\n\n"

    cleaned = FENCED_CODE_BLOCK_RE.sub(replace, answer_text or "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if removed and not grounded_commands:
        notice = "제공된 근거에는 실행 명령이나 예시 코드가 명시되어 있지 않습니다."
        if notice not in cleaned:
            cleaned = f"{cleaned}\n\n{notice}".strip()
    return cleaned


__all__ = [
    "has_sufficient_command_grounding",
    "strip_ungrounded_code_blocks",
]
