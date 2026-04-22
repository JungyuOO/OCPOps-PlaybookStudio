"""canonical AST 품질 검증 규칙."""

from __future__ import annotations

from dataclasses import dataclass

from .models import CanonicalDocumentAst


@dataclass(slots=True)
class CanonicalValidationIssue:
    severity: str
    code: str
    message: str
    section_id: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "section_id": self.section_id,
        }


def validate_document_ast(document: CanonicalDocumentAst) -> list[CanonicalValidationIssue]:
    issues: list[CanonicalValidationIssue] = []

    if not document.doc_id.strip():
        issues.append(CanonicalValidationIssue("error", "missing_doc_id", "문서 id가 비어 있습니다."))
    if not document.title.strip():
        issues.append(CanonicalValidationIssue("error", "missing_title", "문서 제목이 비어 있습니다."))
    if not document.sections:
        issues.append(CanonicalValidationIssue("error", "missing_sections", "문서 section이 없습니다."))
        return issues

    seen_section_ids: set[str] = set()
    seen_anchors: set[str] = set()
    for section in document.sections:
        if not section.section_id.strip():
            issues.append(
                CanonicalValidationIssue(
                    "error",
                    "missing_section_id",
                    "section id가 비어 있습니다.",
                    section_id=section.section_id,
                )
            )
        if section.section_id in seen_section_ids:
            issues.append(
                CanonicalValidationIssue(
                    "error",
                    "duplicate_section_id",
                    f"중복 section id: {section.section_id}",
                    section_id=section.section_id,
                )
            )
        seen_section_ids.add(section.section_id)

        if not section.heading.strip():
            issues.append(
                CanonicalValidationIssue(
                    "error",
                    "missing_heading",
                    "section heading이 비어 있습니다.",
                    section_id=section.section_id,
                )
            )
        if not section.blocks:
            issues.append(
                CanonicalValidationIssue(
                    "warning",
                    "empty_blocks",
                    "section block이 비어 있습니다.",
                    section_id=section.section_id,
                )
            )
        if section.anchor.strip():
            if section.anchor in seen_anchors:
                issues.append(
                    CanonicalValidationIssue(
                        "warning",
                        "duplicate_anchor",
                        f"중복 anchor: {section.anchor}",
                        section_id=section.section_id,
                    )
                )
            seen_anchors.add(section.anchor)

    return issues
