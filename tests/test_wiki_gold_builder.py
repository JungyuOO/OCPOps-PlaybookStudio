from __future__ import annotations

from pathlib import Path

from play_book_studio.ingestion.document_parsing import build_document_chunks, parse_upload_document
from play_book_studio.wiki_gold_builder import (
    build_gold_build_run,
    build_official_materialize_gold_run,
    gold_build_contract_from_blockers,
    prepare_upload_gold_build_candidate,
    with_index_verification,
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


def test_upload_gold_build_allows_korean_technical_docs_with_commands(tmp_path: Path) -> None:
    parsed, chunks = _parse_markdown(
        tmp_path,
        "ci-runbook.md",
        "\n\n".join(
            [
                "# CI 장애 대응",
                "파이프라인 실패 시 먼저 최근 실행 이력과 이벤트를 확인합니다.",
                "## 증상 확인",
                "빌드 로그에서 실패한 태스크와 네임스페이스를 확인합니다.",
                "## 실행 명령",
                "```bash\noc get pods -n ci\nkubectl describe pod build-runner\n```",
                "## 복구 기준",
                "재시도 후 동일 오류가 반복되면 이미지 풀 정책과 시크릿을 점검합니다.",
            ]
        ),
    )

    prepared = prepare_upload_gold_build_candidate(
        parsed,
        chunks,
        source_scope="user_upload",
        index_result={"candidate_count": len(chunks), "indexed_count": len(chunks)},
    )

    diagnostic_codes = [item["code"] for item in prepared.run["diagnostics"]]
    assert "mixed_ko_content" not in diagnostic_codes
    assert prepared.run["status"] == "gold"
    assert prepared.run["repair_actions"] == []


def test_gold_build_run_requires_index_evidence_for_gold() -> None:
    run = build_gold_build_run(
        run_id="run-1",
        source_kind="upload",
        source_scope="user_upload",
        title="업로드 문서",
        diagnostics=[],
        repair_actions=[],
        dry_run=False,
        index_result=None,
        metrics={"section_count": 1, "chunk_count": 3},
    )

    assert run["status"] == "building_gold"
    assert run["final_grade"] == "Gold Build Repair"
    assert run["qdrant_index"] == {}
    reindex = next(stage for stage in run["stage_results"] if stage["stage"] == "reindex")
    assert reindex["status"] == "pending"


def test_gold_build_run_rejects_incomplete_index_evidence() -> None:
    run = build_gold_build_run(
        run_id="run-1",
        source_kind="upload",
        source_scope="user_upload",
        title="업로드 문서",
        diagnostics=[],
        repair_actions=[],
        dry_run=False,
        index_result={"candidate_count": 3, "indexed_count": 2},
        metrics={"section_count": 1, "chunk_count": 3},
    )

    assert run["status"] == "building_gold"
    reindex = next(stage for stage in run["stage_results"] if stage["stage"] == "reindex")
    assert reindex["status"] == "fail"
    assert "2/3" in reindex["detail"]


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


def test_index_verification_marks_embedding_failure_as_repair_work() -> None:
    run = gold_build_contract_from_blockers(
        [],
        title="업로드 문서",
        metrics={"section_count": 1, "chunk_count": 3},
    )

    updated = with_index_verification(
        run,
        index_result={
            "collection": "openshift_docs",
            "candidate_count": 3,
            "indexed_count": 0,
            "status": "deferred",
            "error": "Failed to fetch embeddings",
        },
    )

    assert updated["status"] == "repairing"
    assert updated["diagnostics"][0]["code"] == "index_gap"
    assert updated["diagnostics"][0]["summary"] == "Qdrant 색인이 완료되지 않았습니다."
    assert "error=Failed to fetch embeddings" in updated["diagnostics"][0]["evidence"]
