from __future__ import annotations

import json
from pathlib import Path

from play_book_studio.evals.chunk_quality_audit import build_chunk_quality_audit


def test_chunk_quality_audit_counts_command_and_markup_issues() -> None:
    payload = build_chunk_quality_audit(
        [
            {
                "chunk_id": "cmd-1",
                "book_slug": "cli_tools",
                "section": "Current project",
                "text": "[CODE language=\"shell\"] oc project [/CODE]\nAdditional resources",
                "token_count": 12,
                "chunk_type": "command",
                "cli_commands": ["oc project"],
                "display_language": "ko",
                "section_path": ["CLI", "Current project"],
            },
            {
                "chunk_id": "big-1",
                "book_slug": "support",
                "section": "Large",
                "text": " ".join(["word"] * 320),
                "token_count": 320,
                "chunk_type": "reference",
                "cli_commands": [],
                "display_language": "ko",
                "section_path": ["Support"],
            },
        ]
    )

    assert payload["chunk_count"] == 2
    assert payload["command_chunks"]["count"] == 1
    assert payload["issue_counts"]["raw_code_markup"] == 1
    assert payload["issue_counts"]["code_plus_navigation"] == 1
    assert payload["issue_counts"]["oversized_chunk"] == 1
    assert payload["issue_samples"]["raw_code_markup"][0]["chunk_id"] == "cmd-1"


def test_v004_readable_eval_manifests_are_valid_jsonl() -> None:
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "corpus/manifests/eval/pbs_chat_quality_v004_readable_cases.jsonl",
        root / "corpus/manifests/eval/retrieval_sanity_v004_readable_cases.jsonl",
    ]

    for path in paths:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(rows) >= 5
        assert {row["query_type"] for row in rows} >= {"ops_troubleshooting", "negative"}
        assert all(row.get("id") and row.get("query") for row in rows)
