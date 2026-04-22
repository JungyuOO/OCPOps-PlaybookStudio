from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ["ARTIFACTS_DIR"] = "artifacts"

from play_book_studio.answering.models import AnswerResult, Citation
from play_book_studio.app.chat_debug import (
    append_chat_turn_log as _append_chat_turn_log,
    build_session_debug_payload as _build_session_debug_payload,
    build_turn_diagnosis as _build_turn_diagnosis,
    write_recent_chat_session_snapshot as _write_recent_chat_session_snapshot,
)
from play_book_studio.app.intake_api import (
    build_customer_pack_plan as _build_customer_pack_plan,
    build_customer_pack_support_matrix as _build_customer_pack_support_matrix,
    capture_customer_pack_draft as _capture_customer_pack_draft,
    create_customer_pack_draft as _create_customer_pack_draft,
    ingest_customer_pack as _ingest_customer_pack,
    load_customer_pack_capture as _load_customer_pack_capture,
    load_customer_pack_draft as _load_customer_pack_draft,
    normalize_customer_pack_draft as _normalize_customer_pack_draft,
    upload_customer_pack_draft as _upload_customer_pack_draft,
)
from play_book_studio.app.presenters import (
    _build_health_payload,
    _citation_href,
    _clean_source_view_text,
    _customer_pack_meta_for_viewer_path,
    _refresh_answerer_llm_settings,
    _serialize_citation,
)
from play_book_studio.app.server import _build_handler
from play_book_studio.app.session_flow import (
    context_with_request_overrides as _context_with_request_overrides,
    derive_next_context as _derive_next_context,
    suggest_follow_up_questions as _suggest_follow_up_questions,
)
from play_book_studio.app.sessions import ChatSession, SessionStore, Turn
from play_book_studio.app.source_books import (
    internal_viewer_html as _internal_viewer_html,
)
from play_book_studio.app.source_books_customer_pack import (
    internal_customer_pack_viewer_html as _internal_customer_pack_viewer_html,
    list_customer_pack_drafts as _list_customer_pack_drafts,
    load_customer_pack_book as _load_customer_pack_book,
)
from play_book_studio.app.viewers import _viewer_path_to_local_html
from play_book_studio.retrieval.models import SessionContext


def _citation(
    index: int,
    *,
    anchor: str = "overview",
    section: str = "OpenShift 아키텍처 개요",
    book_slug: str = "architecture",
) -> Citation:
    return Citation(
        index=index,
        chunk_id=f"chunk-{index}",
        book_slug=book_slug,
        section=section,
        anchor=anchor,
        source_url="https://example.com/architecture/index",
        viewer_path="/docs/ocp/4.20/ko/architecture/index.html#overview",
        excerpt="OpenShift 아키텍처 개요",
    )
