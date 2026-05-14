from __future__ import annotations

import json
from pathlib import Path

from play_book_studio.ingestion.official_gold_enrichment import enrich_official_gold_chunks


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_enrich_official_gold_chunks_adds_parent_leaf_metadata(tmp_path: Path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    bm25_path = tmp_path / "bm25.jsonl"
    _write_jsonl(
        chunks_path,
        [
            {
                "chunk_id": "leaf-1",
                "book_slug": "installation",
                "book_title": "설치",
                "chapter": "설치",
                "section": "클러스터 설치",
                "anchor": "install-cluster",
                "source_url": "https://example.test/install",
                "viewer_path": "/docs/install#install-cluster",
                "text": "OpenShift 설치를 시작하기 전에 pull secret과 SSH key를 준비합니다.",
                "token_count": 12,
                "ordinal": 0,
                "section_id": "installation:install-cluster",
                "section_path": ["설치", "클러스터 설치"],
                "chunk_type": "concept",
                "source_id": "ocp:4.20:installation",
                "source_lane": "official_ko",
                "source_type": "official_doc",
                "source_collection": "core",
                "product": "openshift",
                "version": "4.20",
                "locale": "ko",
                "translation_status": "approved_ko",
                "review_status": "approved",
                "trust_score": 1.0,
                "cli_commands": [],
                "error_strings": [],
                "k8s_objects": [],
                "operator_names": [],
                "verification_hints": [],
            },
            {
                "chunk_id": "leaf-2",
                "book_slug": "installation",
                "book_title": "설치",
                "chapter": "설치",
                "section": "클러스터 설치",
                "anchor": "install-cluster",
                "source_url": "https://example.test/install",
                "viewer_path": "/docs/install#install-cluster",
                "text": "설치 후에는 oc get co 명령으로 ClusterOperator 상태를 확인합니다.",
                "token_count": 13,
                "ordinal": 1,
                "section_id": "installation:install-cluster",
                "section_path": ["설치", "클러스터 설치"],
                "chunk_type": "command",
                "source_id": "ocp:4.20:installation",
                "source_lane": "official_ko",
                "source_type": "official_doc",
                "source_collection": "core",
                "product": "openshift",
                "version": "4.20",
                "locale": "ko",
                "translation_status": "approved_ko",
                "review_status": "approved",
                "trust_score": 1.0,
                "cli_commands": ["oc get co"],
                "error_strings": [],
                "k8s_objects": [],
                "operator_names": ["ClusterOperator"],
                "verification_hints": [],
            },
        ],
    )

    report = enrich_official_gold_chunks(chunks_path, bm25_path=bm25_path)

    rows = _read_jsonl(chunks_path)
    leaf_rows = [row for row in rows if row["chunk_role"] == "leaf"]
    parent_rows = [row for row in rows if row["chunk_role"] == "parent"]
    assert report["leaf_count"] == 2
    assert report["parent_count"] == 1
    assert len(parent_rows) == 1
    assert {row["parent_chunk_id"] for row in leaf_rows} == {parent_rows[0]["chunk_id"]}
    assert parent_rows[0]["child_chunk_ids"] == ["leaf-1", "leaf-2"]
    assert all(row["starter_question_candidates"] for row in rows)
    assert all("�" not in question for row in rows for question in row["starter_question_candidates"])
    assert len(_read_jsonl(bm25_path)) == len(rows)


def test_enrich_official_gold_chunks_is_idempotent(tmp_path: Path) -> None:
    chunks_path = tmp_path / "chunks.jsonl"
    _write_jsonl(
        chunks_path,
        [
            {
                "chunk_id": "leaf-1",
                "book_slug": "cli",
                "book_title": "CLI",
                "chapter": "CLI",
                "section": "네임스페이스 확인",
                "anchor": "namespace-check",
                "source_url": "https://example.test/cli",
                "viewer_path": "/docs/cli#namespace-check",
                "text": "프로젝트 목록은 oc get projects 명령으로 확인합니다.",
                "token_count": 10,
                "ordinal": 0,
                "section_id": "cli:namespace-check",
                "section_path": ["CLI", "네임스페이스 확인"],
                "chunk_type": "command",
                "source_id": "ocp:4.20:cli",
                "source_lane": "official_ko",
                "source_type": "official_doc",
                "source_collection": "core",
                "product": "openshift",
                "version": "4.20",
                "locale": "ko",
                "translation_status": "approved_ko",
                "review_status": "approved",
                "trust_score": 1.0,
                "cli_commands": ["oc get projects"],
                "error_strings": [],
                "k8s_objects": ["Namespace"],
                "operator_names": [],
                "verification_hints": [],
            }
        ],
    )

    first = enrich_official_gold_chunks(chunks_path)
    second = enrich_official_gold_chunks(chunks_path)

    assert first["output_count"] == second["output_count"] == 2
    rows = _read_jsonl(chunks_path)
    assert [row["chunk_role"] for row in rows].count("parent") == 1
