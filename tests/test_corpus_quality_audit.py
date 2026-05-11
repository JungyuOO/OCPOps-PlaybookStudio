from __future__ import annotations

import json

from play_book_studio.ingestion.corpus_quality_audit import (
    CorpusAuditTarget,
    audit_chunk_rows,
    audit_corpus_jsonl,
    audit_runtime_corpus,
    chunk_text,
)


def test_audit_chunk_rows_reports_rag_input_quality_signals() -> None:
    rows = [
        {
            "chunk_id": "good",
            "title": "Project scope check",
            "source_url": "https://docs.example.test",
            "text": "Use project and namespace scope checks before narrowing the resource range for a command lookup.",
            "cli_commands": ["oc project", "oc get ns"],
        },
        {
            "chunk_id": "good",
            "title": "\u6028\u4e2d\u751f ?\u4e16\u4ee3?\u6587",
            "source_url": "https://docs.example.test/bad",
            "text": "\u6028\u4e2d\u751f ?\u4e16\u4ee3?\u6587 \u4f5c\u696d ?\u7bc4\u56f2 ?\u72b6\u614b?? \u70b9\u691c",
        },
        {
            "chunk_id": "image",
            "title": "Performance test",
            "source_pptx": "study-docs/perf.pptx",
            "search_text": "Performance testing starts by checking the TPS goal and test environment differences.",
            "image_attachments": [{"asset_path": "data/course_pbs/assets/perf.png"}],
            "source_chunk_ids": ["perf-source"],
            "query_variants": ["What should I check first for a performance test?"],
        },
        {"chunk_id": "empty", "title": "Empty chunk", "source_ref": "x"},
    ]

    report = audit_chunk_rows(rows, label="sample", source_scope="study_docs")

    assert report["row_count"] == 4
    assert report["duplicate_id_count"] == 1
    assert report["missing_text_count"] == 1
    assert report["command_reference_count"] == 1
    assert report["image_reference_count"] == 1
    assert report["asset_reference_count"] == 1
    assert report["image_without_direct_asset_count"] == 0
    assert report["source_chunk_reference_count"] == 1
    assert report["query_variant_count"] == 1
    assert report["mojibake"]["suspect_count"] == 1
    assert report["mojibake"]["examples"][0]["chunk_id"] == "good"


def test_audit_chunk_rows_flags_image_evidence_without_direct_asset() -> None:
    rows = [
        {
            "learning_chunk_id": "ops-step",
            "title": "Performance goal",
            "source_chunk_ids": ["source-chunk"],
            "embedding_text": "Review the performance goal, workload profile, and bottleneck notes before tuning.",
            "image_evidence_texts": ["JMeter screenshot summary"],
        }
    ]

    report = audit_chunk_rows(rows, label="ops", source_scope="study_docs")

    assert report["missing_source_count"] == 0
    assert report["image_reference_count"] == 1
    assert report["asset_reference_count"] == 0
    assert report["image_without_direct_asset_count"] == 1


def test_chunk_text_uses_nested_index_texts_for_course_chunks() -> None:
    text = chunk_text(
        {
            "body_md": "본문",
            "index_texts": {
                "dense_text": "검색용 dense 텍스트",
                "visual_text": "이미지 설명",
            },
        }
    )

    assert "본문" in text
    assert "검색용 dense 텍스트" in text
    assert "이미지 설명" in text


def test_audit_runtime_corpus_skips_missing_targets(tmp_path) -> None:
    report = audit_runtime_corpus(tmp_path)

    assert report["canonical_model"] == "corpus_quality_audit_v1"
    assert report["target_count"] == 3
    assert report["present_target_count"] == 0
    assert all(not target["exists"] for target in report["targets"])


def test_audit_corpus_jsonl_reads_utf8_jsonl(tmp_path) -> None:
    path = tmp_path / "chunks.jsonl"
    path.write_text(
        json.dumps(
            {
                "chunk_id": "one",
            "title": "OpenShift install",
            "source_url": "https://docs.example.test/install",
            "text": "OpenShift Container Platform installation methods differ by environment: Assisted Installer, Agent-based Installer, IPI, and UPI.",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    report = audit_corpus_jsonl(CorpusAuditTarget("official", path, "official_docs"))

    assert report["exists"] is True
    assert report["row_count"] == 1
    assert report["mojibake"]["suspect_count"] == 0
