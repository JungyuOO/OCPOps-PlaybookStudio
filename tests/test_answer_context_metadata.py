from __future__ import annotations

from play_book_studio.answering.context import assemble_context
from play_book_studio.retrieval.models import RetrievalHit


def test_assemble_context_preserves_section_metadata_on_citations() -> None:
    hit = RetrievalHit(
        chunk_id="chunk-1",
        book_slug="study-pods",
        chapter="Workloads",
        section="Pods",
        anchor="pods",
        source_url="corpus/sources/kmsc/raw/pod-guide.pdf",
        viewer_path="/uploads/documents/source-1/chunks/chunk-1",
        text="Use oc get pods to inspect pod status.",
        source="vector",
        raw_score=0.9,
        section_path=("Workloads", "Pods"),
        section_number="1.2",
        heading_title="Pods",
        source_anchor="pods",
        toc_path=("1 Workloads", "1.2 Pods"),
        asset_ids=("asset-a", "asset-b"),
        learning={
            "refs": {
                "next_refs": [
                    {"ref_type": "document", "book_slug": "deployments", "reason": "다음 학습 단계"}
                ]
            }
        },
    )

    bundle = assemble_context([hit], query="pod status", max_chunks=1)

    citation = bundle.citations[0]
    assert citation.section_number == "1.2"
    assert citation.heading_title == "Pods"
    assert citation.source_anchor == "pods"
    assert citation.toc_path == ("1 Workloads", "1.2 Pods")
    assert citation.asset_ids == ("asset-a", "asset-b")
    assert citation.learning["refs"]["next_refs"][0]["book_slug"] == "deployments"
    assert "learning_next_refs:" in bundle.prompt_context
    assert "- deployments: 다음 학습 단계" in bundle.prompt_context
    assert citation.to_dict()["toc_path"] == ("1 Workloads", "1.2 Pods")
    assert citation.to_dict()["asset_id"] == "asset-a"


def test_assemble_context_strips_internal_code_markup_from_citations() -> None:
    hit = RetrievalHit(
        chunk_id="chunk-code",
        book_slug="cli-tools",
        chapter="CLI",
        section="2.6.1.78. oc get",
        anchor="oc-get",
        source_url="https://example.test/cli",
        viewer_path="/docs/cli",
        text='Before running it. [CODE language="shell-session"] $ oc get pods -n demo [/CODE] Then inspect status.',
        source="vector",
        raw_score=1.0,
        cli_commands=('[CODE] oc get pods -n demo [/CODE]',),
    )

    bundle = assemble_context([hit], query="pod 확인 명령어", max_chunks=1)
    citation = bundle.citations[0]

    assert "[CODE" not in citation.excerpt
    assert "[/CODE]" not in citation.excerpt
    assert citation.cli_commands == ("oc get pods -n demo",)
    assert citation.section == "oc get"


def test_assemble_context_drops_polluted_unrelated_cli_commands() -> None:
    hit = RetrievalHit(
        chunk_id="chunk-pvc",
        book_slug="storage",
        chapter="Storage",
        section="PVC Pending",
        anchor="pvc-pending",
        source_url="https://example.test/storage",
        viewer_path="/docs/storage",
        text=(
            "PVC가 Pending 상태인지 확인합니다.\n\n"
            "```shell\n$ oc get pvc -n <namespace>\n```\n\n"
            "출력 예\nNAME STATUS VOLUME\nclaim Bound pvc-123"
        ),
        source="vector",
        raw_score=1.0,
        cli_commands=(
            "oc\n[/CODE]",
            "oc create -f <file_name> -n <application_namespace>",
            "oc get pvc -n <namespace>",
        ),
    )

    bundle = assemble_context([hit], query="PVC가 Pending인데 뭐 확인해야 해?", max_chunks=1)
    citation = bundle.citations[0]

    assert citation.cli_commands == ("oc get pvc -n <namespace>",)
    assert "oc create -f" not in bundle.prompt_context
    assert "\noc\n" not in bundle.prompt_context


def test_assemble_context_trims_command_output_examples() -> None:
    hit = RetrievalHit(
        chunk_id="chunk-pvc-output",
        book_slug="storage",
        chapter="Storage",
        section="PVC Pending",
        anchor="pvc-pending",
        source_url="https://example.test/storage",
        viewer_path="/docs/storage",
        text=(
            "PVC 상태는 다음 명령으로 확인합니다.\n"
            "[CODE]oc get pvc -n <namespace>[/CODE]\n"
            "출력 예\n"
            "NAME STATUS VOLUME CAPACITY ACCESS MODES STORAGECLASS AGE\n"
            "data Pending"
        ),
        source="vector",
        raw_score=1.0,
    )

    bundle = assemble_context([hit], query="PVC가 Pending인데 뭐 확인해야 해?", max_chunks=1)
    citation = bundle.citations[0]

    assert citation.cli_commands == ("oc get pvc -n <namespace>",)
    assert "oc get pvc -n <namespace> 출력 예" not in bundle.prompt_context


def test_assemble_context_demotes_navigation_only_hits() -> None:
    nav_hit = RetrievalHit(
        chunk_id="chunk-nav",
        book_slug="installing_on_any_platform",
        chapter="Install",
        section="Waiting",
        anchor="waiting",
        source_url="https://example.test/nav",
        viewer_path="/docs/nav",
        text="관련 문서\nOpen document\nClose\n다음 문서",
        source="vector",
        raw_score=1.0,
    )
    content_hit = RetrievalHit(
        chunk_id="chunk-content",
        book_slug="installing_on_any_platform",
        chapter="Install",
        section="Bootstrap",
        anchor="bootstrap",
        source_url="https://example.test/bootstrap",
        viewer_path="/docs/bootstrap",
        text="Bootstrap이 완료될 때까지 openshift-install wait-for bootstrap-complete 명령으로 상태를 확인한다.",
        source="vector",
        raw_score=0.8,
    )

    bundle = assemble_context([nav_hit, content_hit], query="bootstrap 상태 확인", max_chunks=1)

    assert bundle.citations[0].chunk_id == "chunk-content"
