from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from play_book_studio.config.settings import load_settings

from .presenters import _load_normalized_sections


GOLD_CANDIDATE_BOOK_PREFIX = "/playbooks/gold-candidates/wave1"
ACTIVE_WIKI_RUNTIME_BOOK_PREFIX = "/playbooks/wiki-runtime/active"
LEGACY_WIKI_RUNTIME_BOOK_PREFIX = "/playbooks/wiki-runtime/wave1"
MARKDOWN_VIEWER_PATH_RE = re.compile(r"^/playbooks/gold-candidates/wave1/([^/]+)/index\.html$")
ACTIVE_RUNTIME_WIKI_MARKDOWN_VIEWER_PATH_RE = re.compile(r"^/playbooks/wiki-runtime/active/([^/]+)(?:/index\.html)?$")
RUNTIME_WIKI_MARKDOWN_VIEWER_PATH_RE = re.compile(r"^/playbooks/wiki-runtime/([^/]+)/([^/]+)/index\.html$")
ENTITY_HUB_VIEWER_PATH_RE = re.compile(r"^/wiki/entities/([^/]+)(?:/index\.html)?$")
FIGURE_VIEWER_PATH_RE = re.compile(r"^/wiki/figures/([^/]+)/([^/]+)(?:/index\.html)?$")
BUYER_PACKET_VIEWER_PATH_RE = re.compile(r"^/buyer-packets/([^/]+)$")


def _playbook_book_path(root_dir: Path, book_slug: str) -> Path:
    settings = load_settings(root_dir)
    return settings.playbook_books_dir / f"{book_slug}.json"


def _playbook_book_candidates(root_dir: Path, book_slug: str) -> tuple[Path, ...]:
    settings = load_settings(root_dir)
    return tuple(directory / f"{book_slug}.json" for directory in settings.playbook_book_dirs)


def _load_playbook_book(root_dir: Path, book_slug: str) -> dict[str, Any] | None:
    for path in _playbook_book_candidates(root_dir, book_slug):
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return None


def _load_normalized_book_sections(root_dir: Path, book_slug: str) -> list[dict[str, Any]]:
    settings = load_settings(root_dir)
    for normalized_docs_path in settings.normalized_docs_candidates:
        if not normalized_docs_path.exists() or not normalized_docs_path.is_file():
            continue
        sections_by_book = _load_normalized_sections(
            str(normalized_docs_path),
            normalized_docs_path.stat().st_mtime_ns,
        )
        sections = sections_by_book.get(book_slug, [])
        if sections:
            return [dict(section) for section in sections if isinstance(section, dict)]
    return []


def parse_active_runtime_markdown_viewer_path(viewer_path: str) -> str | None:
    parsed = urlparse((viewer_path or "").strip())
    active_runtime_match = ACTIVE_RUNTIME_WIKI_MARKDOWN_VIEWER_PATH_RE.fullmatch(parsed.path.strip())
    if active_runtime_match is not None:
        return str(active_runtime_match.group(1) or "").strip()
    return None


def parse_entity_hub_viewer_path(viewer_path: str) -> str | None:
    parsed = urlparse((viewer_path or "").strip())
    match = ENTITY_HUB_VIEWER_PATH_RE.fullmatch(parsed.path.strip())
    if match is None:
        return None
    return match.group(1)


def parse_figure_viewer_path(viewer_path: str) -> tuple[str, str] | None:
    parsed = urlparse((viewer_path or "").strip())
    match = FIGURE_VIEWER_PATH_RE.fullmatch(parsed.path.strip())
    if match is None:
        return None
    return match.group(1), match.group(2)


def parse_buyer_packet_viewer_path(viewer_path: str) -> str | None:
    parsed = urlparse((viewer_path or "").strip())
    match = BUYER_PACKET_VIEWER_PATH_RE.fullmatch(parsed.path.strip())
    if match is None:
        return None
    return match.group(1)


def _load_buyer_packet_bundle(root_dir: Path) -> dict[str, Any] | None:
    path = root_dir / "reports" / "build_logs" / "buyer_packet_bundle_index.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _load_buyer_packet_entry(root_dir: Path, packet_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    bundle = _load_buyer_packet_bundle(root_dir)
    if bundle is None:
        return None
    packets = bundle.get("packets") if isinstance(bundle.get("packets"), list) else []
    match = next(
        (
            item for item in packets
            if isinstance(item, dict) and str(item.get("id") or "").strip() == packet_id
        ),
        None,
    )
    if not isinstance(match, dict):
        return None
    return bundle, match


__all__ = [
    "ACTIVE_RUNTIME_WIKI_MARKDOWN_VIEWER_PATH_RE",
    "ACTIVE_WIKI_RUNTIME_BOOK_PREFIX",
    "BUYER_PACKET_VIEWER_PATH_RE",
    "ENTITY_HUB_VIEWER_PATH_RE",
    "FIGURE_VIEWER_PATH_RE",
    "GOLD_CANDIDATE_BOOK_PREFIX",
    "LEGACY_WIKI_RUNTIME_BOOK_PREFIX",
    "MARKDOWN_VIEWER_PATH_RE",
    "RUNTIME_WIKI_MARKDOWN_VIEWER_PATH_RE",
    "_load_buyer_packet_bundle",
    "_load_buyer_packet_entry",
    "_load_normalized_book_sections",
    "_load_playbook_book",
    "_playbook_book_candidates",
    "_playbook_book_path",
    "parse_active_runtime_markdown_viewer_path",
    "parse_buyer_packet_viewer_path",
    "parse_entity_hub_viewer_path",
    "parse_figure_viewer_path",
]
