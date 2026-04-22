"""번역 lane 상태와 provenance를 공통 규칙으로 계산한다."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import (
    CONTENT_STATUS_APPROVED_KO,
    CONTENT_STATUS_BLOCKED,
    CONTENT_STATUS_EN_ONLY,
    CONTENT_STATUS_MIXED,
    CONTENT_STATUS_TRANSLATED_KO_DRAFT,
    SourceManifestEntry,
)


TRANSLATION_STAGE_APPROVED = "approved_ko"
TRANSLATION_STAGE_DRAFT_REVIEW = "translated_ko_draft"
TRANSLATION_STAGE_TRANSLATION_REQUIRED = "en_only"
TRANSLATION_STAGE_MIXED_REVIEW = "mixed_review"
TRANSLATION_STAGE_BLOCKED = "blocked"
TRANSLATION_STAGE_UNKNOWN = "unknown"


def translation_stage_for_status(content_status: str) -> str:
    status = (content_status or "").strip()
    if status == CONTENT_STATUS_APPROVED_KO:
        return TRANSLATION_STAGE_APPROVED
    if status == CONTENT_STATUS_TRANSLATED_KO_DRAFT:
        return TRANSLATION_STAGE_DRAFT_REVIEW
    if status == CONTENT_STATUS_EN_ONLY:
        return TRANSLATION_STAGE_TRANSLATION_REQUIRED
    if status == CONTENT_STATUS_MIXED:
        return TRANSLATION_STAGE_MIXED_REVIEW
    if status == CONTENT_STATUS_BLOCKED:
        return TRANSLATION_STAGE_BLOCKED
    return TRANSLATION_STAGE_UNKNOWN


def translation_next_status(content_status: str) -> str:
    status = (content_status or "").strip()
    if status == CONTENT_STATUS_EN_ONLY:
        return CONTENT_STATUS_TRANSLATED_KO_DRAFT
    if status == CONTENT_STATUS_TRANSLATED_KO_DRAFT:
        return CONTENT_STATUS_APPROVED_KO
    if status == CONTENT_STATUS_MIXED:
        return CONTENT_STATUS_TRANSLATED_KO_DRAFT
    return status or CONTENT_STATUS_BLOCKED


def translation_output_mode(content_status: str) -> str:
    stage = translation_stage_for_status(content_status)
    if stage == TRANSLATION_STAGE_APPROVED:
        return "runtime"
    if stage == TRANSLATION_STAGE_DRAFT_REVIEW:
        return "draft_review"
    if stage == TRANSLATION_STAGE_TRANSLATION_REQUIRED:
        return "translation_required"
    if stage == TRANSLATION_STAGE_MIXED_REVIEW:
        return "mixed_review"
    if stage == TRANSLATION_STAGE_BLOCKED:
        return "blocked"
    return "unknown"


def build_translation_metadata(
    entry: SourceManifestEntry,
    *,
    content_status: str | None = None,
    citation_eligible: bool | None = None,
    corpus_dir: Path | None = None,
) -> dict[str, Any]:
    status = (content_status or entry.content_status or "").strip()
    source_language = (
        entry.translation_source_language
        or entry.resolved_language
        or entry.docs_language
        or "ko"
    ).strip() or "ko"
    target_language = (
        entry.translation_target_language
        or entry.docs_language
        or "ko"
    ).strip() or "ko"
    stage = translation_stage_for_status(status)
    runtime_eligible = status == CONTENT_STATUS_APPROVED_KO
    artifact_targets: dict[str, str] = {}
    if corpus_dir is not None:
        artifact_targets = {
            "normalized_docs_path": str(corpus_dir / "normalized_docs.jsonl"),
            "playbook_documents_path": str(corpus_dir / "playbook_documents.jsonl"),
            "playbook_book_path": str(corpus_dir / "playbooks" / f"{entry.book_slug}.json"),
        }
    return {
        "current_status": status,
        "stage": stage,
        "next_status": translation_next_status(status),
        "source_language": source_language,
        "target_language": target_language,
        "source_url": entry.translation_source_url or entry.resolved_source_url or entry.source_url,
        "source_fingerprint": entry.translation_source_fingerprint or entry.source_fingerprint,
        "requires_translation": status in {CONTENT_STATUS_EN_ONLY, CONTENT_STATUS_MIXED},
        "requires_review": status == CONTENT_STATUS_TRANSLATED_KO_DRAFT,
        "runtime_eligible": runtime_eligible,
        "citation_eligible": runtime_eligible if citation_eligible is None else bool(citation_eligible),
        "corpus_output_mode": translation_output_mode(status),
        "playbook_output_mode": translation_output_mode(status),
        "artifact_targets": artifact_targets,
    }
