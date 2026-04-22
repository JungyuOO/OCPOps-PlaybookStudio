from __future__ import annotations

from dataclasses import dataclass
import re


INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
COMMAND_HEAD_RE = re.compile(
    r"^(?:\$+\s*)?"
    r"(?:"
    r"oc|kubectl|podman|docker|curl|jq|yq|grep|awk|sed|tar|cp|mv|rm|cat|chmod|chown|"
    r"openssl|htpasswd|systemctl|journalctl|ssh|scp|helm|crictl|buildah|skopeo|chroot"
    r")\b",
    re.IGNORECASE,
)
SCRIPT_COMMAND_RE = re.compile(r"^(?:\$+\s*)?(?:\.?/)?[A-Za-z0-9._-]+\.sh(?:\s+.*)?$", re.IGNORECASE)
COMMAND_CONNECTOR_RE = re.compile(r"\s+(?:또는|및|and|or)\s+(?=(?:다음\s+)?명령)", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")
SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?])")
SPACE_AFTER_OPEN_PAREN_RE = re.compile(r"([(\[{])\s+")
SPACE_BEFORE_CLOSE_PAREN_RE = re.compile(r"\s+([)\]}])")

FOLLOWING_PARTICLE_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("으로", "다음 명령으로"),
    ("로", "다음 명령으로"),
    ("에서", "다음 명령에서"),
    ("에", "다음 명령에"),
    ("을", "다음 명령을"),
    ("를", "다음 명령을"),
    ("과", "다음 명령과"),
    ("와", "다음 명령과"),
    ("도", "다음 명령도"),
)


@dataclass(frozen=True, slots=True)
class InlineCommandSplit:
    narrative_text: str
    commands: tuple[str, ...]
    caption_text: str


def _normalize_text(text: str) -> str:
    cleaned = WHITESPACE_RE.sub(" ", (text or "").strip())
    cleaned = SPACE_BEFORE_PUNCT_RE.sub(r"\1", cleaned)
    cleaned = SPACE_AFTER_OPEN_PAREN_RE.sub(r"\1", cleaned)
    cleaned = SPACE_BEFORE_CLOSE_PAREN_RE.sub(r"\1", cleaned)
    cleaned = COMMAND_CONNECTOR_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\b다음\s+다음\s+명령", "다음 명령", cleaned)
    return cleaned.strip()


def _looks_like_command(snippet: str) -> bool:
    candidate = (snippet or "").strip()
    if not candidate:
        return False
    if COMMAND_HEAD_RE.match(candidate):
        return True
    if SCRIPT_COMMAND_RE.match(candidate):
        return True
    if " " in candidate and any(symbol in candidate for symbol in ("|", ">", "<")):
        return True
    return False


def _replacement_for_context(text: str, start: int, end: int, *, has_prior_text: bool) -> tuple[str, int]:
    following = text[end:]
    leading_ws = len(following) - len(following.lstrip())
    trimmed = following.lstrip()
    if trimmed.startswith("명령"):
        return "아래 ", leading_ws
    for particle, replacement in FOLLOWING_PARTICLE_REPLACEMENTS:
        if trimmed.startswith(particle):
            return replacement, leading_ws + len(particle)
    if not has_prior_text:
        return "다음 명령", leading_ws
    return "", 0


def _caption_from_text(text: str) -> str:
    replaced = INLINE_CODE_RE.sub(
        lambda match: "명령" if _looks_like_command(match.group(1)) else match.group(0),
        text,
    )
    caption = _normalize_text(replaced)
    if caption in {"명령", "다음 명령", "이 명령"}:
        return ""
    return caption


def split_inline_commands(text: str) -> InlineCommandSplit | None:
    raw_text = (text or "").strip()
    if not raw_text or "`" not in raw_text:
        return None

    commands: list[str] = []
    narrative_parts: list[str] = []
    cursor = 0
    for match in INLINE_CODE_RE.finditer(raw_text):
        snippet = match.group(1).strip()
        if not _looks_like_command(snippet):
            continue
        narrative_parts.append(raw_text[cursor:match.start()])
        replacement, consume = _replacement_for_context(
            raw_text,
            match.start(),
            match.end(),
            has_prior_text=bool("".join(narrative_parts).strip()),
        )
        if replacement:
            narrative_parts.append(replacement)
        commands.append(snippet)
        cursor = match.end() + consume

    if not commands:
        return None

    narrative_parts.append(raw_text[cursor:])
    narrative_text = _normalize_text("".join(narrative_parts))
    caption_text = _caption_from_text(raw_text)
    return InlineCommandSplit(
        narrative_text=narrative_text,
        commands=tuple(commands),
        caption_text=caption_text,
    )
