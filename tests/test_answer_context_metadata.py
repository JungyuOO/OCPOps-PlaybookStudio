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
    )

    bundle = assemble_context([hit], query="pod status", max_chunks=1)

    citation = bundle.citations[0]
    assert citation.section_number == "1.2"
    assert citation.heading_title == "Pods"
    assert citation.source_anchor == "pods"
    assert citation.toc_path == ("1 Workloads", "1.2 Pods")
    assert citation.asset_ids == ("asset-a", "asset-b")
    assert citation.to_dict()["toc_path"] == ("1 Workloads", "1.2 Pods")
    assert citation.to_dict()["asset_id"] == "asset-a"
