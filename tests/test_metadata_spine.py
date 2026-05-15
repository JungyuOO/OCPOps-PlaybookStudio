from play_book_studio.document_quality import build_document_quality_snapshot
from play_book_studio.db.metadata_spine_backfill import backfill_metadata_spine
from play_book_studio.ingestion.metadata_spine import build_chunk_metadata_spine


def test_metadata_spine_extracts_ocp_operational_signals() -> None:
    text = """
    ## SCC와 RBAC 확인

    ```yaml
    kind: SecurityContextConstraints
    metadata:
      name: restricted-v2
    ```

    oc adm policy add-scc-to-user restricted-v2 -z builder -n demo
    kubectl get rolebinding -n demo
    """

    metadata = build_chunk_metadata_spine(
        text,
        section_path=("Security", "SCC와 RBAC 확인"),
        filename="06.-ImageStream-03.20.pdf",
        source_scope="user_upload",
    )

    assert metadata["topic"] == "security"
    assert metadata["metadata_confidence"] in {"medium", "high"}
    assert "SecurityContextConstraints" in metadata["k8s_objects"]
    assert "SCC" in metadata["k8s_objects"]
    assert any(command.startswith("oc adm policy") for command in metadata["cli_commands"])
    assert metadata["answerable_questions"]


def test_metadata_spine_does_not_treat_newline_after_oc_as_command() -> None:
    metadata = build_chunk_metadata_spine(
        "oc\n[/CODE]\n\noc get pods -n demo",
        section_path=("Diagnostics",),
        filename="networking.md",
        source_scope="official_docs",
    )

    assert "oc\n[/CODE]" not in metadata["cli_commands"]
    assert metadata["cli_commands"] == ["oc get pods -n demo"]


def test_document_quality_blocks_gold_when_answerability_metadata_is_missing() -> None:
    quality = build_document_quality_snapshot(
        {
            "document_source_id": "source-1",
            "parsed_document_id": "parsed-1",
            "source_scope": "user_upload",
            "chunks": [
                {
                    "chunk_id": "chunk-1",
                    "markdown": "일반 텍스트",
                    "metadata": {"metadata_confidence": "low", "semantic_role": "unknown"},
                    "asset_ids": [],
                }
            ],
            "assets": [],
        },
        topology={"state": "ready", "metadata": {"storage": "postgres"}},
        gold_build_run={"status": "gold"},
    )

    assert quality["state"] == "needs_repair"
    assert any(check["id"] == "answerability_metadata" for check in quality["blockers"])


def test_metadata_spine_backfill_reports_existing_chunk_updates() -> None:
    class FakeCursor:
        def __init__(self) -> None:
            self.rows = [
                (
                    "11111111-1111-1111-1111-111111111111",
                    "",
                    "oc get scc restricted-v2\nkind: SecurityContextConstraints\nmetadata:\n  name: restricted-v2",
                    ["SCC"],
                    "document",
                    {"semantic_role": "uploaded_document"},
                    "user_upload",
                    "SCC 확인",
                    "06.-ImageStream-03.20.pdf",
                )
            ]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def execute(self, *_args, **_kwargs) -> None:
            return None

        def fetchall(self):
            return self.rows

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    result = backfill_metadata_spine(FakeConnection(), dry_run=True, force=True)

    assert result["updated_count"] == 1
    assert result["updated_by_scope"] == {"user_upload": 1}
    assert result["examples"][0]["semantic_role"] == "config"
    assert "SCC" in result["examples"][0]["k8s_objects"]
