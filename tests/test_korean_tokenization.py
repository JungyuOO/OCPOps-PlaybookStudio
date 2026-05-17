from play_book_studio.retrieval.bm25 import BM25Index, tokenize_text


def test_korean_tokenizer_normalizes_particles_and_endings() -> None:
    assert "프로비저닝" in tokenize_text("프로비저닝에서는")
    assert "단계" in tokenize_text("단계는")


def test_bm25_matches_korean_terms_with_particles_and_endings() -> None:
    index = BM25Index.from_rows(
        [
            {
                "chunk_id": "storage-static",
                "book_slug": "storage",
                "text": "정적 프로비저닝에서는 PersistentVolume과 PersistentVolumeClaim을 확인합니다.",
            },
            {
                "chunk_id": "network-route",
                "book_slug": "networking",
                "text": "Route와 Service 연결을 확인합니다.",
            },
        ]
    )

    hits = index.search("프로비저닝 확인 단계", top_k=2)

    assert hits
    assert hits[0].chunk_id == "storage-static"
