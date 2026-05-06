from __future__ import annotations

from pathlib import Path

from play_book_studio.ingestion import corpus_import
from play_book_studio.ingestion.corpus_import import (
    build_corpus_import_plan,
    corpus_import_profile,
    import_corpus_documents,
    iter_corpus_source_files,
)

TEST_TMP = Path(__file__).resolve().parents[1] / "tmp" / "corpus_import_tests"


class FakeTransaction:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def transaction(self):
        return FakeTransaction()


class Stored:
    repository_id = "repo-id"
    document_source_id = "source-id"
    asset_ids = ()
    chunk_ids = ("chunk-1",)


def _case_dir(name: str) -> Path:
    path = TEST_TMP / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_corpus_import_profiles_lock_shared_scopes():
    official = corpus_import_profile("official_docs")
    study = corpus_import_profile("study_docs")

    assert official.repository_kind == "official"
    assert official.visibility == "global_shared"
    assert official.source_scope == "official_docs"
    assert study.repository_kind == "study"
    assert study.visibility == "workspace_shared"
    assert study.source_scope == "study_docs"


def test_iter_corpus_source_files_keeps_supported_documents_only():
    source_dir = _case_dir("supported")
    (source_dir / "guide.md").write_text("# Guide", encoding="utf-8")
    (source_dir / "deck.pptx").write_bytes(b"not-a-real-pptx")
    (source_dir / "ignore.tmp").write_text("skip", encoding="utf-8")
    (source_dir / "~$lock.docx").write_bytes(b"skip")

    files = iter_corpus_source_files(source_dir)

    assert [path.name for path in files] == ["deck.pptx", "guide.md"]


def test_build_corpus_import_plan_reports_repository_scope():
    source_dir = _case_dir("plan")
    (source_dir / "ops.md").write_text("# Ops\n\nCheck status.", encoding="utf-8")

    plan = build_corpus_import_plan(source_dir, corpus_kind="study_docs")

    assert plan["repository_slug"] == "study-docs"
    assert plan["repository_kind"] == "study"
    assert plan["visibility"] == "workspace_shared"
    assert plan["source_scope"] == "study_docs"
    assert plan["file_count"] == 1
    assert plan["files"][0]["relative_path"] == "ops.md"


def test_import_corpus_documents_persists_shared_scope(monkeypatch):
    source_dir = _case_dir("import")
    source = source_dir / "official.md"
    source.write_text("# Official\n\nSupported install flow.", encoding="utf-8")
    calls = []

    def fake_persist(connection, parsed, chunks, **kwargs):
        calls.append((connection, parsed, chunks, kwargs))
        return Stored()

    monkeypatch.setattr(corpus_import, "persist_parsed_upload_document", fake_persist)

    result = import_corpus_documents(
        FakeConnection(),
        source_dir=source_dir,
        corpus_kind="official_docs",
        chunk_max_chars=200,
        chunk_overlap_blocks=0,
    )

    assert result["imported_count"] == 1
    assert result["failed_count"] == 0
    kwargs = calls[0][3]
    assert kwargs["repository_slug"] == "official-docs"
    assert kwargs["repository_kind"] == "official"
    assert kwargs["visibility"] == "global_shared"
    assert kwargs["source_scope"] == "official_docs"
    assert kwargs["storage_key"] == "corpus/official_docs/official.md"


def test_import_corpus_documents_preserves_section_metadata(monkeypatch):
    source_dir = _case_dir("section_metadata")
    source = source_dir / "study.md"
    source.write_text(
        "# 1 Install\n\nPrepare the cluster.\n\n## 1.1 Verify\n\nRun `oc get nodes`.",
        encoding="utf-8",
    )
    calls = []

    def fake_persist(connection, parsed, chunks, **kwargs):
        calls.append((connection, parsed, chunks, kwargs))
        return Stored()

    monkeypatch.setattr(corpus_import, "persist_parsed_upload_document", fake_persist)

    result = import_corpus_documents(
        FakeConnection(),
        source_dir=source_dir,
        corpus_kind="study_docs",
        chunk_max_chars=200,
        chunk_overlap_blocks=0,
    )

    assert result["imported_count"] == 1
    chunks = calls[0][2]
    verify_chunk = next(chunk for chunk in chunks if chunk.section_number == "1.1")
    assert verify_chunk.heading_title == "Verify"
    assert verify_chunk.source_anchor == "1.1-install-verify"
    assert verify_chunk.toc_path == ("1 Install", "1.1 Verify")


def test_import_corpus_documents_skips_exact_duplicate_sources(monkeypatch):
    source_dir = _case_dir("duplicates")
    (source_dir / "first.md").write_text("# Same\n\nBody.", encoding="utf-8")
    (source_dir / "second.md").write_text("# Same\n\nBody.", encoding="utf-8")
    calls = []

    def fake_persist(connection, parsed, chunks, **kwargs):
        calls.append((connection, parsed, chunks, kwargs))
        return Stored()

    monkeypatch.setattr(corpus_import, "persist_parsed_upload_document", fake_persist)

    result = import_corpus_documents(
        FakeConnection(),
        source_dir=source_dir,
        corpus_kind="study_docs",
        chunk_max_chars=200,
        chunk_overlap_blocks=0,
    )

    assert result["imported_count"] == 1
    assert result["skipped_count"] == 1
    assert result["failed_count"] == 0
    assert result["skipped"][0]["reason"] == "duplicate_sha256"
    assert result["skipped"][0]["duplicate_of"] == "first.md"
    assert len(calls) == 1
