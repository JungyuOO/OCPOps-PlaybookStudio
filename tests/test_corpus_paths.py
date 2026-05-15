from __future__ import annotations

from play_book_studio.config.corpus_paths import (
    official_gold_chunks_candidates,
    official_manualbook_playbook_dir_candidates,
    resolve_official_gold_chunks_path,
    resolve_official_manualbook_documents_path,
    resolve_official_manualbook_playbooks_dir,
    resolve_official_manualbook_root_dir,
)


def test_official_resolvers_prefer_consolidated_corpus_seed_paths(tmp_path) -> None:
    modern_chunks = tmp_path / "corpus" / "sources" / "official" / "imported-gold" / "gold_corpus_ko" / "chunks.jsonl"
    legacy_chunks = tmp_path / "data" / "gold_corpus_ko" / "chunks.jsonl"
    modern_chunks.parent.mkdir(parents=True)
    legacy_chunks.parent.mkdir(parents=True)
    modern_chunks.write_text("{}", encoding="utf-8")
    legacy_chunks.write_text("{}", encoding="utf-8")

    modern_docs = tmp_path / "corpus" / "sources" / "official" / "imported-gold" / "gold_manualbook_ko" / "playbook_documents.jsonl"
    modern_playbooks = tmp_path / "corpus" / "sources" / "official" / "imported-gold" / "gold_manualbook_ko" / "playbooks"
    legacy_playbooks = tmp_path / "data" / "gold_manualbook_ko" / "playbooks"
    modern_docs.parent.mkdir(parents=True, exist_ok=True)
    modern_playbooks.mkdir(parents=True)
    legacy_playbooks.mkdir(parents=True)
    modern_docs.write_text("{}", encoding="utf-8")
    (modern_playbooks / "architecture.json").write_text("{}", encoding="utf-8")
    (legacy_playbooks / "legacy.json").write_text("{}", encoding="utf-8")

    assert resolve_official_gold_chunks_path(tmp_path) == modern_chunks.resolve()
    assert resolve_official_manualbook_documents_path(tmp_path) == modern_docs.resolve()
    assert resolve_official_manualbook_playbooks_dir(tmp_path) == modern_playbooks.resolve()
    assert resolve_official_manualbook_root_dir(tmp_path) == modern_playbooks.parent.resolve()


def test_official_resolvers_keep_legacy_data_fallback(tmp_path) -> None:
    legacy_chunks = tmp_path / "data" / "gold_corpus_ko" / "chunks.jsonl"
    legacy_docs = tmp_path / "data" / "gold_manualbook_ko" / "playbook_documents.jsonl"
    legacy_playbooks = tmp_path / "data" / "gold_manualbook_ko" / "playbooks"
    legacy_chunks.parent.mkdir(parents=True)
    legacy_docs.parent.mkdir(parents=True)
    legacy_playbooks.mkdir(parents=True)
    legacy_chunks.write_text("{}", encoding="utf-8")
    legacy_docs.write_text("{}", encoding="utf-8")
    (legacy_playbooks / "architecture.json").write_text("{}", encoding="utf-8")

    assert resolve_official_gold_chunks_path(tmp_path) == legacy_chunks.resolve()
    assert resolve_official_manualbook_documents_path(tmp_path) == legacy_docs.resolve()
    assert resolve_official_manualbook_playbooks_dir(tmp_path) == legacy_playbooks.resolve()

    chunk_candidates = official_gold_chunks_candidates(tmp_path)
    playbook_candidates = official_manualbook_playbook_dir_candidates(tmp_path)

    assert chunk_candidates[0] == (
        tmp_path / "corpus" / "sources" / "official" / "imported-gold" / "gold_corpus_ko" / "chunks.jsonl"
    ).resolve()
    assert chunk_candidates[-1] == legacy_chunks.resolve()
    assert playbook_candidates[0] == (
        tmp_path / "corpus" / "sources" / "official" / "imported-gold" / "gold_manualbook_ko" / "playbooks"
    ).resolve()
    assert playbook_candidates[-1] == legacy_playbooks.resolve()
