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
from play_book_studio.ingestion.graph_sidecar import (
    refresh_active_runtime_graph_artifacts,
    write_graph_sidecar_from_artifacts,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


class GraphSidecarDegradeTests(unittest.TestCase):
    def test_write_graph_sidecar_from_artifacts_writes_valid_full_and_compact_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = load_settings(root)
            _write_jsonl(
                settings.playbook_documents_path,
                [
                    {
                        "book_slug": "architecture",
                        "title": "아키텍처",
                        "source_uri": "https://docs.example/architecture",
                        "review_status": "approved",
                        "quality_status": "ready",
                        "source_metadata": {
                            "source_type": "official_doc",
                            "source_lane": "official_ko",
                            "source_collection": "core",
                        },
                    }
                ],
            )
            _write_jsonl(
                settings.chunks_path,
                [
                    {
                        "chunk_id": "architecture:intro",
                        "book_slug": "architecture",
                        "book_title": "아키텍처",
                        "chapter": "1",
                        "section": "개요",
                        "anchor": "intro",
                        "viewer_path": "/docs/ocp/4.20/ko/architecture/index.html#intro",
                        "source_url": "https://docs.example/architecture",
                        "text": "아키텍처 개요",
                        "token_count": 3,
                        "ordinal": 1,
                        "source_collection": "core",
                        "source_type": "official_doc",
                        "source_lane": "official_ko",
                        "k8s_objects": ["IngressController"],
                        "operator_names": ["ingress-operator"],
                        "error_strings": [],
                        "verification_hints": ["oc get ingresscontroller"],
                    },
                    {
                        "chunk_id": "architecture:details",
                        "book_slug": "architecture",
                        "book_title": "아키텍처",
                        "chapter": "1",
                        "section": "상세",
                        "anchor": "details",
                        "viewer_path": "/docs/ocp/4.20/ko/architecture/index.html#details",
                        "source_url": "https://docs.example/architecture",
                        "text": "아키텍처 상세",
                        "token_count": 3,
                        "ordinal": 2,
                        "source_collection": "core",
                        "source_type": "official_doc",
                        "source_lane": "official_ko",
                        "k8s_objects": ["IngressController"],
                        "operator_names": ["ingress-operator"],
                        "error_strings": [],
                        "verification_hints": ["oc describe ingresscontroller"],
                    },
                ],
            )

            output_path, payload = write_graph_sidecar_from_artifacts(settings)

            self.assertEqual(settings.graph_sidecar_path, output_path)
            full_payload = json.loads(settings.graph_sidecar_path.read_text(encoding="utf-8"))
            compact_payload = json.loads(settings.graph_sidecar_compact_path.read_text(encoding="utf-8"))
            self.assertEqual("graph_sidecar_v1", full_payload["schema_version"])
            self.assertEqual("graph_sidecar_compact_v1", compact_payload["schema_version"])
            self.assertEqual(1, full_payload["book_count"])
            self.assertEqual(2, full_payload["chunk_count"])
            self.assertEqual(payload["relation_count"], full_payload["relation_count"])
            self.assertEqual(1, compact_payload["book_count"])
            relation_groups = full_payload["chunks"][0]["relation_groups"]
            self.assertIn("shared_k8s_objects", relation_groups)
            self.assertEqual(
                {"related_book_count", "related_book_slugs", "related_chunk_count", "value"},
                set(relation_groups["shared_k8s_objects"][0].keys()),
            )

    def test_write_graph_sidecar_from_artifacts_preserves_existing_file_when_streaming_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = load_settings(root)
            _write_jsonl(
                settings.playbook_documents_path,
                [
                    {
                        "book_slug": "architecture",
                        "title": "아키텍처",
                        "source_metadata": {"source_type": "official_doc"},
                    }
                ],
            )
            _write_jsonl(
                settings.chunks_path,
                [
                    {
                        "chunk_id": "architecture:intro",
                        "book_slug": "architecture",
                        "book_title": "아키텍처",
                        "chapter": "1",
                        "section": "개요",
                        "anchor": "intro",
                        "viewer_path": "/docs/ocp/4.20/ko/architecture/index.html#intro",
                        "source_url": "https://docs.example/architecture",
                        "text": "아키텍처 개요",
                        "token_count": 3,
                        "ordinal": 1,
                        "source_type": "official_doc",
                    }
                ],
            )
            existing_payload = {"schema_version": "graph_sidecar_v1", "book_count": 7, "relation_count": 3}
            settings.graph_sidecar_path.parent.mkdir(parents=True, exist_ok=True)
            settings.graph_sidecar_path.write_text(json.dumps(existing_payload, ensure_ascii=False), encoding="utf-8")

            with patch(
                "play_book_studio.ingestion.graph_sidecar._stream_full_graph_sidecar_payload",
                side_effect=RuntimeError("stream failed"),
            ):
                with self.assertRaisesRegex(RuntimeError, "stream failed"):
                    write_graph_sidecar_from_artifacts(settings)

            self.assertEqual(
                existing_payload,
                json.loads(settings.graph_sidecar_path.read_text(encoding="utf-8")),
            )

    def test_refresh_full_sidecar_degrades_when_neo4j_export_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            settings = load_settings(root)

            settings.graph_sidecar_path.parent.mkdir(parents=True, exist_ok=True)
            settings.graph_sidecar_compact_path.parent.mkdir(parents=True, exist_ok=True)
            settings.graph_sidecar_path.write_text(
                json.dumps(
                    {
                        "schema_version": "graph_sidecar_v1",
                        "book_count": 2,
                        "relation_count": 1,
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            settings.graph_sidecar_compact_path.write_text(
                json.dumps(
                    {
                        "schema_version": "graph_sidecar_compact_v1",
                        "book_count": 2,
                        "relation_count": 1,
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            with patch(
                "play_book_studio.ingestion.graph_sidecar.write_graph_sidecar_from_artifacts",
                side_effect=RuntimeError("neo4j driver is not installed"),
            ):
                report = refresh_active_runtime_graph_artifacts(
                    settings,
                    refresh_full_sidecar=True,
                    allow_compact_degrade=True,
                )

            self.assertEqual("degraded", report["status"])
            self.assertEqual("full_sidecar_runtime_fallback", report["degrade_mode"])
            self.assertEqual("degraded", report["full_sidecar"]["status"])
            self.assertEqual(2, report["full_sidecar"]["book_count"])
            self.assertEqual(1, report["full_sidecar"]["relation_count"])
            self.assertIn("neo4j driver is not installed", report["full_sidecar"]["error"])


if __name__ == "__main__":
    unittest.main()
