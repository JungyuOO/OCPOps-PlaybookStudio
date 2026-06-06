from __future__ import annotations

from play_book_studio.evals.user_upload_quality_audit import (
    AuditThresholds,
    build_user_upload_quality_audit,
    is_title_only_user_upload_chunk,
)
from play_book_studio.retrieval.payload import text_hash


def _row(
    chunk_id: str,
    *,
    document_source_id: str = "doc-1",
    parsed_document_id: str = "parse-latest",
    is_latest: bool = True,
    text: str = (
        "PipelineRun builds the image, pushes it to the registry, and then the deployment "
        "rollout can consume the newly produced image from the configured namespace."
    ),
    token_count: int = 23,
    heading_title: str = "Pipeline steps",
    indexed_hash: str | None = None,
) -> dict[str, object]:
    embedding_hash = text_hash(text) if indexed_hash is None else indexed_hash
    return {
        "chunk_id": chunk_id,
        "document_source_id": document_source_id,
        "parsed_document_id": parsed_document_id,
        "latest_parsed_document_id": "parse-latest",
        "is_latest": is_latest,
        "document_title": "CI sequence",
        "filename": "ci.md",
        "chunk_type": "document",
        "embedding_text": text,
        "markdown": text,
        "token_count": token_count,
        "heading_title": heading_title,
        "section_path": ["CI sequence", heading_title],
        "toc_path": ["CI sequence", heading_title],
        "asset_ids": [],
        "repository_id": "repo-1",
        "owner_user_id": "owner-1",
        "source_scope": "user_upload",
        "indexed_embedding_text_hash": embedding_hash,
    }


def test_title_only_user_upload_chunk_detects_heading_echo() -> None:
    assert is_title_only_user_upload_chunk(
        _row(
            "title",
            text="CI sequence\n\nCI sequence",
            token_count=4,
            heading_title="CI sequence",
        )
    )

    assert not is_title_only_user_upload_chunk(
        _row(
            "body",
            text="CI sequence\n\nPipelineRun builds the image and pushes it to the registry.",
            token_count=11,
            heading_title="Pipeline steps",
        )
    )


def test_user_upload_quality_audit_separates_latest_and_stale_parse_chunks() -> None:
    payload = build_user_upload_quality_audit(
        [
            _row("latest-1"),
            _row(
                "stale-1",
                parsed_document_id="parse-old",
                is_latest=False,
                text="Old parse text that should be counted only as stale parse evidence.",
            ),
        ]
    )

    assert payload["decision"] == "pass"
    assert payload["all_chunk_count"] == 2
    assert payload["latest_chunk_count"] == 1
    assert payload["stale_parse_chunk_count"] == 1
    assert payload["latest_document_source_count"] == 1
    assert payload["documents"][0]["stale_parse_chunk_count"] == 1


def test_user_upload_quality_audit_fails_missing_or_stale_latest_embeddings() -> None:
    payload = build_user_upload_quality_audit(
        [
            _row("missing", indexed_hash=""),
            _row("stale", document_source_id="doc-2", indexed_hash="not-current"),
        ]
    )

    gates = {gate["name"]: gate for gate in payload["gates"]}

    assert payload["decision"] == "fail"
    assert payload["embedding"]["latest_missing_embedding_count"] == 1
    assert payload["embedding"]["latest_stale_embedding_count"] == 1
    assert gates["latest_missing_embeddings"]["status"] == "fail"
    assert gates["latest_stale_embeddings"]["status"] == "fail"


def test_user_upload_quality_audit_marks_title_only_rate_as_review_not_fail() -> None:
    payload = build_user_upload_quality_audit(
        [
            _row("title", text="CI sequence", token_count=2, heading_title="CI sequence"),
            _row("body", text="PipelineRun builds the image and pushes it to the registry.", token_count=10),
        ],
        thresholds=AuditThresholds(title_only_rate_review=0.25, undersized_rate_review=1.0),
    )

    gates = {gate["name"]: gate for gate in payload["gates"]}

    assert payload["decision"] == "review"
    assert payload["issue_counts"]["title_only_chunk"] == 1
    assert gates["title_only_rate"]["status"] == "review"
