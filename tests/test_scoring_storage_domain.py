from play_book_studio.retrieval.models import RetrievalHit, SessionContext
from play_book_studio.retrieval.scoring import fuse_ranked_hits


def _hit(
    *,
    chunk_id: str,
    book_slug: str,
    section: str,
    text: str,
    raw_score: float = 1.0,
) -> RetrievalHit:
    return RetrievalHit(
        chunk_id=chunk_id,
        book_slug=book_slug,
        chapter="",
        section=section,
        anchor="",
        source_url="",
        viewer_path=f"/docs/{book_slug}/{chunk_id}",
        text=text,
        source="vector",
        raw_score=raw_score,
    )


def test_static_provisioning_query_ranks_storage_above_unrelated_install_hit() -> None:
    unrelated = _hit(
        chunk_id="mhc",
        book_slug="machine_management",
        section="MachineHealthCheck 리소스 생성",
        text="베어 메탈의 MachineHealthCheck 리소스를 생성하고 상태를 확인합니다.",
    )
    storage = _hit(
        chunk_id="static-storage",
        book_slug="storage",
        section="정적 프로비저닝",
        text="정적 프로비저닝에서는 PersistentVolume과 PersistentVolumeClaim을 생성하고 PV와 PVC 바인딩을 확인합니다.",
    )

    ranked = fuse_ranked_hits(
        "정적 프로비저닝 기준으로 다음 확인 단계는 뭐야?",
        {"vector": [unrelated, storage]},
        context=SessionContext(),
        top_k=2,
    )

    assert ranked[0].chunk_id == "static-storage"
    assert "storage_static_provisioning_boost" in ranked[0].component_scores
    assert "domain_mismatch_penalty" in ranked[1].component_scores
