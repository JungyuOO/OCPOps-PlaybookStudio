from __future__ import annotations

import json
from pathlib import Path

from play_book_studio.cli import _run_upload_ingest, build_parser

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_TMP = REPO_ROOT / "tmp" / "upload_ingest_cli_tests"


def test_upload_ingest_parser_accepts_dry_run_file_args():
    args = build_parser().parse_args(
        [
            "upload-ingest",
            "--root-dir",
            str(REPO_ROOT),
            "--path",
            "tmp/sample.md",
            "--tenant-slug",
            "ocp",
            "--workspace-slug",
            "ops",
            "--dry-run",
        ]
    )

    assert args.command == "upload-ingest"
    assert args.path == Path("tmp/sample.md")
    assert args.tenant_slug == "ocp"
    assert args.workspace_slug == "ops"
    assert args.dry_run is True


def test_upload_ingest_dry_run_outputs_parse_and_chunk_summary(capsys):
    TEST_TMP.mkdir(parents=True, exist_ok=True)
    source = TEST_TMP / "sample.md"
    source.write_text("# Operations\n\nCheck health.\n\n## Verify\n\noc get co", encoding="utf-8")
    args = build_parser().parse_args(
        [
            "upload-ingest",
            "--root-dir",
            str(REPO_ROOT),
            "--path",
            str(source),
            "--chunk-max-chars",
            "80",
            "--chunk-overlap-blocks",
            "0",
            "--dry-run",
        ]
    )

    exit_code = _run_upload_ingest(args)

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["filename"] == "sample.md"
    assert payload["document_format"] == "md"
    assert payload["block_count"] == 4
    assert payload["chunk_count"] == 2
    assert payload["persisted"] is None
    assert ["Operations", "Verify"] in payload["sections"]
