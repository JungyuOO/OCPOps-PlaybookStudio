from __future__ import annotations

from play_book_studio.db.document_repository import document_topology_input_fingerprint
from play_book_studio.wiki_topology import TOPOLOGY_SCHEMA_VERSION, build_document_topology


def test_document_topology_builds_source_grounded_nodes_and_edges() -> None:
    document = {
        "document_source_id": "source-1",
        "parsed_document_id": "parsed-1",
        "title": "YAML 기반 Pod 운영",
        "source_scope": "user_upload",
        "total_chunks": 1,
        "chunks": [
            {
                "chunk_id": "chunk-1",
                "ordinal": 1,
                "chunk_type": "document",
                "heading_title": "Pod YAML 생성",
                "markdown": """
## Pod YAML 생성

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: demo
```

```bash
oc apply -f pod.yaml
```
""",
                "text": "",
                "token_count": 42,
                "section_path": ["운영", "Pod YAML 생성"],
                "asset_ids": ["asset-1"],
                "page_start": 2,
            }
        ],
        "assets": [
            {
                "asset_id": "asset-1",
                "asset_type": "image",
                "mime_type": "image/png",
                "page_number": 2,
                "filename": "page-002.png",
                "qwen_description": "OpenShift 콘솔에서 Pod와 Service 토폴로지를 보여주는 이미지",
                "caption_text": "",
                "ocr_text": "",
                "storage_key": "uploads/assets/page-002.png",
            }
        ],
    }

    topology = build_document_topology(document).to_dict()

    assert topology["schema_version"] == TOPOLOGY_SCHEMA_VERSION
    assert topology["summary"]["state"] == "ready"
    assert topology["summary"]["asset_count"] == 1
    assert topology["summary"]["described_asset_count"] == 1
    assert topology["summary"]["command_count"] == 1
    labels = {node["label"] for node in topology["nodes"]}
    assert {"Pod", "YAML", "OpenShift", "Service"}.issubset(labels)
    assert any(node["kind"] == "command" and "oc apply -f pod.yaml" in node["label"] for node in topology["nodes"])
    assert any(edge["relation"] == "VISUALIZES" for edge in topology["edges"])
    assert all(edge["evidence"] for edge in topology["edges"])


def test_document_topology_input_fingerprint_tracks_partial_and_token_inputs() -> None:
    document = {
        "document_source_id": "source-1",
        "parsed_document_id": "parsed-1",
        "document_version_id": "version-1",
        "title": "운영 문서",
        "filename": "ops.md",
        "source_scope": "user_upload",
        "total_chunks": 1,
        "has_more": False,
        "chunks": [
            {
                "chunk_id": "chunk-1",
                "ordinal": 1,
                "chunk_type": "document",
                "heading_title": "개요",
                "markdown": "OpenShift Route",
                "text": "OpenShift Route",
                "token_count": 7,
                "section_path": ["개요"],
            }
        ],
        "assets": [],
    }

    base = document_topology_input_fingerprint(document)
    more_chunks = {**document, "total_chunks": 2, "has_more": True}
    token_changed = {
        **document,
        "chunks": [{**document["chunks"][0], "token_count": 8}],
    }

    assert document_topology_input_fingerprint(more_chunks) != base
    assert document_topology_input_fingerprint(token_changed) != base


def test_document_topology_flags_missing_image_descriptions() -> None:
    topology = build_document_topology(
        {
            "document_source_id": "source-1",
            "parsed_document_id": "parsed-1",
            "title": "이미지 설명 누락",
            "chunks": [
                {
                    "chunk_id": "chunk-1",
                    "heading_title": "개요",
                    "markdown": "OpenShift Route 설정",
                    "asset_ids": ["asset-1"],
                }
            ],
            "assets": [
                {
                    "asset_id": "asset-1",
                    "asset_type": "image",
                    "mime_type": "image/png",
                    "filename": "page-001.png",
                    "qwen_description": "",
                    "caption_text": "",
                    "ocr_text": "",
                }
            ],
        }
    ).to_dict()

    assert topology["summary"]["state"] == "needs_review"
    assert topology["summary"]["missing_asset_description_count"] == 1
    assert "이미지 1개에 설명 근거가 없습니다." in topology["summary"]["blockers"]
