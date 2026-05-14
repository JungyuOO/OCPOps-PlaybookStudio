"""Deterministic cleanup for text-layer PDF extraction artifacts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


_PAGE_COMMENT_RE = re.compile(r"^\s*<!--\s*page:\s*(\d+)\s*-->\s*$", re.IGNORECASE)
_PAGE_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+Page\s+\d+\s*$", re.IGNORECASE)
_PAGE_NUMBER_RE = re.compile(r"^\s*\d{1,4}\s*$")
_SHORT_FRAGMENT_RE = re.compile(r"^[A-Za-z가-힣]{1,8}$")
_YAML_COMMENT_FRAGMENT_RE = re.compile(r"^[A-Za-z가-힣0-9 ()_.-]{1,32}$")
_FOOTER_LABEL_RE = re.compile(r"^[A-Za-z가-힣][A-Za-z가-힣 ._-]{0,31}$")
_STRUCTURAL_LINE_RE = re.compile(r"^\s*(?:#{1,6}\s+|```|~~~|[-*]\s+|\|)")
_YAML_KEY_RE = re.compile(r"^\s{0,12}[A-Za-z_][\w.-]*\s*:")
_CODE_LIKE_YAML_KEY_RE = re.compile(
    r"^\s{0,12}(?:apiVersion|kind|metadata|spec|subjects|roleRef|rules|verbs|resources|namespace|name|"
    r"allowHostDirVolumePlugin|allowHostIPC|allowHostNetwork|allowHostPID|allowHostPorts|"
    r"allowPrivilegeEscalation|allowPrivilegedContainer|priority|readOnlyRootFilesystem|type|"
    r"runAsUser|seLinuxContext|supplementalGroups|serviceAccountName|securityContext|users|groups|volumes):\s*"
)
_PAREN_CONTINUATION_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 ._/-]{1,64}\)$")
_KOREAN_QUESTION_FRAGMENT_RE = re.compile(r"^[가-힣]{1,3}[?][\"']?$")
_KNOWN_STUCK_TOKEN_REPLACEMENTS = (
    (re.compile(r"\bUser\s+IDUID\b"), "User ID(UID)"),
    (re.compile(r"\bRBAC\s+Role-Based\s+Access\s+Control\)"), "RBAC (Role-Based Access Control)"),
    (re.compile(r"\bSCC\s+Security\s+Context\s+Constraints\)"), "SCC (Security Context Constraints)"),
)


@dataclass(frozen=True, slots=True)
class PdfTextRepairBlock:
    repair_kind: str
    start_line: int
    end_line: int
    line_count: int
    preview: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "repair_kind": self.repair_kind,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "line_count": self.line_count,
            "preview": list(self.preview),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class PdfTextRepairResult:
    changed: bool
    repaired_markdown: str
    changed_block_count: int
    diff_summary: tuple[PdfTextRepairBlock, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "changed": self.changed,
            "changed_block_count": self.changed_block_count,
            "diff_summary": [block.to_dict() for block in self.diff_summary],
        }


def repair_pdf_text_artifacts(markdown: str) -> PdfTextRepairResult:
    """Remove common PDF text-layer noise before code/chunk repair.

    The repair is intentionally conservative: it removes converter page markers,
    repeated short page footers such as ``SCC`` + ``2``, and joins tiny fragments
    split across page or hard-wrap boundaries.
    """

    source = str(markdown or "")
    lines = source.splitlines()
    if not lines:
        return PdfTextRepairResult(False, source, 0, ())

    output: list[str] = []
    repairs: list[PdfTextRepairBlock] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if _PAGE_COMMENT_RE.match(line):
            repairs.append(_block("page_marker", index, index + 1, [line], "removed converter page marker"))
            index += 1
            continue

        footer_end = _footer_pair_end(lines, index)
        if footer_end:
            repairs.append(
                _block(
                    "page_footer",
                    index,
                    footer_end,
                    lines[index:footer_end],
                    "removed repeated PDF page footer",
                )
            )
            index = footer_end
            continue

        stripped = line.strip()
        previous_index = _previous_content_index(output)
        join_index = _fragment_join_target(output, previous_index, stripped)
        if join_index >= 0:
            separator = " " if _needs_space_before_fragment(output[join_index], stripped) else ""
            output[join_index] = output[join_index].rstrip() + separator + stripped
            repairs.append(_block("line_fragment", index, index + 1, [line], "joined split PDF text fragment"))
            index += 1
            continue

        output.append(line)
        index += 1

    output, prose_repairs = _repair_prose_spacing(output)
    repairs.extend(prose_repairs)

    repaired = "\n".join(output)
    if source.endswith("\n"):
        repaired += "\n"
    return PdfTextRepairResult(
        changed=bool(repairs),
        repaired_markdown=repaired,
        changed_block_count=len(repairs),
        diff_summary=tuple(repairs),
    )


def _block(
    repair_kind: str,
    start: int,
    end: int,
    preview: list[str],
    reason: str,
) -> PdfTextRepairBlock:
    return PdfTextRepairBlock(
        repair_kind=repair_kind,
        start_line=start + 1,
        end_line=end,
        line_count=max(1, end - start),
        preview=tuple(item.strip() for item in preview if item.strip())[:4],
        reason=reason,
    )


def _footer_pair_end(lines: list[str], index: int) -> int:
    current = lines[index].strip()
    if not _is_footer_label(current):
        return 0
    next_index = _next_nonblank_index(lines, index + 1)
    if next_index < 0 or not _PAGE_NUMBER_RE.match(lines[next_index]):
        return 0
    if re.fullmatch(r"[A-Z][A-Z0-9 ._-]{1,15}", current):
        return next_index + 1
    after_number = _next_nonblank_index(lines, next_index + 1)
    if after_number < 0 or _PAGE_COMMENT_RE.match(lines[after_number]) or _PAGE_HEADING_RE.match(lines[after_number]):
        return next_index + 1
    return 0


def _is_footer_label(text: str) -> bool:
    if not text or len(text) > 32:
        return False
    if _STRUCTURAL_LINE_RE.match(text) or ":" in text:
        return False
    if not _FOOTER_LABEL_RE.match(text):
        return False
    return bool(re.search(r"[A-Za-z가-힣]", text))


def _next_nonblank_index(lines: list[str], start: int) -> int:
    for index in range(start, len(lines)):
        if lines[index].strip():
            return index
    return -1


def _previous_content_index(lines: list[str]) -> int:
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].strip():
            return index
    return -1


def _fragment_join_target(lines: list[str], previous_index: int, fragment: str) -> int:
    if previous_index < 0:
        return -1
    if _should_join_fragment(lines[previous_index], fragment):
        return previous_index
    if _is_fence_line(lines[previous_index]):
        body_index = _previous_content_index(lines[:previous_index])
        if body_index >= 0 and _should_join_fragment(lines[body_index], fragment):
            return body_index
    if _PAGE_HEADING_RE.match(lines[previous_index]):
        body_index = _previous_content_index(lines[:previous_index])
        if body_index >= 0 and _should_join_fragment(lines[body_index], fragment):
            return body_index
    return -1


def _is_fence_line(line: str) -> bool:
    return bool(re.match(r"^\s*(```+|~~~+)\s*$", line.strip()))


def _should_join_fragment(previous: str, fragment: str) -> bool:
    if not fragment:
        return False
    if _PAGE_NUMBER_RE.match(fragment) or _STRUCTURAL_LINE_RE.match(fragment):
        return False
    if re.match(r"^\d+[.)]\s+", fragment):
        return False
    if len(fragment) > 1 and fragment.isupper():
        return False
    prev = previous.rstrip()
    if not prev:
        return False
    if prev.endswith(("-n", "--namespace")):
        return bool(re.fullmatch(r"[A-Za-z0-9_.-]{1,63}", fragment))
    if re.search(r"\bRBAC\s+Role-Based\s+Access$", prev) and fragment.startswith("Control)"):
        return True
    if prev.count("(") > prev.count(")") and _PAREN_CONTINUATION_RE.match(fragment):
        return True
    if re.search(r"[가-힣]$", prev) and _KOREAN_QUESTION_FRAGMENT_RE.match(fragment):
        return True
    if _YAML_KEY_RE.match(prev) and _YAML_COMMENT_FRAGMENT_RE.match(fragment):
        return True
    if prev.endswith((".", ":", ";", ")", "]", "}")):
        return False
    if not _SHORT_FRAGMENT_RE.match(fragment):
        return False
    if re.search(r"[A-Za-z가-힣-]$", prev) and len(fragment) <= 4:
        return True
    if _YAML_KEY_RE.match(prev) and len(fragment) <= 8:
        return True
    return False


def _needs_space_before_fragment(previous: str, fragment: str) -> bool:
    prev = previous.rstrip()
    if prev.endswith(("-n", "--namespace")):
        return True
    if re.search(r"\bRBAC\s+Role-Based\s+Access$", prev) and fragment.startswith("Control)"):
        return True
    if prev.count("(") > prev.count(")") and _PAREN_CONTINUATION_RE.match(fragment):
        return True
    if _KOREAN_QUESTION_FRAGMENT_RE.match(fragment):
        return False
    if prev.endswith("-"):
        return False
    if re.search(r"[가-힣]$", prev):
        first_token = fragment.strip().split(maxsplit=1)[0]
        if re.fullmatch(r"[가-힣]", first_token):
            return False
    if _YAML_KEY_RE.match(prev) and prev.endswith(")"):
        return True
    if fragment.startswith("-"):
        return True
    if _YAML_KEY_RE.match(prev) and " " in fragment.strip():
        return True
    return False


def _repair_prose_spacing(lines: list[str]) -> tuple[list[str], list[PdfTextRepairBlock]]:
    repaired_lines: list[str] = []
    repairs: list[PdfTextRepairBlock] = []
    in_fence = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            repaired_lines.append(line)
            continue
        if in_fence:
            repaired = _normalize_code_comment_line(line)
            repaired_lines.append(repaired)
            if repaired != line:
                repairs.append(
                    _block(
                        "code_comment_spacing",
                        index,
                        index + 1,
                        [line],
                        "normalized PDF spacing inside code comments",
                    )
                )
            continue
        heading_match = re.match(r"^(\s*#{1,6}\s+)(.+?)\s*$", line)
        if heading_match:
            prefix, title = heading_match.groups()
            repaired = prefix + _normalize_prose_line(title).strip()
            repaired_lines.append(repaired)
            if repaired != line:
                repairs.append(
                    _block(
                        "prose_spacing",
                        index,
                        index + 1,
                        [line],
                        "normalized PDF heading spacing and stuck tokens",
                    )
                )
            continue
        if _STRUCTURAL_LINE_RE.match(line) or _CODE_LIKE_YAML_KEY_RE.match(line):
            repaired_lines.append(line)
            continue
        repaired = _normalize_prose_line(line)
        repaired_lines.append(repaired)
        if repaired != line:
            repairs.append(
                _block(
                    "prose_spacing",
                    index,
                    index + 1,
                    [line],
                    "normalized PDF prose spacing and stuck tokens",
                )
            )
    return repaired_lines, repairs


def _normalize_code_comment_line(line: str) -> str:
    comment_index = _code_comment_index(line)
    if comment_index < 0:
        return line
    prefix = line[:comment_index]
    comment = line[comment_index + 1 :]
    if not comment.strip():
        return line
    normalized_comment = _normalize_prose_line(comment).strip()
    return f"{prefix}# {normalized_comment}"


def _code_comment_index(line: str) -> int:
    in_single_quote = False
    in_double_quote = False
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            continue
        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            continue
        if char == "#" and not in_single_quote and not in_double_quote:
            return index
    return -1


def _normalize_prose_line(line: str) -> str:
    if not line.strip():
        return line
    prefix = re.match(r"^\s*", line).group(0)
    body = line.strip()
    for pattern, replacement in _KNOWN_STUCK_TOKEN_REPLACEMENTS:
        body = pattern.sub(replacement, body)
    body = re.sub(r"[ \t]{2,}", " ", body)
    body = re.sub(r"\(\s+", "(", body)
    body = re.sub(r"\s+\)", ")", body)
    body = re.sub(r"\s+([,.;:!?])", r"\1", body)
    return prefix + body


__all__ = [
    "PdfTextRepairBlock",
    "PdfTextRepairResult",
    "repair_pdf_text_artifacts",
]
