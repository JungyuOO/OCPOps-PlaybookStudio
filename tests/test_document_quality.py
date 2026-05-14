from __future__ import annotations

from play_book_studio.document_quality import build_document_quality_snapshot


def _document(markdown: str, *, chunks: list[dict] | None = None) -> dict:
    return {
        "document_source_id": "11111111-1111-1111-1111-111111111111",
        "parsed_document_id": "22222222-2222-2222-2222-222222222222",
        "source_scope": "user_upload",
        "chunks": chunks or [
            {
                "chunk_id": "chunk-1",
                "markdown": markdown,
                "token_count": max(1, len(markdown.split())),
                "asset_ids": ["asset-1"],
            }
        ],
        "assets": [
            {
                "asset_id": "asset-1",
                "asset_type": "image",
                "qwen_description": "RBAC 다이어그램 설명",
            }
        ],
    }


def _ready_topology() -> dict:
    return {
        "state": "ready",
        "summary": {"state": "ready"},
        "metadata": {"storage": "postgres"},
    }


def test_quality_blocks_unfenced_commands_and_missing_topology() -> None:
    quality = build_document_quality_snapshot(
        _document("# RBAC\n\noc adm policy add-role-to-user edit user1\napiVersion: rbac.authorization.k8s.io/v1"),
        topology=None,
    )

    blocker_ids = {item["id"] for item in quality["blockers"]}
    assert quality["state"] == "needs_repair"
    assert "code_loss" in blocker_ids
    assert "topology_snapshot" in blocker_ids


def test_quality_detects_page_stub_and_split_text_artifacts() -> None:
    quality = build_document_quality_snapshot(
        _document(
            "",
            chunks=[
                {"chunk_id": "page-6", "markdown": "## Page 6", "token_count": 3, "asset_ids": []},
                {"chunk_id": "page-8", "markdown": "## Page 8", "token_count": 3, "asset_ids": []},
                {
                    "chunk_id": "body",
                    "markdown": "my-proje ct 오픈시 프트 비활 성화 테스 트 인 프라 프로젝 트",
                    "token_count": 10,
                    "asset_ids": ["asset-1"],
                },
            ],
        ),
        topology=_ready_topology(),
    )

    blocker_ids = {item["id"] for item in quality["blockers"]}
    assert quality["state"] == "needs_repair"
    assert "page_stub" in blocker_ids
    assert "split_text" in blocker_ids


def test_quality_blocks_single_page_stub() -> None:
    quality = build_document_quality_snapshot(
        _document(
            "",
            chunks=[
                {"chunk_id": "page-6", "markdown": "## Page 6", "token_count": 3, "asset_ids": []},
                {
                    "chunk_id": "body",
                    "markdown": "# 본문\n\n정상 본문입니다.",
                    "token_count": 5,
                    "asset_ids": ["asset-1"],
                },
            ],
        ),
        topology=_ready_topology(),
    )

    blocker_ids = {item["id"] for item in quality["blockers"]}
    assert quality["state"] == "needs_repair"
    assert "page_stub" in blocker_ids


def test_quality_allows_fenced_commands_with_ready_topology_and_asset_evidence() -> None:
    quality = build_document_quality_snapshot(
        _document("# 점검\n\n```bash\noc get pods -n openshift-authentication\n```"),
        topology=_ready_topology(),
    )

    assert quality["state"] == "gold_ready"
    assert quality["blockers"] == []


def test_quality_blocks_pdf_footer_noise_and_wrapped_commands() -> None:
    quality = build_document_quality_snapshot(
        _document(
            """# SCC

```bash
$ oc adm policy add-scc-to-user anyuid -z my-sa -n my-proje
```

SCC
2

ct
"""
        ),
        topology=_ready_topology(),
    )

    blocker_ids = {item["id"] for item in quality["blockers"]}
    assert quality["state"] == "needs_repair"
    assert "page_footer_noise" in blocker_ids
    assert "broken_wrapped_command" in blocker_ids


def test_quality_blocks_unfenced_scc_yaml_fields() -> None:
    quality = build_document_quality_snapshot(
        _document(
            """# SCC

allowHostDirVolumePlugin: false
allowHostNetwork: false
allowPrivilegedContainer: false
priority: 10
runAsUser:
  type: MustRunAsRange
"""
        ),
        topology=_ready_topology(),
    )

    blocker_ids = {item["id"] for item in quality["blockers"]}
    assert quality["state"] == "needs_repair"
    assert "code_loss" in blocker_ids


def test_quality_blocks_readability_artifacts_that_should_not_be_gold() -> None:
    quality = build_document_quality_snapshot(
        _document(
            """# SCC

SCC 는  OpenShift 에서  Pod 의  보안  컨텍스트를  제어합니다.
User IDUID 범위를 지정합니다.
구분 RBAC Role-Based Access Control) SCC Security Context Constraints)
"""
        ),
        topology=_ready_topology(),
    )

    blocker_ids = {item["id"] for item in quality["blockers"]}
    assert quality["state"] == "needs_repair"
    assert "readability_artifact" in blocker_ids


def test_quality_allows_clean_parenthetical_terms() -> None:
    quality = build_document_quality_snapshot(
        _document(
            """# SCC

RBAC (Role-Based Access Control)
SCC (Security Context Constraints)
컨테이너가 실행될 User ID(UID) 범위 지정
"""
        ),
        topology=_ready_topology(),
    )

    blocker_ids = {item["id"] for item in quality["blockers"]}
    assert "readability_artifact" not in blocker_ids
