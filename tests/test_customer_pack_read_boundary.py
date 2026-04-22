from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests
from http.server import ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from play_book_studio.answering.models import AnswerResult, Citation
from play_book_studio.app.customer_pack_read_boundary import (
    LOCAL_CUSTOMER_PACK_TENANT_ID,
    LOCAL_CUSTOMER_PACK_WORKSPACE_ID,
    load_customer_pack_read_boundary,
)
from play_book_studio.app.chat_debug import append_chat_turn_log
from play_book_studio.app.server import _build_handler
from play_book_studio.app.sessions import ChatSession, SessionStore, Turn
from play_book_studio.config.settings import load_settings
from play_book_studio.intake import CustomerPackDraftStore
from play_book_studio.intake.private_corpus import customer_pack_private_manifest_path
from play_book_studio.app.intake_api import ingest_customer_pack
from play_book_studio.retrieval.models import SessionContext


class _FakeTokenizer:
    model_max_length = 1024

    def __call__(self, text: str, **kwargs):
        del kwargs
        token_count = max(len(str(text).split()), 1)
        return {"input_ids": list(range(token_count))}


class _FakeVectorRow:
    def __init__(self, values: list[float]) -> None:
        self._values = values

    def tolist(self) -> list[float]:
        return list(self._values)


class _FakeChunkingModel:
    tokenizer = _FakeTokenizer()


class _FakeEmbeddingModel:
    def encode(self, texts, **kwargs):
        del kwargs
        return [_FakeVectorRow([1.0, 0.0, 0.0]) for _ in texts]


class _FakeLlmClient:
    def runtime_metadata(self) -> dict[str, object]:
        return {
            "preferred_provider": "deterministic-test",
            "fallback_enabled": False,
            "last_provider": "deterministic-test",
            "last_fallback_used": False,
            "last_attempted_providers": ["deterministic-test"],
        }


class _FakeAnswerer:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.llm_client = _FakeLlmClient()
        self.retriever = SimpleNamespace(reranker=None)

    @classmethod
    def from_settings(cls, settings):
        return cls(settings)


@contextmanager
def _test_server(root: Path):
    settings = load_settings(root)
    answerer = _FakeAnswerer(settings)
    store = SessionStore(root)
    handler = _build_handler(answerer=answerer, store=store, root_dir=root)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", store, answerer
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _ingest_pack(
    root: Path,
    *,
    draft_tag: str,
    tenant_id: str | None,
    workspace_id: str | None,
    approval_state: str,
    publication_state: str = "draft",
) -> dict[str, object]:
    source_md = root / f"{draft_tag}.md"
    source_md.write_text(
        (
            f"# {draft_tag}\n\n"
            "## ConfigMap Secret\n\n"
            f"{draft_tag} values must be synchronized before rollout.\n"
        ),
        encoding="utf-8",
    )
    payload: dict[str, object] = {
        "source_type": "md",
        "uri": str(source_md),
        "title": draft_tag,
        "approval_state": approval_state,
        "publication_state": publication_state,
    }
    if tenant_id is not None:
        payload["tenant_id"] = tenant_id
    if workspace_id is not None:
        payload["workspace_id"] = workspace_id
    with (
        patch(
            "play_book_studio.intake.private_corpus.load_sentence_model",
            return_value=_FakeEmbeddingModel(),
        ),
        patch(
            "play_book_studio.ingestion.chunking.load_sentence_model",
            return_value=_FakeChunkingModel(),
        ),
    ):
        return ingest_customer_pack(root, payload)


def _private_citation_payload(draft_id: str) -> dict[str, object]:
    return {
        "index": 1,
        "book_slug": "private-config",
        "book_title": "Customer Source-First Pack",
        "section": "ConfigMap Secret",
        "viewer_path": f"/playbooks/customer-packs/{draft_id}/index.html#configmap-secret",
        "source_url": f"/api/customer-packs/captured?draft_id={draft_id}",
        "source_label": "Customer Source-First Pack",
        "source_collection": "uploaded",
        "source_lane": "customer_source_first_pack",
        "approval_state": "draft",
        "publication_state": "draft",
        "boundary_truth": "private_customer_pack_runtime",
        "runtime_truth_label": "Customer Source-First Pack",
        "boundary_badge": "Private Pack Runtime",
    }


def _mark_pack_needs_review(root: Path, draft_id: str) -> None:
    store = CustomerPackDraftStore(root)
    record = store.get(draft_id)
    assert record is not None
    record.approval_state = "needs_review"
    store.save(record)


def _persist_private_session(
    *,
    root: Path,
    store: SessionStore,
    answerer: _FakeAnswerer,
    session_id: str,
    draft_id: str,
    approval_state: str,
) -> None:
    citation = Citation(
        index=1,
        chunk_id=f"{draft_id}:configmap-secret",
        book_slug="private-config",
        section="ConfigMap Secret",
        anchor="configmap-secret",
        source_url=f"/api/customer-packs/captured?draft_id={draft_id}",
        viewer_path=f"/playbooks/customer-packs/{draft_id}/index.html#configmap-secret",
        excerpt="ConfigMap Secret values must be synchronized before rollout.",
        source_collection="uploaded",
    )
    context = SessionContext(
        mode="chat",
        ocp_version=load_settings(root).ocp_version,
        selected_draft_ids=[draft_id],
        restrict_uploaded_sources=True,
    )
    turn = Turn(
        query="ConfigMap Secret 설명",
        mode="chat",
        answer="답변",
        rewritten_query="ConfigMap Secret 설명",
        response_kind="rag",
        citations=[_private_citation_payload(draft_id)],
        related_links=[],
        related_sections=[],
        warnings=[],
        stages=[],
        diagnosis={},
        primary_source_lane="customer_source_first_pack",
        primary_boundary_truth="private_customer_pack_runtime",
        primary_runtime_truth_label="Customer Source-First Pack",
        primary_boundary_badge="Private Pack Runtime",
        primary_publication_state="draft",
        primary_approval_state=approval_state,
        turn_id=f"turn-{session_id}",
        created_at="2026-04-18T12:00:00",
    )
    session = ChatSession(
        session_id=session_id,
        mode="chat",
        context=context,
        history=[turn],
        revision=1,
        updated_at="2026-04-18T12:00:00",
    )
    store.persist(session)
    result = AnswerResult(
        query="ConfigMap Secret 설명",
        mode="chat",
        answer="답변",
        rewritten_query="ConfigMap Secret 설명",
        citations=[citation],
        response_kind="rag",
        cited_indices=[1],
        warnings=[],
        retrieval_trace={"route": "customer-pack-test"},
        pipeline_trace={"mode": "customer-pack-test"},
    )
    append_chat_turn_log(
        root,
        answerer=answerer,
        session=session,
        query="ConfigMap Secret 설명",
        result=result,
        context_before=context,
        context_after=context,
    )


class CustomerPackReadBoundaryTests(unittest.TestCase):
    def test_customer_pack_read_surfaces_auto_repair_local_uploads_and_fail_close_non_read_ready_packs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            approved = _ingest_pack(
                root,
                draft_tag="approved",
                tenant_id="tenant-a",
                workspace_id="workspace-a",
                approval_state="approved",
            )
            unreviewed = _ingest_pack(
                root,
                draft_tag="unreviewed",
                tenant_id="tenant-b",
                workspace_id="workspace-b",
                approval_state="unreviewed",
            )
            placeholder = _ingest_pack(
                root,
                draft_tag="placeholder",
                tenant_id=None,
                workspace_id=None,
                approval_state="approved",
            )
            blocked = _ingest_pack(
                root,
                draft_tag="needs-review",
                tenant_id="tenant-c",
                workspace_id="workspace-c",
                approval_state="approved",
            )
            _mark_pack_needs_review(root, str(blocked["draft_id"]))

            approved_id = str(approved["draft_id"])
            unreviewed_id = str(unreviewed["draft_id"])
            placeholder_id = str(placeholder["draft_id"])
            blocked_id = str(blocked["draft_id"])

            with _test_server(root) as (base_url, _store, _answerer):
                for draft_id, expected_status in (
                    (approved_id, 200),
                    (unreviewed_id, 200),
                    (placeholder_id, 200),
                    (blocked_id, 404),
                ):
                    captured = requests.get(
                        f"{base_url}/api/customer-packs/captured",
                        params={"draft_id": draft_id},
                        timeout=10,
                    )
                    self.assertEqual(expected_status, captured.status_code)

                    book = requests.get(
                        f"{base_url}/api/customer-packs/book",
                        params={"draft_id": draft_id},
                        timeout=10,
                    )
                    self.assertEqual(expected_status, book.status_code)

                    draft = requests.get(
                        f"{base_url}/api/customer-packs/drafts",
                        params={"draft_id": draft_id},
                        timeout=10,
                    )
                    self.assertEqual(expected_status, draft.status_code)

                    viewer_document = requests.get(
                        f"{base_url}/api/viewer-document",
                        params={"viewer_path": f"/playbooks/customer-packs/{draft_id}/index.html"},
                        timeout=10,
                    )
                    self.assertEqual(expected_status, viewer_document.status_code)

                    source_meta = requests.get(
                        f"{base_url}/api/source-meta",
                        params={"viewer_path": f"/playbooks/customer-packs/{draft_id}/index.html"},
                        timeout=10,
                    )
                    self.assertEqual(expected_status, source_meta.status_code)

                drafts = requests.get(f"{base_url}/api/customer-packs/drafts", timeout=10)
                self.assertEqual(200, drafts.status_code)
                payload = drafts.json()
                self.assertEqual(3, payload["count"])
                self.assertEqual(
                    {approved_id, unreviewed_id, placeholder_id},
                    {item["draft_id"] for item in payload["drafts"]},
                )

            unreviewed_boundary = load_customer_pack_read_boundary(root, unreviewed_id)
            self.assertTrue(unreviewed_boundary["read_allowed"])
            self.assertEqual("approved", unreviewed_boundary["approval_state"])

            placeholder_boundary = load_customer_pack_read_boundary(root, placeholder_id)
            self.assertTrue(placeholder_boundary["read_allowed"])
            self.assertEqual(LOCAL_CUSTOMER_PACK_TENANT_ID, placeholder_boundary["tenant_id"])
            self.assertEqual(LOCAL_CUSTOMER_PACK_WORKSPACE_ID, placeholder_boundary["workspace_id"])
            self.assertEqual("approved", placeholder_boundary["approval_state"])

            blocked_boundary = load_customer_pack_read_boundary(root, blocked_id)
            self.assertFalse(blocked_boundary["read_allowed"])
            self.assertIn("approval_not_read_ready:needs_review", blocked_boundary["fail_reasons"])

    def test_customer_pack_read_surface_sanitizes_public_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            approved = _ingest_pack(
                root,
                draft_tag="approved",
                tenant_id="tenant-a",
                workspace_id="workspace-a",
                approval_state="approved",
            )
            draft_id = str(approved["draft_id"])

            manifest_path = customer_pack_private_manifest_path(load_settings(root), draft_id)
            self.assertTrue(manifest_path.exists())

            with _test_server(root) as (base_url, _store, _answerer):
                draft_response = requests.get(
                    f"{base_url}/api/customer-packs/drafts",
                    params={"draft_id": draft_id},
                    timeout=10,
                )
                self.assertEqual(200, draft_response.status_code)
                draft_payload = draft_response.json()
                self.assertEqual(
                    f"/api/customer-packs/captured?draft_id={draft_id}",
                    draft_payload["capture_artifact_path"],
                )
                self.assertNotIn("uploaded_file_path", draft_payload)
                self.assertNotIn("canonical_book_path", draft_payload)
                self.assertNotIn("private_corpus_manifest_path", draft_payload)
                self.assertNotIn("source_fingerprint", draft_payload)
                self.assertNotIn("parser_route", draft_payload)
                self.assertNotIn("parser_version", draft_payload)
                self.assertNotIn("degraded_pdf", draft_payload)
                self.assertNotIn("degraded_reason", draft_payload)
                self.assertNotIn("fallback_backend", draft_payload)
                self.assertNotIn("fallback_status", draft_payload)
                self.assertNotIn("fallback_reason", draft_payload)
                self.assertNotIn("quality_score", draft_payload)
                self.assertNotIn("quality_flags", draft_payload)

                book_response = requests.get(
                    f"{base_url}/api/customer-packs/book",
                    params={"draft_id": draft_id},
                    timeout=10,
                )
                self.assertEqual(200, book_response.status_code)
                book_payload = book_response.json()
                self.assertEqual(
                    f"/api/customer-packs/captured?draft_id={draft_id}",
                    book_payload["source_uri"],
                )
                self.assertNotIn("customer_pack_evidence", book_payload)
                self.assertNotIn("degraded_pdf", book_payload)
                self.assertNotIn("degraded_reason", book_payload)
                self.assertNotIn("fallback_backend", book_payload)
                self.assertNotIn("fallback_status", book_payload)
                self.assertNotIn("fallback_reason", book_payload)
                self.assertNotIn("quality_score", book_payload)
                self.assertTrue(
                    all(
                        section["source_url"] == f"/api/customer-packs/captured?draft_id={draft_id}"
                        for section in book_payload["sections"]
                    )
                )

                source_meta = requests.get(
                    f"{base_url}/api/source-meta",
                    params={"viewer_path": f"/playbooks/customer-packs/{draft_id}/index.html"},
                    timeout=10,
                )
                self.assertEqual(200, source_meta.status_code)
                source_meta_payload = source_meta.json()
                self.assertNotIn("quality_score", source_meta_payload)
                self.assertNotIn("degraded_reason", source_meta_payload)
                self.assertNotIn("fallback_reason", source_meta_payload)
                self.assertIn("parser_backend", source_meta_payload)
                self.assertIn("quality_status", source_meta_payload)

    def test_sessions_and_debug_surfaces_fail_close_for_blocked_private_drafts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            approved = _ingest_pack(
                root,
                draft_tag="approved",
                tenant_id="tenant-a",
                workspace_id="workspace-a",
                approval_state="approved",
            )
            unreviewed = _ingest_pack(
                root,
                draft_tag="unreviewed",
                tenant_id="tenant-b",
                workspace_id="workspace-b",
                approval_state="unreviewed",
            )
            placeholder = _ingest_pack(
                root,
                draft_tag="placeholder",
                tenant_id=None,
                workspace_id=None,
                approval_state="approved",
            )
            blocked = _ingest_pack(
                root,
                draft_tag="needs-review",
                tenant_id="tenant-c",
                workspace_id="workspace-c",
                approval_state="approved",
            )
            _mark_pack_needs_review(root, str(blocked["draft_id"]))
            approved_id = str(approved["draft_id"])
            unreviewed_id = str(unreviewed["draft_id"])
            placeholder_id = str(placeholder["draft_id"])
            blocked_id = str(blocked["draft_id"])

            with _test_server(root) as (base_url, store, answerer):
                _persist_private_session(
                    root=root,
                    store=store,
                    answerer=answerer,
                    session_id="session-approved",
                    draft_id=approved_id,
                    approval_state="approved",
                )
                _persist_private_session(
                    root=root,
                    store=store,
                    answerer=answerer,
                    session_id="session-unreviewed",
                    draft_id=unreviewed_id,
                    approval_state="unreviewed",
                )
                _persist_private_session(
                    root=root,
                    store=store,
                    answerer=answerer,
                    session_id="session-placeholder",
                    draft_id=placeholder_id,
                    approval_state="approved",
                )
                _persist_private_session(
                    root=root,
                    store=store,
                    answerer=answerer,
                    session_id="session-blocked",
                    draft_id=blocked_id,
                    approval_state="needs_review",
                )

                for session_id, expected_status in (
                    ("session-approved", 200),
                    ("session-unreviewed", 200),
                    ("session-placeholder", 200),
                    ("session-blocked", 404),
                ):
                    session_payload = requests.get(
                        f"{base_url}/api/sessions/load",
                        params={"session_id": session_id},
                        timeout=10,
                    )
                    self.assertEqual(expected_status, session_payload.status_code)

                    debug_payload = requests.get(
                        f"{base_url}/api/debug/session",
                        params={"session_id": session_id},
                        timeout=10,
                    )
                    self.assertEqual(expected_status, debug_payload.status_code)

                chat_log_payload = requests.get(
                    f"{base_url}/api/debug/chat-log",
                    params={"limit": 20},
                    timeout=10,
                )
                self.assertEqual(200, chat_log_payload.status_code)
                debug_log = chat_log_payload.json()
                self.assertNotIn("path", debug_log)
                self.assertEqual(3, debug_log["count"])
                self.assertEqual(
                    {"session-approved", "session-unreviewed", "session-placeholder"},
                    {entry["session_id"] for entry in debug_log["entries"]},
                )
                for entry in debug_log["entries"]:
                    self.assertNotIn("snapshot_path", entry["audit_envelope"])
                    self.assertNotIn("recent_session_path", entry["audit_envelope"])
                    runtime_payload = entry.get("runtime") or {}
                    self.assertNotIn("artifacts_dir", runtime_payload)
                    self.assertNotIn("source_manifest_path", runtime_payload)
                    self.assertNotIn("customer_pack_books_dir", runtime_payload)


if __name__ == "__main__":
    unittest.main()
