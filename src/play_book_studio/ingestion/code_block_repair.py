"""Deterministic markdown code-block repair helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal


RepairLanguage = Literal["yaml", "bash"]

_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_COMMAND_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\$+\s*)?(?:sudo\s+)?"
    r"(?:(?:oc|kubectl|helm|curl|podman|docker)\b|export\s+[A-Za-z_][A-Za-z0-9_]*=)",
)
_YAML_KEY_RE = re.compile(r"^\s{0,12}[A-Za-z_][\w.-]*\s*:\s*(?:.*)?$")
_YAML_LIST_KEY_RE = re.compile(r"^\s{0,12}-\s+[A-Za-z_][\w.-]*\s*:\s*(?:.*)?$")
_YAML_LIST_SCALAR_RE = re.compile(r"^\s{0,12}-\s+\S.*$")
_YAML_CONTINUATION_RE = re.compile(r"^\s{2,}[-A-Za-z0-9_.'\"{}\[\],:/#()]+\s*(?:.*)?$")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+\S+")
_IMAGE_RE = re.compile(r"^\s*!\[[^\]]*]\([^)]+\)\s*$")
_HTML_COMMENT_RE = re.compile(r"^\s*<!--.*-->\s*$")

_YAML_STRONG_KEYS = {
    "apiVersion",
    "kind",
    "metadata",
    "spec",
    "status",
    "data",
    "rules",
    "subjects",
    "roleRef",
    "containers",
    "image",
    "name",
    "namespace",
    "labels",
    "selector",
    "template",
    "ports",
    "resources",
    "verbs",
    "allowHostDirVolumePlugin",
    "allowHostIPC",
    "allowHostNetwork",
    "allowHostPID",
    "allowHostPorts",
    "allowPrivilegeEscalation",
    "allowPrivilegedContainer",
    "priority",
    "readOnlyRootFilesystem",
    "runAsUser",
    "seLinuxContext",
    "supplementalGroups",
    "serviceAccountName",
    "securityContext",
    "users",
    "groups",
    "volumes",
    "type",
}
_YAML_LIST_PARENT_KEYS = {
    "apiGroups",
    "resources",
    "verbs",
    "resourceNames",
    "names",
    "groups",
    "users",
    "subjects",
    "containers",
    "env",
    "ports",
    "volumes",
}


@dataclass(frozen=True, slots=True)
class CodeBlockRepairBlock:
    language: RepairLanguage
    start_line: int
    end_line: int
    line_count: int
    preview: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "language": self.language,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "line_count": self.line_count,
            "preview": list(self.preview),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class CodeBlockRepairResult:
    changed: bool
    repaired_markdown: str
    changed_block_count: int
    diff_summary: tuple[CodeBlockRepairBlock, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "changed": self.changed,
            "changed_block_count": self.changed_block_count,
            "diff_summary": [block.to_dict() for block in self.diff_summary],
        }


def repair_unfenced_code_blocks(markdown: str) -> CodeBlockRepairResult:
    """Wrap unfenced YAML and shell commands without rewriting source text."""

    source = str(markdown or "")
    lines = source.splitlines()
    if not lines:
        return CodeBlockRepairResult(False, source, 0, ())

    output: list[str] = []
    repairs: list[CodeBlockRepairBlock] = []
    index = 0
    fence_marker: tuple[str, int] | None = None
    while index < len(lines):
        line = lines[index]
        marker = _fence_marker(line)
        if fence_marker is not None:
            output.append(line)
            if marker and marker[0] == fence_marker[0] and marker[1] >= fence_marker[1]:
                fence_marker = None
            index += 1
            continue
        if marker:
            fence_marker = marker
            output.append(line)
            index += 1
            continue

        bash_group = _collect_bash_group(lines, index)
        if bash_group:
            end = bash_group
            repairs.append(_repair_block("bash", lines, index, end, "shell command sequence"))
            output.extend(_fenced("bash", lines[index:end]))
            index = end
            continue

        yaml_group = _collect_yaml_group(lines, index)
        if yaml_group:
            end = yaml_group
            repairs.append(_repair_block("yaml", lines, index, end, "kubernetes/yaml mapping sequence"))
            output.extend(_fenced("yaml", lines[index:end]))
            index = end
            continue

        output.append(line)
        index += 1

    output, absorbed_repairs = _absorb_orphan_bash_continuations(output)
    repairs.extend(absorbed_repairs)
    repaired = "\n".join(output)
    if source.endswith("\n"):
        repaired += "\n"
    return CodeBlockRepairResult(
        changed=bool(repairs),
        repaired_markdown=repaired,
        changed_block_count=len(repairs),
        diff_summary=tuple(repairs),
    )


def _collect_bash_group(lines: list[str], start: int) -> int:
    if not _is_command_line(lines[start]):
        return 0
    end = start + 1
    while end < len(lines):
        current = lines[end]
        if not current.strip():
            break
        if _fence_marker(current) or _looks_like_non_code(current):
            break
        if _is_command_line(current) or _is_command_continuation(current, previous_line=lines[end - 1]):
            end += 1
            continue
        break
    return end


def _collect_yaml_group(lines: list[str], start: int) -> int:
    if not _is_yaml_candidate_line(lines[start]):
        return 0
    end = start + 1
    while end < len(lines):
        current = lines[end]
        if not current.strip():
            break
        if _fence_marker(current):
            break
        if _is_yaml_candidate_line(current) or _is_yaml_continuation_line(current, previous_line=lines[end - 1]):
            end += 1
            continue
        break
    group = lines[start:end]
    return end if _yaml_group_has_enough_signal(group) else 0


def _is_command_line(line: str) -> bool:
    return bool(_COMMAND_RE.match(line.strip()))


def _is_command_continuation(line: str, *, previous_line: str = "") -> bool:
    stripped = line.strip()
    if stripped.startswith(("-", "--", "|")) or stripped.endswith("\\"):
        return True
    return _is_orphan_bash_continuation(line, previous_line)


def _is_orphan_bash_continuation(line: str, previous_line: str) -> bool:
    stripped = line.strip()
    previous = previous_line.strip()
    if not stripped or not previous or _looks_like_non_code(line):
        return False
    if any("\uac00" <= char <= "\ud7a3" for char in stripped):
        return False
    if stripped.endswith(":") or re.match(r"^[A-Z][A-Za-z ]+:", stripped):
        return False
    if re.match(r"^-[A-Za-z]\s+\S+", stripped):
        return True
    if not re.match(r"^[A-Za-z0-9./:_-]+(?:\s+--?[A-Za-z0-9_-]+(?:[=\s].*)?)*$", stripped):
        return False
    if previous.endswith(("-n", "--namespace")):
        return True
    if re.search(r"(?:\s-n|--namespace)\s+[A-Za-z0-9_-]{3,}$", previous) and re.fullmatch(
        r"[A-Za-z]{1,8}",
        stripped,
    ):
        return True
    if not ("/" in stripped or "--" in stripped or stripped.startswith(("-", "--")) or previous.endswith("\\")):
        return False
    return (
        previous.endswith("\\")
        or "--from=" in previous
        or "://" in previous
        or previous.count("'") % 2 == 1
        or previous.count('"') % 2 == 1
    )


def _joined_orphan_bash_continuation(previous_line: str, continuation_line: str) -> str | None:
    previous = previous_line.rstrip()
    stripped = continuation_line.strip()
    if previous.endswith(("-n", "--namespace")):
        return f"{previous} {stripped}"
    if re.search(r"(?:\s-n|--namespace)\s+[A-Za-z0-9_-]{3,}$", previous) and re.fullmatch(
        r"[A-Za-z]{1,8}",
        stripped,
    ):
        return f"{previous}{stripped}"
    if re.match(r"^-[A-Za-z]\s+\S+", stripped):
        return f"{previous} {stripped}"
    return None


def _is_yaml_candidate_line(line: str) -> bool:
    stripped = line.strip()
    if _looks_like_non_code(line) or not stripped:
        return False
    if ":" not in stripped:
        return False
    key = _yaml_key(line)
    if key in _YAML_STRONG_KEYS:
        return True
    if _YAML_KEY_RE.match(line) or _YAML_LIST_KEY_RE.match(line):
        return True
    return False


def _is_yaml_continuation_line(line: str, *, previous_line: str = "") -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if _YAML_LIST_SCALAR_RE.match(line):
        parent_key = _yaml_key(previous_line)
        if line.startswith((" ", "\t")) or parent_key in _YAML_LIST_PARENT_KEYS or _YAML_LIST_SCALAR_RE.match(previous_line):
            return True
    if _looks_like_non_code(line):
        return False
    if _YAML_LIST_KEY_RE.match(line):
        return True
    if _YAML_CONTINUATION_RE.match(line):
        return True
    return False


def _yaml_group_has_enough_signal(lines: list[str]) -> bool:
    nonblank = [line for line in lines if line.strip()]
    if len(nonblank) < 3:
        return False
    keys = [_yaml_key(line) for line in nonblank]
    strong_count = len([key for key in keys if key in _YAML_STRONG_KEYS])
    key_set = {key for key in keys if key}
    if "kind" in key_set and ({"metadata", "spec"} & key_set):
        return True
    if strong_count >= 2:
        return True
    return False


def _yaml_key(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("-"):
        stripped = stripped[1:].strip()
    match = re.match(r"([A-Za-z_][\w.-]*)\s*:", stripped)
    return match.group(1) if match else ""


def _looks_like_non_code(line: str) -> bool:
    stripped = line.strip()
    if _HEADING_RE.match(line) or _IMAGE_RE.match(line) or _HTML_COMMENT_RE.match(line):
        return True
    if stripped.startswith("|") or _TABLE_SEPARATOR_RE.match(line):
        return True
    if re.match(r"^\s*[-*]\s+\S", line) and not _COMMAND_RE.match(line) and not _YAML_LIST_KEY_RE.match(line):
        return True
    return False


def _fenced(language: RepairLanguage, group: list[str]) -> list[str]:
    if language == "bash":
        group = _normalize_bash_group(group)
    return [f"```{language}", *group, "```"]


def _normalize_bash_group(group: list[str]) -> list[str]:
    output: list[str] = []
    for line in group:
        if output and _is_orphan_bash_continuation(line, output[-1]):
            joined = _joined_orphan_bash_continuation(output[-1], line)
            if joined is not None:
                output[-1] = joined
                continue
        output.append(line)
    return output


def _fence_marker(line: str) -> tuple[str, int] | None:
    match = _FENCE_RE.match(line)
    if not match:
        return None
    marker = match.group(1)
    return marker[0], len(marker)


def _repair_block(
    language: RepairLanguage,
    lines: list[str],
    start: int,
    end: int,
    reason: str,
) -> CodeBlockRepairBlock:
    group = [line.strip() for line in lines[start:end] if line.strip()]
    return CodeBlockRepairBlock(
        language=language,
        start_line=start + 1,
        end_line=end,
        line_count=end - start,
        preview=tuple(group[:4]),
        reason=reason,
    )


def _absorb_orphan_bash_continuations(
    lines: list[str],
) -> tuple[list[str], list[CodeBlockRepairBlock]]:
    output: list[str] = []
    repairs: list[CodeBlockRepairBlock] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip().lower().startswith("```bash"):
            output.append(line)
            index += 1
            continue
        fence_start = index
        body: list[str] = []
        index += 1
        while index < len(lines) and not _fence_marker(lines[index]):
            body.append(lines[index])
            index += 1
        if index >= len(lines):
            output.append(line)
            output.extend(body)
            break
        closing = lines[index]
        index += 1
        absorbed: list[str] = []
        absorbed_preview: list[str] = []
        pending_blank: list[str] = []
        while index < len(lines):
            current = lines[index]
            if not current.strip():
                pending_blank.append(current)
                index += 1
                continue
            previous = absorbed[-1] if absorbed else body[-1] if body else ""
            if not _is_orphan_bash_continuation(current, previous):
                break
            pending_blank.clear()
            absorbed_preview.append(current)
            joined = _joined_orphan_bash_continuation(previous, current)
            if joined is not None and absorbed:
                absorbed[-1] = joined
            elif joined is not None and body:
                body[-1] = joined
            else:
                absorbed.append(current)
            index += 1
        output.append(line)
        output.extend(body)
        output.extend(absorbed)
        output.append(closing)
        output.extend(pending_blank)
        if absorbed_preview:
            repairs.append(
                CodeBlockRepairBlock(
                    language="bash",
                    start_line=fence_start + 1,
                    end_line=fence_start + len(body) + len(absorbed) + 2,
                    line_count=len(absorbed_preview),
                    preview=tuple(item.strip() for item in absorbed_preview[:4]),
                    reason="absorbed split shell command continuation",
                )
            )
    return output, repairs


__all__ = [
    "CodeBlockRepairBlock",
    "CodeBlockRepairResult",
    "repair_unfenced_code_blocks",
]
