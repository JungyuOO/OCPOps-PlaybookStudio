from __future__ import annotations

from play_book_studio.contextual_enrichment import (
    CONTEXTUAL_ENRICHMENT_VERSION,
    contextual_search_text,
    enrich_contextual_row,
    has_contextual_enrichment,
)
from play_book_studio.retrieval.bm25 import BM25Index


def test_contextual_enrichment_adds_parent_path_prefix() -> None:
    row = {
        "chunk_id": "chunk-1",
        "book_slug": "advanced_networking",
        "book_title": "고급 네트워킹",
        "chapter": "1장. 끝점에 대한 연결 확인",
        "section": "연결 확인 상태 점검",
        "section_path": ["1장. 끝점에 대한 연결 확인", "연결 확인 상태 점검"],
        "source_lane": "official_ko",
        "source_collection": "core",
        "source_type": "official_doc",
        "chunk_type": "concept",
        "operator_names": ["Cluster Network Operator"],
        "text": "CNO는 클러스터 내 리소스 간 연결 상태 검사를 수행합니다.",
    }

    enriched = enrich_contextual_row(row)

    assert enriched["contextual_enrichment_version"] == CONTEXTUAL_ENRICHMENT_VERSION
    assert enriched["contextual_parent_title"] == "고급 네트워킹"
    assert enriched["contextual_heading_path"] == ["1장. 끝점에 대한 연결 확인", "연결 확인 상태 점검"]
    assert "문서: 고급 네트워킹" in enriched["contextual_prefix"]
    assert "Operator: Cluster Network Operator" in enriched["contextual_prefix"]
    assert has_contextual_enrichment(enriched)
    assert contextual_search_text(enriched).startswith("문서: 고급 네트워킹")


def test_bm25_runtime_uses_contextual_heading_path_for_recall() -> None:
    rows = [
        {
            "chunk_id": "plain-registry",
            "book_slug": "registry",
            "book_title": "Registry",
            "chapter": "Registry options",
            "section": "Mirror settings",
            "section_path": ["Registry options", "Mirror settings"],
            "text": "Mirror registry settings are configured before cluster installation.",
        },
        {
            "chunk_id": "disconnected-install",
            "book_slug": "installing_on_any_platform",
            "book_title": "Installing on any platform",
            "chapter": "Disconnected installation",
            "section": "Mirroring images for disconnected clusters",
            "section_path": ["Disconnected installation", "Mirroring images for disconnected clusters"],
            "text": "Prepare release images and registry credentials before installation.",
        },
    ]

    hits = BM25Index.from_rows(rows).search("disconnected cluster image mirroring", top_k=2)

    assert hits
    assert hits[0].chunk_id == "disconnected-install"
    assert hits[0].contextual_enrichment_version == CONTEXTUAL_ENRICHMENT_VERSION
    assert hits[0].contextual_heading_path == (
        "Disconnected installation",
        "Mirroring images for disconnected clusters",
    )
