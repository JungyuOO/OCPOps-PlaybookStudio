from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.app.intake_api import ingest_customer_pack
from play_book_studio.config.settings import load_settings
from play_book_studio.intake.artifact_bundle import iter_customer_pack_book_payload_paths
from play_book_studio.intake.private_corpus import (
    customer_pack_private_bm25_path,
    customer_pack_private_chunks_path,
)
from play_book_studio.retrieval.intake_overlay import customer_pack_books_fingerprint
from tests.test_customer_pack_read_boundary import (
    _FakeChunkingModel,
    _FakeEmbeddingModel,
    _test_server,
)


def _ingest_rich_md_pack(root: Path) -> dict[str, object]:
    source_md = root / "artifact-bundle.md"
    source_md.write_text(
        (
            "# 운영 가이드\n\n"
            "## 백업 절차\n\n"
            "운영 전에 구성과 백업 절차를 먼저 점검한다.\n"
            "oc get nodes\n"
            "oc get pods -A\n\n"
            "## 장애 복구\n\n"
            "오류 발생 시 로그를 확인하고 복구 절차를 진행한다.\n"
            "Error: CrashLoopBackOff\n"
            "복구 후 검증 단계를 다시 실행한다.\n\n"
            "## 정책 검증\n\n"
            "필수 보안 요구 사항과 제한 조건을 검토한다.\n"
            "must keep audit logging enabled.\n"
        ),
        encoding="utf-8",
    )

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
        return ingest_customer_pack(
            root,
            {
                "source_type": "md",
                "uri": str(source_md),
                "title": "운영 가이드",
                "approval_state": "approved",
            },
        )


class CustomerPackArtifactBundleTests(unittest.TestCase):
    def test_artifact_bundle_writes_sidecars_without_polluting_book_payload_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            result = _ingest_rich_md_pack(root)
            settings = load_settings(root)

            book = dict(result.get("book") or {})
            private_corpus = dict(result.get("private_corpus") or {})
            artifact_bundle = dict(book.get("artifact_bundle") or {})

            self.assertEqual("canonical_json_bundle", artifact_bundle["truth_owner"])
            self.assertTrue(Path(str(book["artifact_manifest_path"])).exists())
            self.assertEqual("canonical_json_bundle", private_corpus["truth_owner"])
            self.assertGreaterEqual(int(private_corpus["playable_asset_count"]), 1)
            self.assertGreaterEqual(int(private_corpus["anchor_lineage_count"]), 1)
            self.assertIn(book["shared_grade"], {"gold", "silver"})
            self.assertEqual("exact", book["grade_gate"]["citation_gate"]["status"])
            self.assertTrue(book["grade_gate"]["retrieval_gate"]["ready"])
            self.assertTrue(private_corpus["read_ready"])
            self.assertEqual("exact", private_corpus["citation_landing_status"])
            self.assertTrue(private_corpus["retrieval_ready"])

            manifest_payload = json.loads(Path(str(book["artifact_manifest_path"])).read_text(encoding="utf-8"))
            self.assertEqual("canonical_json_bundle", manifest_payload["truth_owner"])
            self.assertEqual(str(result["draft_id"]), manifest_payload["draft_id"])
            self.assertTrue(Path(str(manifest_payload["relations_path"])).exists())
            self.assertTrue(Path(str(manifest_payload["figure_assets_path"])).exists())
            self.assertTrue(Path(str(manifest_payload["citations_path"])).exists())
            self.assertEqual(str(private_corpus["manifest_path"]), manifest_payload["corpus_manifest_path"])
            self.assertIn(manifest_payload["shared_grade"], {"gold", "silver"})
            self.assertTrue(manifest_payload["read_ready"])
            self.assertTrue(manifest_payload["retrieval_ready"])

            relations_payload = json.loads(Path(str(manifest_payload["relations_path"])).read_text(encoding="utf-8"))
            citations_payload = json.loads(Path(str(manifest_payload["citations_path"])).read_text(encoding="utf-8"))
            self.assertTrue(relations_payload["section_relation_index"])
            self.assertTrue(citations_payload["citations"])

            chunk_rows = [
                json.loads(line)
                for line in customer_pack_private_chunks_path(settings, str(result["draft_id"])).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            bm25_rows = [
                json.loads(line)
                for line in customer_pack_private_bm25_path(settings, str(result["draft_id"])).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertTrue(chunk_rows)
            self.assertTrue(bm25_rows)
            self.assertTrue(all(row["truth_owner"] == "canonical_json_bundle" for row in chunk_rows))
            self.assertTrue(all(row["canonical_book_slug"] == str(book["book_slug"]) for row in chunk_rows))
            self.assertTrue(all(str(row.get("asset_slug") or "").strip() for row in chunk_rows))
            self.assertTrue(any(str(row.get("semantic_role") or "").strip() == "procedure" for row in chunk_rows))
            self.assertTrue(any(row.get("block_kinds") for row in chunk_rows))
            self.assertTrue(any(row.get("cli_commands") for row in bm25_rows))
            self.assertTrue(all(row["truth_owner"] == "canonical_json_bundle" for row in bm25_rows))
            self.assertTrue(any(str(row.get("lineage_section_key") or "").strip() for row in bm25_rows))

            payload_paths = iter_customer_pack_book_payload_paths(settings.customer_pack_books_dir)
            all_json_paths = sorted(settings.customer_pack_books_dir.glob("*.json"))
            self.assertEqual(int(book["playable_asset_count"]), len(payload_paths))
            self.assertGreater(len(all_json_paths), len(payload_paths))

            fingerprint = customer_pack_books_fingerprint(settings.customer_pack_books_dir)
            self.assertEqual(len(payload_paths), len(fingerprint))

            derived_assets = [dict(item) for item in (book.get("derived_assets") or []) if isinstance(item, dict)]
            self.assertTrue(derived_assets)
            derived_slug = str(derived_assets[0]["asset_slug"])
            derived_book_path = settings.customer_pack_books_dir / f"{derived_slug}.json"
            derived_manifest_path = settings.customer_pack_books_dir / f"{derived_slug}.manifest.json"
            self.assertTrue(derived_book_path.exists())
            self.assertTrue(derived_manifest_path.exists())
            derived_payload = json.loads(derived_book_path.read_text(encoding="utf-8"))
            self.assertEqual("canonical_json_bundle", derived_payload["artifact_bundle"]["truth_owner"])

    def test_public_book_route_drops_internal_artifact_bundle_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            result = _ingest_rich_md_pack(root)

            with _test_server(root) as (base_url, _store, _answerer):
                response = requests.get(
                    f"{base_url}/api/customer-packs/book",
                    params={"draft_id": str(result["draft_id"])},
                    timeout=10,
                )

            self.assertEqual(200, response.status_code)
            payload = response.json()
            self.assertNotIn("artifact_bundle", payload)
            self.assertNotIn("artifact_manifest_path", payload)


if __name__ == "__main__":
    unittest.main()
