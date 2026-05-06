from __future__ import annotations

import json
from pathlib import Path

from play_book_studio.cli import build_parser
from play_book_studio.ingestion.official_gold_import import (
    _heading_title,
    _normalized_chunk_text,
    _section_number,
    _section_path,
    _source_anchor,
    _toc_path,
    build_official_gold_import_plan,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_TMP = REPO_ROOT / "tmp" / "official_gold_import_tests"


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_build_official_gold_import_plan_groups_chunks_by_source():
    chunks_path = TEST_TMP / "chunks.jsonl"
    _write_jsonl(
        chunks_path,
        [
            {
                "chunk_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "book_slug": "architecture",
                "book_title": "Architecture",
                "source_id": "openshift:architecture",
                "text": "Architecture overview",
            },
            {
                "chunk_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "book_slug": "architecture",
                "book_title": "Architecture",
                "source_id": "openshift:architecture",
                "text": "Control plane",
            },
            {
                "chunk_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                "book_slug": "networking",
                "book_title": "Networking",
                "source_id": "openshift:networking",
                "text": "Routes",
            },
        ],
    )

    plan = build_official_gold_import_plan(chunks_path)

    assert plan["source_count"] == 2
    assert plan["chunk_count"] == 3
    assert plan["repository_slug"] == "official-docs"
    assert plan["visibility"] == "global_shared"
    assert plan["source_scope"] == "official_docs"
    assert [item["chunk_count"] for item in plan["sources"]] == [2, 1]


def test_official_gold_import_parser_accepts_args():
    args = build_parser().parse_args(
        [
            "official-gold-import",
            "--root-dir",
            str(REPO_ROOT),
            "--chunks-path",
            "corpus/data/gold_corpus_ko/chunks.jsonl",
            "--limit",
            "25",
            "--index",
            "--index-limit",
            "30000",
            "--refresh-qdrant-payloads",
            "--collection",
            "openshift_docs",
            "--refresh-limit",
            "30000",
            "--refresh-batch-size",
            "128",
            "--dry-run",
        ]
    )

    assert args.command == "official-gold-import"
    assert args.chunks_path == Path("corpus/data/gold_corpus_ko/chunks.jsonl")
    assert args.limit == 25
    assert args.index is True
    assert args.index_limit == 30000
    assert args.refresh_qdrant_payloads is True
    assert args.collection == "openshift_docs"
    assert args.refresh_limit == 30000
    assert args.refresh_batch_size == 128
    assert args.dry_run is True


def test_official_gold_import_derives_section_metadata_without_body_prefixes():
    row = {
        "book_slug": "architecture",
        "book_title": "Architecture",
        "chapter": "1 Networking",
        "section": "1.1 Routes and services",
        "section_path": ["1 Networking", "1.1 Routes and services"],
        "anchor": "routes",
        "text": "Architecture\n1 Networking > 1.1 Routes and services\n\nRoute body text.",
    }
    section_path = _section_path(row)

    assert section_path == ["Networking", "Routes and services"]
    assert _section_number(row) == "1.1"
    assert _heading_title(row, section_path) == "Routes and services"
    assert _source_anchor(row) == "routes"
    assert _toc_path(row) == ["1 Networking", "1.1 Routes and services"]
    assert _normalized_chunk_text(row) == "Route body text."
