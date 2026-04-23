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

from play_book_studio.app.intake_api import ingest_customer_pack
from play_book_studio.config.settings import load_settings
from play_book_studio.intake.private_corpus import (
    customer_pack_private_manifest_path,
    customer_pack_private_relations_path,
)
from play_book_studio.retrieval.bm25 import BM25Index
from play_book_studio.retrieval.models import SessionContext
from play_book_studio.retrieval.retriever import ChatRetriever
from tests.test_customer_pack_native_ooxml_smoke import _create_messy_pptx
from tests.test_customer_pack_read_boundary import (
    _FakeChunkingModel,
    _FakeEmbeddingModel,
)


class CustomerPackRelationCorpusTests(unittest.TestCase):
    def test_messy_pptx_materializes_relation_rows_into_private_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_path = root / "messy.pptx"
            _create_messy_pptx(source_path)

            with (
                patch(
                    "play_book_studio.intake.private_corpus.load_sentence_model",
                    return_value=_FakeEmbeddingModel(),
                ),
                patch(
                    "play_book_studio.ingestion.chunking.load_sentence_model",
                    return_value=_FakeChunkingModel(),
                ),
            ):
                result = ingest_customer_pack(
                    root,
                    {
                        "source_type": "pptx",
                        "uri": str(source_path),
                        "title": "P 유형 샘플",
                        "approval_state": "approved",
                    },
                )

            settings = load_settings(root)
            draft_id = str(result["draft_id"])
            manifest = json.loads(customer_pack_private_manifest_path(settings, draft_id).read_text(encoding="utf-8"))
            relation_rows = [
                json.loads(line)
                for line in customer_pack_private_relations_path(settings, draft_id).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

            self.assertEqual("canonical_json_bundle", manifest["relation_truth_owner"])
            self.assertGreater(int(manifest["relation_row_count"]), 0)
            self.assertEqual(str(customer_pack_private_relations_path(settings, draft_id)), manifest["relation_rows_path"])
            self.assertTrue(relation_rows)
            self.assertTrue(all(str(row.get("chunk_type") or "") == "relation" for row in relation_rows))
            self.assertTrue(all(str(row.get("truth_owner") or "") == "canonical_json_bundle" for row in relation_rows))
            self.assertTrue(any("flow" in list(row.get("relation_question_classes") or []) for row in relation_rows))
            self.assertTrue(any(str(row.get("lineage_viewer_path") or "").strip() for row in relation_rows))
            self.assertTrue(any("source_entity:" in str(row.get("text") or "") for row in relation_rows))

    def test_relation_query_prefers_relation_hit_for_selected_customer_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_path = root / "messy.pptx"
            _create_messy_pptx(source_path)

            with (
                patch(
                    "play_book_studio.intake.private_corpus.load_sentence_model",
                    return_value=_FakeEmbeddingModel(),
                ),
                patch(
                    "play_book_studio.ingestion.chunking.load_sentence_model",
                    return_value=_FakeChunkingModel(),
                ),
            ):
                result = ingest_customer_pack(
                    root,
                    {
                        "source_type": "pptx",
                        "uri": str(source_path),
                        "title": "P 유형 샘플",
                        "approval_state": "approved",
                    },
                )

            settings = load_settings(root)
            retriever = ChatRetriever(
                settings,
                BM25Index.from_rows([]),
                vector_retriever=None,
                reranker=None,
            )
            retrieval = retriever.retrieve(
                "CI에서 운영 환경으로 어떤 흐름으로 넘어가?",
                context=SessionContext(
                    mode="chat",
                    selected_draft_ids=[str(result["draft_id"])],
                    restrict_uploaded_sources=True,
                ),
                top_k=5,
                candidate_k=10,
                use_bm25=True,
                use_vector=False,
            )

            self.assertTrue(retrieval.hits)
            top_hit = retrieval.hits[0]
            self.assertGreaterEqual(int(retrieval.trace.get("effective_candidate_k") or 0), 30)
            self.assertEqual("uploaded", top_hit.source_collection)
            self.assertEqual("relation", top_hit.chunk_type)
            self.assertIn("flow", tuple(str(item) for item in top_hit.graph_relations))
            self.assertTrue(str(top_hit.viewer_path or "").startswith("/playbooks/customer-packs/"))


if __name__ == "__main__":
    unittest.main()
