from __future__ import annotations

from pathlib import Path

from play_book_studio.ingestion.document_parsing import build_document_chunks, parse_upload_document
from play_book_studio.wiki_gold_builder import (
    build_official_materialize_gold_run,
    gold_build_contract_from_blockers,
    prepare_upload_gold_build_candidate,
)


def _parse_markdown(tmp_path: Path, name: str, text: str):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    parsed = parse_upload_document(path)
    chunks = build_document_chunks(parsed, max_chars=300, overlap_blocks=0)
    return parsed, chunks


def test_upload_gold_build_repairs_headingless_korean_document(tmp_path: Path) -> None:
    parsed, chunks = _parse_markdown(
        tmp_path,
        "cluster-check.md",
        "클러스터 상태를 확인합니다.\n\n운영자는 콘솔과 API 상태를 함께 점검합니다.",
    )

    assert chunks
    assert all(not chunk.section_path for chunk in chunks)

    prepared = prepare_upload_gold_build_candidate(
        parsed,
        chunks,
        source_scope="user_upload",
        index_result={"candidate_count": len(chunks), "indexed_count": len(chunks)},
    )

    assert all(chunk.section_path for chunk in prepared.chunks)
    assert prepared.parsed.markdown.startswith("# cluster check")
    assert prepared.run["status"] == "gold"
    assert prepared.run["final_grade"] == "Gold"
    assert prepared.run["repair_actions"][0]["id"] == "semantic_section_rebuild"
    assert prepared.run["repair_actions"][0]["status"] == "applied"


def test_upload_gold_build_routes_english_content_to_repair_writer(tmp_path: Path) -> None:
    parsed, chunks = _parse_markdown(
        tmp_path,
        "hcp-architecture.md",
        "# Hosted control planes\n\nHosted control planes decouple the control plane from worker nodes.",
    )

    prepared = prepare_upload_gold_build_candidate(
        parsed,
        chunks,
        source_scope="user_upload",
        index_result={"candidate_count": len(chunks), "indexed_count": len(chunks)},
    )

    assert prepared.run["status"] == "needs_manual_repair"
    assert prepared.run["final_grade"] == "Gold Build Repair"
    assert [item["code"] for item in prepared.run["diagnostics"]] == ["non_ko_content"]
    assert prepared.run["repair_actions"][0]["id"] == "ko_operational_rewrite"
    assert prepared.run["repair_actions"][0]["status"] == "provider_required"
    assert "한국어 운영 문서체" in prepared.run["repair_actions"][0]["summary"]


def test_gold_contract_blockers_become_repair_queue_actions() -> None:
    run = gold_build_contract_from_blockers(
        ["zero_sections", "missing_source_provenance"],
        title="Broken Runtime Book",
        metrics={"section_count": 0, "chunk_count": 4},
    )

    assert run["status"] == "needs_manual_repair"
    assert run["current_stage"] == "repair"
    assert [action["id"] for action in run["repair_actions"]] == [
        "semantic_section_rebuild",
        "anchor_metadata_rebuild",
    ]
    assert run["manual_repair_needed"] is True


def test_official_materialize_gold_run_promotes_after_smoke() -> None:
    run = build_official_materialize_gold_run(
        {
            "book_slug": "hcp",
            "source_basis": "official_homepage",
            "title": "호스팅된 컨트롤 플레인",
            "draft_summary": {"generated_count": 1, "section_count": 3, "chunk_count": 12},
            "gold_summary": {"promoted_count": 1, "qdrant_upserted_count": 12},
            "smoke": {
                "approved_manifest_present": True,
                "viewer_ready": True,
                "source_meta_ready": True,
            },
        }
    )

    assert run["status"] == "gold"
    assert run["final_grade"] == "Gold"
    assert {action["id"] for action in run["repair_actions"]} == {
        "ko_operational_rewrite",
        "anchor_metadata_rebuild",
    }
    assert all(action["status"] == "applied" for action in run["repair_actions"])
