"""코퍼스/플레이북 공통 원천 구조인 canonical AST 모델 모음."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


SemanticRole = Literal["overview", "procedure", "reference", "concept", "appendix", "unknown"]
SourceType = Literal["web", "pdf", "upload", "repo"]
TranslationStatus = Literal["original", "translated_ko_draft", "approved_ko"]
NoteVariant = Literal["note", "warning", "caution", "important", "tip"]


@dataclass(slots=True)
class AstProvenance:
    source_id: str = ""
    source_lane: str = ""
    source_type: str = ""
    source_collection: str = ""
    product: str = ""
    version: str = ""
    locale: str = ""
    original_title: str = ""
    legal_notice_url: str = ""
    license_or_terms: str = ""
    review_status: str = "unreviewed"
    trust_score: float = 1.0
    verifiability: str = ""
    updated_at: str = ""
    capture_uri: str = ""
    source_fingerprint: str = ""
    raw_content_sha256: str = ""
    parser_name: str = ""
    parser_version: str = ""
    source_state: str = ""
    content_status: str = ""
    translation_stage: str = ""
    translation_source_language: str = ""
    translation_target_language: str = ""
    translation_source_url: str = ""
    translation_source_fingerprint: str = ""
    parsed_artifact_id: str = ""
    tenant_id: str = "public"
    workspace_id: str = "core"
    pack_id: str = ""
    pack_version: str = ""
    bundle_scope: str = "official"
    classification: str = "public"
    access_groups: tuple[str, ...] = field(default_factory=lambda: ("public",))
    provider_egress_policy: str = "unspecified"
    approval_state: str = ""
    publication_state: str = ""
    redaction_state: str = "not_required"
    citation_eligible: bool = False
    citation_block_reason: str = ""
    primary_input_kind: str = ""
    source_repo: str = ""
    source_branch: str = ""
    source_binding_kind: str = ""
    source_relative_path: str = ""
    source_relative_paths: tuple[str, ...] = field(default_factory=tuple)
    source_mirror_root: str = ""
    fallback_input_kind: str = ""
    fallback_source_url: str = ""
    fallback_viewer_path: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
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
            "capture_uri": self.capture_uri,
            "source_fingerprint": self.source_fingerprint,
            "raw_content_sha256": self.raw_content_sha256,
            "parser_name": self.parser_name,
            "parser_version": self.parser_version,
            "source_state": self.source_state,
            "content_status": self.content_status,
            "translation_stage": self.translation_stage,
            "translation_source_language": self.translation_source_language,
            "translation_target_language": self.translation_target_language,
            "translation_source_url": self.translation_source_url,
            "translation_source_fingerprint": self.translation_source_fingerprint,
            "parsed_artifact_id": self.parsed_artifact_id,
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "pack_id": self.pack_id,
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
            "primary_input_kind": self.primary_input_kind,
            "source_repo": self.source_repo,
            "source_branch": self.source_branch,
            "source_binding_kind": self.source_binding_kind,
            "source_relative_path": self.source_relative_path,
            "source_relative_paths": list(self.source_relative_paths),
            "source_mirror_root": self.source_mirror_root,
            "fallback_input_kind": self.fallback_input_kind,
            "fallback_source_url": self.fallback_source_url,
            "fallback_viewer_path": self.fallback_viewer_path,
            "notes": list(self.notes),
        }


@dataclass(slots=True)
class ProcedureStep:
    ordinal: int
    text: str
    substeps: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "text": self.text,
            "substeps": list(self.substeps),
        }


@dataclass(slots=True)
class ParagraphBlock:
    text: str
    kind: str = "paragraph"

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "text": self.text}


@dataclass(slots=True)
class PrerequisiteBlock:
    items: tuple[str, ...]
    kind: str = "prerequisite"

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "items": list(self.items)}


@dataclass(slots=True)
class ProcedureBlock:
    steps: tuple[ProcedureStep, ...]
    kind: str = "procedure"

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "steps": [step.to_dict() for step in self.steps]}


@dataclass(slots=True)
class CodeBlock:
    code: str
    language: str = "shell"
    copy_text: str = ""
    wrap_hint: bool = True
    overflow_hint: str = "toggle"
    caption: str = ""
    kind: str = "code"

    def __post_init__(self) -> None:
        if not self.copy_text:
            self.copy_text = self.code

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "language": self.language,
            "code": self.code,
            "copy_text": self.copy_text,
            "wrap_hint": self.wrap_hint,
            "overflow_hint": self.overflow_hint,
            "caption": self.caption,
        }


@dataclass(slots=True)
class NoteBlock:
    text: str
    variant: NoteVariant = "note"
    title: str = ""
    kind: str = "note"

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "variant": self.variant,
            "title": self.title,
            "text": self.text,
        }


@dataclass(slots=True)
class TableBlock:
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    caption: str = ""
    kind: str = "table"

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "headers": list(self.headers),
            "rows": [list(row) for row in self.rows],
            "caption": self.caption,
        }


@dataclass(slots=True)
class AnchorBlock:
    anchor: str
    label: str = ""
    kind: str = "anchor"

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "anchor": self.anchor,
            "label": self.label,
        }


AstBlock = (
    ParagraphBlock
    | PrerequisiteBlock
    | ProcedureBlock
    | CodeBlock
    | NoteBlock
    | TableBlock
    | AnchorBlock
)


def serialize_block(block: AstBlock) -> dict[str, object]:
    return block.to_dict()


@dataclass(slots=True)
class CanonicalSectionAst:
    section_id: str
    ordinal: int
    heading: str
    level: int
    path: tuple[str, ...]
    anchor: str
    source_url: str
    viewer_path: str
    semantic_role: SemanticRole = "unknown"
    blocks: tuple[AstBlock, ...] = field(default_factory=tuple)

    @property
    def block_kinds(self) -> tuple[str, ...]:
        return tuple(getattr(block, "kind", "unknown") for block in self.blocks)

    def to_dict(self) -> dict[str, object]:
        return {
            "section_id": self.section_id,
            "ordinal": self.ordinal,
            "heading": self.heading,
            "level": self.level,
            "path": list(self.path),
            "anchor": self.anchor,
            "source_url": self.source_url,
            "viewer_path": self.viewer_path,
            "semantic_role": self.semantic_role,
            "block_kinds": list(self.block_kinds),
            "blocks": [serialize_block(block) for block in self.blocks],
        }


@dataclass(slots=True)
class CanonicalDocumentAst:
    doc_id: str
    book_slug: str
    title: str
    source_type: SourceType
    source_url: str
    viewer_base_path: str
    source_language: str
    display_language: str
    translation_status: TranslationStatus
    pack_id: str
    pack_label: str
    inferred_product: str
    inferred_version: str
    sections: tuple[CanonicalSectionAst, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)
    provenance: AstProvenance = field(default_factory=AstProvenance)

    def to_dict(self) -> dict[str, object]:
        return {
            "doc_id": self.doc_id,
            "book_slug": self.book_slug,
            "title": self.title,
            "source_type": self.source_type,
            "source_url": self.source_url,
            "viewer_base_path": self.viewer_base_path,
            "source_language": self.source_language,
            "display_language": self.display_language,
            "translation_status": self.translation_status,
            "pack_id": self.pack_id,
            "pack_label": self.pack_label,
            "inferred_product": self.inferred_product,
            "inferred_version": self.inferred_version,
            "sections": [section.to_dict() for section in self.sections],
            "notes": list(self.notes),
            "provenance": self.provenance.to_dict(),
        }


@dataclass(slots=True)
class PlaybookSectionArtifact:
    section_id: str
    ordinal: int
    heading: str
    level: int
    path: tuple[str, ...]
    anchor: str
    viewer_path: str
    semantic_role: SemanticRole
    blocks: tuple[AstBlock, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "section_id": self.section_id,
            "section_key": self.section_id,
            "ordinal": self.ordinal,
            "heading": self.heading,
            "level": self.level,
            "path": list(self.path),
            "section_path": list(self.path),
            "section_path_label": " > ".join(self.path) if self.path else self.heading,
            "anchor": self.anchor,
            "anchor_id": self.anchor,
            "viewer_path": self.viewer_path,
            "semantic_role": self.semantic_role,
            "block_kinds": list(getattr(block, "kind", "unknown") for block in self.blocks),
            "blocks": [serialize_block(block) for block in self.blocks],
        }


@dataclass(slots=True)
class PlaybookDocumentArtifact:
    book_slug: str
    title: str
    source_uri: str
    source_language: str
    language_hint: str
    translation_status: str
    translation_stage: str
    translation_source_uri: str
    translation_source_language: str
    translation_source_fingerprint: str
    pack_id: str
    inferred_version: str
    legal_notice_url: str = ""
    review_status: str = "unreviewed"
    sections: tuple[PlaybookSectionArtifact, ...] = field(default_factory=tuple)
    quality_status: str = "draft"
    quality_score: float = 0.0
    quality_flags: tuple[str, ...] = field(default_factory=tuple)
    source_metadata: dict[str, object] = field(default_factory=dict)
    anchor_map: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "canonical_model": "playbook_document_v1",
            "source_view_strategy": "playbook_ast_v1",
            "book_slug": self.book_slug,
            "title": self.title,
            "version": self.inferred_version,
            "locale": self.language_hint,
            "source_uri": self.source_uri,
            "source_language": self.source_language,
            "language_hint": self.language_hint,
            "translation_status": self.translation_status,
            "translation_stage": self.translation_stage,
            "translation_source_uri": self.translation_source_uri,
            "translation_source_language": self.translation_source_language,
            "translation_source_fingerprint": self.translation_source_fingerprint,
            "legal_notice_url": self.legal_notice_url,
            "review_status": self.review_status,
            "pack_id": self.pack_id,
            "inferred_version": self.inferred_version,
            "section_count": len(self.sections),
            "source_metadata": dict(self.source_metadata),
            "anchor_map": dict(self.anchor_map),
            "sections": [section.to_dict() for section in self.sections],
            "quality_status": self.quality_status,
            "quality_score": self.quality_score,
            "quality_flags": list(self.quality_flags),
        }
