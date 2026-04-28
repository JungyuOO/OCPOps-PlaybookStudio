from __future__ import annotations

import json
from pathlib import Path

from play_book_studio.app.llmwiki_contextual_enrichment_gate import (
    build_llmwiki_contextual_enrichment_gate,
)


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    return path


def _row(chunk_id: str, *, book_title: str, section_path: list[str], text: str, collection: str) -> dict:
    return {
        "chunk_id": chunk_id,
        "book_slug": book_title.lower().replace(" ", "-"),
        "book_title": book_title,
        "chapter": section_path[0],
        "section": section_path[-1],
        "section_path": section_path,
        "source_lane": "official_ko" if collection == "core" else "customer_source_first_pack",
        "source_collection": collection,
        "source_type": "official_doc" if collection == "core" else "pptx",
        "chunk_type": "reference",
        "text": text,
    }


def test_contextual_enrichment_gate_passes_official_and_customer_rows(tmp_path: Path) -> None:
    official = _write_jsonl(
        tmp_path / "data" / "gold_corpus_ko" / "bm25_corpus.jsonl",
        [
            _row(
                "official-1",
                book_title="고급 네트워킹",
                section_path=["1장. 끝점에 대한 연결 확인"],
                text="CNO는 연결 상태 검사를 수행합니다.",
                collection="core",
            )
        ],
    )
    customer = _write_jsonl(
        tmp_path / "artifacts" / "customer_packs" / "corpus" / "customer-master" / "bm25_corpus.jsonl",
        [
            _row(
                "customer-1",
                book_title="고객 운영북",
                section_path=["운영 절차", "라우터 점검"],
                text="라우터 점검은 변경 전후로 수행합니다.",
                collection="uploaded",
            )
        ],
    )

    payload = build_llmwiki_contextual_enrichment_gate(
        tmp_path,
        official_bm25_path=official,
        customer_bm25_paths=[customer],
    )

    assert payload["status"] == "ok"
    assert payload["ready"] is True
    assert payload["checks"]["bm25_runtime_uses_contextual_search_text"] is True
    assert payload["checks"]["contextual_recall_fixture_improves"] is True
    assert payload["coverage"]["total"]["row_count"] == 2
    assert payload["coverage"]["total"]["runtime_contextual_count"] == 2


def test_contextual_enrichment_gate_fails_without_customer_rows(tmp_path: Path) -> None:
    official = _write_jsonl(
        tmp_path / "official.jsonl",
        [
            _row(
                "official-1",
                book_title="고급 네트워킹",
                section_path=["1장. 끝점에 대한 연결 확인"],
                text="CNO는 연결 상태 검사를 수행합니다.",
                collection="core",
            )
        ],
    )

    payload = build_llmwiki_contextual_enrichment_gate(
        tmp_path,
        official_bm25_path=official,
        customer_bm25_paths=[],
    )

    assert payload["status"] == "fail"
    assert "customer_corpus_loaded" in payload["failures"]
