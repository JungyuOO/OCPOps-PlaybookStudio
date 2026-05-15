from __future__ import annotations

from play_book_studio.retrieval.models import RetrievalHit
from play_book_studio.retrieval.topology_expansion import enrich_hits_from_topology_snapshots


def _hit(chunk_id: str, *, source_id: str = "11111111-1111-1111-1111-111111111111", score: float = 1.0) -> RetrievalHit:
    return RetrievalHit(
        chunk_id=chunk_id,
        book_slug="uploaded",
        chapter="",
        section="",
        anchor=chunk_id,
        source_url="",
        viewer_path=f"/docs/{chunk_id}",
        text="oc apply OpenShift route",
        source="test",
        raw_score=score,
        fused_score=score,
        document_source_id=source_id,
    )


def test_topology_expansion_annotates_real_hits_and_injects_reservoir_candidate() -> None:
    snapshot = {
        "document_source_id": "11111111-1111-1111-1111-111111111111",
        "nodes": [
            {"id": "node-route", "kind": "concept", "label": "Route"},
            {"id": "node-command", "kind": "command", "label": "oc apply -f route.yaml"},
        ],
        "edges": [
            {
                "id": "edge-seed",
                "source": "node-command",
                "target": "node-route",
                "relation": "CONFIGURES",
                "label": "명령어가 Route를 구성",
                "evidence": [{"chunk_id": "chunk-seed", "quote": "oc apply -f route.yaml"}],
            },
            {
                "id": "edge-related",
                "source": "node-route",
                "target": "node-command",
                "relation": "EXPLAINS",
                "label": "Route 절차 설명",
                "evidence": [{"chunk_id": "chunk-related", "quote": "Route 생성 절차"}],
            },
        ],
    }

    hits, trace = enrich_hits_from_topology_snapshots(
        "Route 생성",
        hits=[_hit("chunk-seed", score=1.0)],
        reservoir_hits=[_hit("chunk-seed", score=1.0), _hit("chunk-related", score=0.2)],
        snapshots=[snapshot],
    )

    assert trace["used"] is True
    assert trace["matched_hit_count"] >= 1
    assert trace["injected_hit_count"] == 1
    assert any(hit.chunk_id == "chunk-related" for hit in hits)
    seed = next(hit for hit in hits if hit.chunk_id == "chunk-seed")
    assert "edge-seed" in seed.topology_edge_ids
    assert "CONFIGURES" in seed.topology_relations
    related = next(hit for hit in hits if hit.chunk_id == "chunk-related")
    assert related.component_scores["topology_injected"] == 1.0


def test_topology_expansion_does_not_attach_unrelated_edge_on_query_match_only() -> None:
    snapshot = {
        "document_source_id": "11111111-1111-1111-1111-111111111111",
        "nodes": [
            {"id": "node-route", "kind": "concept", "label": "Route"},
            {"id": "node-command", "kind": "command", "label": "oc apply"},
        ],
        "edges": [
            {
                "id": "edge-other-chunk",
                "source": "node-command",
                "target": "node-route",
                "relation": "CONFIGURES",
                "evidence": [{"chunk_id": "chunk-other", "quote": "oc apply"}],
            },
        ],
    }

    hits, trace = enrich_hits_from_topology_snapshots(
        "Route",
        hits=[_hit("chunk-seed", score=1.0)],
        reservoir_hits=[_hit("chunk-other", score=0.2)],
        snapshots=[snapshot],
    )

    seed = next(hit for hit in hits if hit.chunk_id == "chunk-seed")
    assert seed.topology_edge_ids == ()
    assert trace["matched_hit_count"] == 0
