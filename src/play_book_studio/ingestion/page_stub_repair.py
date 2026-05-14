"""Deterministic repair for PDF page-marker stub chunks."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


_PAGE_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+Page\s+(\d+)\s*$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class PageStubRepairBlock:
    page_number: int
    start_line: int
    end_line: int
    line_count: int
    preview: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "page_number": self.page_number,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "line_count": self.line_count,
            "preview": list(self.preview),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class PageStubRepairResult:
    changed: bool
    repaired_markdown: str
    changed_block_count: int
    diff_summary: tuple[PageStubRepairBlock, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "changed": self.changed,
            "changed_block_count": self.changed_block_count,
            "diff_summary": [block.to_dict() for block in self.diff_summary],
        }


def repair_page_stub_headings(markdown: str) -> PageStubRepairResult:
    """Remove converter-only ``Page N`` headings while preserving page comments/content."""

    source = str(markdown or "")
    lines = source.splitlines()
    if not lines:
        return PageStubRepairResult(False, source, 0, ())

    output: list[str] = []
    repairs: list[PageStubRepairBlock] = []
    for index, line in enumerate(lines, start=1):
        match = _PAGE_HEADING_RE.match(line)
        if not match:
            output.append(line)
            continue
        page_number = int(match.group(1))
        repairs.append(
            PageStubRepairBlock(
                page_number=page_number,
                start_line=index,
                end_line=index,
                line_count=1,
                preview=(line.strip(),),
                reason="converter page marker promoted to chunk heading",
            )
        )

    repaired = "\n".join(output)
    if source.endswith("\n"):
        repaired += "\n"
    return PageStubRepairResult(
        changed=bool(repairs),
        repaired_markdown=repaired,
        changed_block_count=len(repairs),
        diff_summary=tuple(repairs),
    )


__all__ = [
    "PageStubRepairBlock",
    "PageStubRepairResult",
    "repair_page_stub_headings",
]
