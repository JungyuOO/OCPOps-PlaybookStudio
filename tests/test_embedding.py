from __future__ import annotations

from pathlib import Path

from play_book_studio.config.settings import Settings, load_settings
from play_book_studio.ingestion import embedding
from play_book_studio.ingestion.embedding import EmbeddingClient


def test_load_settings_defaults_embedding_ssl_verify_off_for_http_endpoint(tmp_path: Path):
    (tmp_path / ".env").write_text("EMBEDDING_BASE_URL=http://tei.example.test/v1\n", encoding="utf-8")

    settings = load_settings(tmp_path)

    assert settings.embedding_verify_ssl is False


def test_embedding_client_passes_ssl_verify_setting(monkeypatch):
    calls = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"embedding": [0.1, 0.2]}]}

    def fake_post(url, **kwargs):
        calls["url"] = url
        calls["kwargs"] = kwargs
        return FakeResponse()

    monkeypatch.setattr(embedding.requests, "post", fake_post)
    client = EmbeddingClient(
        Settings(
            root_dir=Path("."),
            embedding_base_url="https://tei.example.test/v1",
            embedding_model="dragonkue/bge-m3-ko",
            embedding_verify_ssl=False,
        )
    )

    assert client.embed_texts(["test"]) == [[0.1, 0.2]]
    assert calls["url"] == "https://tei.example.test/v1/embeddings"
    assert calls["kwargs"]["verify"] is False
