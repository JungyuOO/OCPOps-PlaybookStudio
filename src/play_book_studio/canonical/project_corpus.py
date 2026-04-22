"""canonical AST를 retrieval/corpus용 평탄 구조로 투영한다."""

from __future__ import annotations

from dataclasses import dataclass
import re


DOCS_SOURCE_URL_RE = re.compile(
    r"^https://docs\.redhat\.com/"
    r"(?P<lang>ko|en)/documentation/"
    r"(?P<product>[^/]+)/(?P<version>\d+\.\d+)/"
    r"html(?:-single)?/(?P<slug>[^/]+)/index$"
)

from .models import (
    AnchorBlock,
    CanonicalDocumentAst,
    CodeBlock,
    NoteBlock,
    ParagraphBlock,
    PrerequisiteBlock,
    ProcedureBlock,
    TableBlock,
)


@dataclass(slots=True)
class CorpusSectionProjection:
    section_id: str
    book_slug: str
    book_title: str
    heading: str
    section_level: int
    section_path: tuple[str, ...]
    anchor: str
    source_url: str
    viewer_path: str
    semantic_role: str
    block_kinds: tuple[str, ...]
    source_language: str
    display_language: str
    translation_status: str
    translation_stage: str
    translation_source_language: str
    translation_source_url: str
    translation_source_fingerprint: str
    source_id: str
    source_lane: str
    source_type: str
    source_collection: str
    product: str
    version: str
    locale: str
    original_title: str
    legal_notice_url: str
    license_or_terms: str
    review_status: str
    trust_score: float
    verifiability: str
    updated_at: str
    parsed_artifact_id: str
    tenant_id: str
    workspace_id: str
    parent_pack_id: str
    pack_version: str
    bundle_scope: str
    classification: str
    access_groups: tuple[str, ...]
    provider_egress_policy: str
    approval_state: str
    publication_state: str
    redaction_state: str
    citation_eligible: bool
    citation_block_reason: str
    text: str

    def to_dict(self) -> dict[str, object]:
        return {
            "section_id": self.section_id,
            "book_slug": self.book_slug,
            "book_title": self.book_title,
            "heading": self.heading,
            "section_level": self.section_level,
            "section_path": list(self.section_path),
            "anchor": self.anchor,
            "anchor_id": self.anchor,
            "source_url": self.source_url,
            "viewer_path": self.viewer_path,
            "semantic_role": self.semantic_role,
            "block_kinds": list(self.block_kinds),
            "source_language": self.source_language,
            "display_language": self.display_language,
            "translation_status": self.translation_status,
            "translation_stage": self.translation_stage,
            "translation_source_language": self.translation_source_language,
            "translation_source_url": self.translation_source_url,
            "translation_source_fingerprint": self.translation_source_fingerprint,
            "source_id": self.source_id,
            "source_lane": self.source_lane,
            "source_type": self.source_type,
            "source_collection": self.source_collection,
            "product": self.product,
            "version": self.version,
            "locale": self.locale,
            "original_title": self.original_title,
            "legal_notice_url": self.legal_notice_url,
            "license_or_terms": self.license_or_terms,
            "review_status": self.review_status,
            "trust_score": self.trust_score,
            "verifiability": self.verifiability,
            "updated_at": self.updated_at,
            "parsed_artifact_id": self.parsed_artifact_id,
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "parent_pack_id": self.parent_pack_id,
            "pack_version": self.pack_version,
            "bundle_scope": self.bundle_scope,
            "classification": self.classification,
            "access_groups": list(self.access_groups),
            "provider_egress_policy": self.provider_egress_policy,
            "approval_state": self.approval_state,
            "publication_state": self.publication_state,
            "redaction_state": self.redaction_state,
            "citation_eligible": self.citation_eligible,
            "citation_block_reason": self.citation_block_reason,
            "text": self.text,
        }


def _resolved_legal_notice_url(document: CanonicalDocumentAst) -> str:
    explicit = (document.provenance.legal_notice_url or "").strip()
    if explicit:
        return explicit
    match = DOCS_SOURCE_URL_RE.match(document.source_url)
    if not match:
        return ""
    return (
        "https://docs.redhat.com/"
        f"{match.group('lang')}/documentation/{match.group('product')}/{match.group('version')}/"
        "html/legal_notice/index"
    )


def _flatten_block(block) -> str:
    if isinstance(block, ParagraphBlock):
        return block.text.strip()
    if isinstance(block, PrerequisiteBlock):
        if not block.items:
            return ""
        return "사전 요구 사항:\n" + "\n".join(f"- {item}" for item in block.items if item.strip())
    if isinstance(block, ProcedureBlock):
        lines: list[str] = []
        for step in block.steps:
            if not step.text.strip():
                continue
            lines.append(f"{step.ordinal}. {step.text.strip()}")
            for substep in step.substeps:
                if substep.strip():
                    lines.append(f"- {substep.strip()}")
        return "\n".join(lines)
    if isinstance(block, CodeBlock):
        return f"[CODE]\n{block.code.strip()}\n[/CODE]"
    if isinstance(block, NoteBlock):
        label = block.variant.upper()
        title = f" {block.title.strip()}" if block.title.strip() else ""
        return f"[{label}]{title} {block.text.strip()}".strip()
    if isinstance(block, TableBlock):
        rows: list[str] = []
        if block.headers:
            rows.append(" | ".join(header.strip() for header in block.headers))
        rows.extend(" | ".join(cell.strip() for cell in row) for row in block.rows)
        table_text = "\n".join(rows).strip()
        return f"[TABLE]\n{table_text}\n[/TABLE]"
    if isinstance(block, AnchorBlock):
        return ""
    return ""


def project_corpus_sections(document: CanonicalDocumentAst) -> list[CorpusSectionProjection]:
    rows: list[CorpusSectionProjection] = []
    legal_notice_url = _resolved_legal_notice_url(document)
    for section in document.sections:
        parts = [_flatten_block(block) for block in section.blocks]
        text = "\n\n".join(part for part in parts if part.strip()).strip()
        rows.append(
            CorpusSectionProjection(
                section_id=section.section_id,
                book_slug=document.book_slug,
                book_title=document.title,
                heading=section.heading,
                section_level=section.level,
                section_path=section.path,
                anchor=section.anchor,
                source_url=section.source_url,
                viewer_path=section.viewer_path,
                semantic_role=section.semantic_role,
                block_kinds=section.block_kinds,
                source_language=document.source_language,
                display_language=document.display_language,
                translation_status=document.translation_status,
                translation_stage=document.provenance.translation_stage,
                translation_source_language=document.provenance.translation_source_language,
                translation_source_url=document.provenance.translation_source_url,
                translation_source_fingerprint=document.provenance.translation_source_fingerprint,
                source_id=document.provenance.source_id,
                source_lane=document.provenance.source_lane,
                source_type=document.provenance.source_type,
                source_collection=document.provenance.source_collection,
                product=document.provenance.product or document.inferred_product,
                version=document.provenance.version or document.inferred_version,
                locale=document.provenance.locale or document.display_language,
                original_title=document.provenance.original_title or document.title,
                legal_notice_url=legal_notice_url,
                license_or_terms=document.provenance.license_or_terms,
                review_status=document.provenance.review_status,
                trust_score=document.provenance.trust_score,
                verifiability=document.provenance.verifiability,
                updated_at=document.provenance.updated_at,
                parsed_artifact_id=document.provenance.parsed_artifact_id,
                tenant_id=document.provenance.tenant_id,
                workspace_id=document.provenance.workspace_id,
                parent_pack_id=document.provenance.pack_id or document.pack_id,
                pack_version=document.provenance.pack_version or document.inferred_version,
                bundle_scope=document.provenance.bundle_scope,
                classification=document.provenance.classification,
                access_groups=document.provenance.access_groups,
                provider_egress_policy=document.provenance.provider_egress_policy,
                approval_state=document.provenance.approval_state,
                publication_state=document.provenance.publication_state,
                redaction_state=document.provenance.redaction_state,
                citation_eligible=document.provenance.citation_eligible,
                citation_block_reason=document.provenance.citation_block_reason,
                text=text,
            )
        )
    return rows
