"""canonical AST를 사람이 읽는 플레이북 문서 구조로 투영한다."""

from __future__ import annotations

import json
from pathlib import Path
import re

from .models import CanonicalDocumentAst, PlaybookDocumentArtifact, PlaybookSectionArtifact


DOCS_SOURCE_URL_RE = re.compile(
    r"^https://docs\.redhat\.com/"
    r"(?P<lang>ko|en)/documentation/"
    r"(?P<product>[^/]+)/(?P<version>\d+\.\d+)/"
    r"html(?:-single)?/(?P<slug>[^/]+)/index$"
)


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


def project_playbook_document(document: CanonicalDocumentAst) -> PlaybookDocumentArtifact:
    sections = tuple(
        PlaybookSectionArtifact(
            section_id=section.section_id,
            ordinal=section.ordinal,
            heading=section.heading,
            level=section.level,
            path=section.path,
            anchor=section.anchor,
            viewer_path=section.viewer_path,
            semantic_role=section.semantic_role,
            blocks=section.blocks,
        )
        for section in document.sections
    )
    quality_status = {
        "approved_ko": "ready",
        "translated_ko_draft": "review_required",
        "original": "translation_required",
    }.get(document.translation_status, "draft")
    quality_flags = list(document.notes)
    if document.translation_status != "approved_ko":
        quality_flags.append(document.translation_status)
    anchor_map = {
        section.anchor: section.viewer_path
        for section in document.sections
        if section.anchor.strip()
    }
    legal_notice_url = _resolved_legal_notice_url(document)
    source_metadata = {
        "source_id": document.provenance.source_id,
        "source_type": document.provenance.source_type or document.source_type,
        "source_lane": document.provenance.source_lane,
        "source_collection": document.provenance.source_collection,
        "primary_input_kind": document.provenance.primary_input_kind,
        "source_repo": document.provenance.source_repo,
        "source_branch": document.provenance.source_branch,
        "source_binding_kind": document.provenance.source_binding_kind,
        "source_relative_path": document.provenance.source_relative_path,
        "source_relative_paths": list(document.provenance.source_relative_paths),
        "source_mirror_root": document.provenance.source_mirror_root,
        "fallback_input_kind": document.provenance.fallback_input_kind,
        "fallback_source_url": document.provenance.fallback_source_url,
        "fallback_viewer_path": document.provenance.fallback_viewer_path,
        "product": document.provenance.product or document.inferred_product,
        "version": document.provenance.version or document.inferred_version,
        "trust_score": document.provenance.trust_score,
        "original_url": document.source_url,
        "original_title": document.provenance.original_title or document.title,
        "legal_notice_url": legal_notice_url,
        "license_or_terms": document.provenance.license_or_terms,
        "review_status": document.provenance.review_status,
        "verifiability": document.provenance.verifiability,
        "updated_at": document.provenance.updated_at,
        "translation_source_language": document.provenance.translation_source_language,
        "parsed_artifact_id": document.provenance.parsed_artifact_id,
        "tenant_id": document.provenance.tenant_id,
        "workspace_id": document.provenance.workspace_id,
        "pack_id": document.provenance.pack_id or document.pack_id,
        "pack_version": document.provenance.pack_version or document.inferred_version,
        "bundle_scope": document.provenance.bundle_scope,
        "classification": document.provenance.classification,
        "access_groups": list(document.provenance.access_groups),
        "provider_egress_policy": document.provenance.provider_egress_policy,
        "approval_state": document.provenance.approval_state,
        "publication_state": document.provenance.publication_state,
        "redaction_state": document.provenance.redaction_state,
        "citation_eligible": document.provenance.citation_eligible,
        "citation_block_reason": document.provenance.citation_block_reason,
    }
    return PlaybookDocumentArtifact(
        book_slug=document.book_slug,
        title=document.title,
        source_uri=document.source_url,
        source_language=document.source_language,
        language_hint=document.display_language,
        translation_status=document.translation_status,
        translation_stage=document.provenance.translation_stage,
        translation_source_uri=document.provenance.translation_source_url or document.source_url,
        translation_source_language=document.provenance.translation_source_language or document.source_language,
        translation_source_fingerprint=document.provenance.translation_source_fingerprint,
        pack_id=document.pack_id,
        inferred_version=document.inferred_version,
        legal_notice_url=legal_notice_url,
        review_status=document.provenance.review_status,
        sections=sections,
        quality_status=quality_status,
        quality_flags=tuple(quality_flags),
        source_metadata=source_metadata,
        anchor_map=anchor_map,
    )


def write_playbook_documents(
    path: Path,
    books_dir: Path,
    documents: list[PlaybookDocumentArtifact],
) -> None:
    books_dir.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    expected_filenames = {f"{document.book_slug}.json" for document in documents}
    with path.open("w", encoding="utf-8") as handle:
        for document in documents:
            payload = document.to_dict()
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            (books_dir / f"{document.book_slug}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    for stale_path in books_dir.glob("*.json"):
        if stale_path.name not in expected_filenames:
            stale_path.unlink()
