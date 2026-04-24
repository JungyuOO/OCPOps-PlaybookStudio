from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.config.settings import load_settings
from play_book_studio.config.validation import read_jsonl
from play_book_studio.ingestion.models import NormalizedSection
from play_book_studio.ingestion.runtime_catalog_library import (
    _retain_non_official_non_derived_playbook_rows,
    _retain_non_official_rows,
    materialize_runtime_corpus_from_playbooks,
)


class _FakeTokenizer:
    model_max_length = 128

    def __call__(
        self,
        text: str,
        *,
        add_special_tokens: bool = False,
        truncation: bool = False,
        return_attention_mask: bool = False,
        return_token_type_ids: bool = False,
        **_: object,
    ):
        token_count = max(1, len(str(text or "").split()))
        return {"input_ids": list(range(token_count))}


class _FakeChunkingModel:
    tokenizer = _FakeTokenizer()


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _normalized_section(
    *,
    slug: str,
    title: str,
    heading: str,
    anchor: str,
    source_type: str,
    source_lane: str,
) -> dict:
    return NormalizedSection(
        book_slug=slug,
        book_title=title,
        heading=heading,
        section_level=2,
        section_path=[heading],
        anchor=anchor,
        source_url=f"https://docs.example/{slug}",
        viewer_path=f"/docs/ocp/4.20/ko/{slug}/index.html#{anchor}",
        text=f"{title}\n\n{heading}\n\n운영 설명 본문",
        section_id=f"{slug}:{anchor}",
        semantic_role="concept",
        block_kinds=("paragraph",),
        source_language="ko",
        display_language="ko",
        translation_status="approved_ko",
        translation_stage="approved_ko",
        source_id=f"source:{slug}",
        source_lane=source_lane,
        source_type=source_type,
        source_collection="core",
        product="openshift",
        version="4.20",
        locale="ko",
        review_status="approved",
        approval_state="approved",
        publication_state="published",
    ).to_dict()


class OfficialRuntimeCorpusTests(unittest.TestCase):
    def test_runtime_retain_helpers_do_not_prune_manual_synthesis_rows(self) -> None:
        normalized_rows = [
            {"source_type": "manual_synthesis", "book_slug": "ai_workloads"},
            {"source_type": "official_doc", "book_slug": "architecture"},
            {"source_type": "uploaded", "book_slug": "customer_pack"},
        ]
        playbook_rows = [
            {"book_slug": "ai_workloads", "source_metadata": {"source_type": "manual_synthesis"}},
            {"book_slug": "architecture", "source_metadata": {"source_type": "official_doc"}},
            {"book_slug": "customer_pack", "source_metadata": {"source_type": "uploaded"}},
        ]

        retained_normalized = _retain_non_official_rows(normalized_rows)
        retained_playbooks = _retain_non_official_non_derived_playbook_rows(playbook_rows)

        self.assertEqual(
            {"ai_workloads", "customer_pack"},
            {str(row.get("book_slug") or "") for row in retained_normalized},
        )
        self.assertEqual(
            {"ai_workloads", "customer_pack"},
            {str(row.get("book_slug") or "") for row in retained_playbooks},
        )

    def test_materializer_backfills_manual_synthesis_into_runtime_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = load_settings(root)
            normalized_rows = [
                _normalized_section(
                    slug="ai_workloads",
                    title="AI 워크로드",
                    heading="AI 워크로드 개요",
                    anchor="ai-workloads-overview",
                    source_type="manual_synthesis",
                    source_lane="applied_playbook",
                ),
                _normalized_section(
                    slug="architecture",
                    title="아키텍처",
                    heading="아키텍처 개요",
                    anchor="architecture-overview",
                    source_type="official_doc",
                    source_lane="official_ko",
                ),
            ]
            _write_jsonl(settings.normalized_docs_path, normalized_rows)

            with (
                patch(
                    "play_book_studio.ingestion.runtime_catalog_library.materialize_derived_playbooks",
                    return_value={"generated_count": 0},
                ),
                patch(
                    "play_book_studio.ingestion.runtime_catalog_library.refresh_active_runtime_graph_artifacts",
                    return_value={"full_sidecar": {"book_count": 2, "relation_count": 0}},
                ),
                patch(
                    "play_book_studio.ingestion.chunking.load_sentence_model",
                    return_value=_FakeChunkingModel(),
                ),
            ):
                report = materialize_runtime_corpus_from_playbooks(
                    settings,
                    sync_qdrant=False,
                )

            chunk_rows = list(read_jsonl(settings.chunks_path))
            chunk_slugs = {str(row.get("book_slug") or "") for row in chunk_rows}

            self.assertEqual(2, report["official_section_count"])
            self.assertEqual(2, report["runtime_book_count"])
            self.assertIn("ai_workloads", chunk_slugs)
            self.assertIn("architecture", chunk_slugs)
            self.assertTrue(
                any(
                    str(row.get("book_slug") or "") == "ai_workloads"
                    and str(row.get("source_type") or "") == "manual_synthesis"
                    for row in chunk_rows
                )
            )


if __name__ == "__main__":
    unittest.main()
