from __future__ import annotations

from pathlib import Path, PurePosixPath
import re
from typing import Iterable

import requests

from play_book_studio.config.settings import Settings

from .official_rebuild import ASCIIDOC_INCLUDE_RE
from .source_first import SOURCE_BRANCH, resolve_repo_relative_paths, source_mirror_root


GITHUB_BLOB_URL_RE = re.compile(
    r"^https://github\.com/openshift/openshift-docs/blob/(?P<branch>[^/]+)/(?P<path>.+)$"
)
RAW_GITHUB_BASE = "https://raw.githubusercontent.com/openshift/openshift-docs"


def _decode_response_text(response: requests.Response) -> str:
    encoding = response.encoding
    if not encoding or encoding.lower() == "iso-8859-1":
        encoding = response.apparent_encoding or "utf-8"
    response.encoding = encoding
    return response.text


def _entry_branch_and_paths(settings: Settings, entry) -> tuple[str, list[str]]:
    branch = str(getattr(entry, "source_branch", "") or "").strip()
    source_relative_paths = [
        str(path).strip()
        for path in (getattr(entry, "source_relative_paths", ()) or ())
        if str(path).strip()
    ]
    source_relative_path = str(getattr(entry, "source_relative_path", "") or "").strip()
    if source_relative_path and source_relative_path not in source_relative_paths:
        source_relative_paths.insert(0, source_relative_path)
    if not source_relative_paths:
        source_relative_paths = resolve_repo_relative_paths(settings.root_dir, entry.book_slug)
    if not source_relative_paths:
        source_url = str(
            getattr(entry, "source_url", "")
            or getattr(entry, "translation_source_url", "")
            or getattr(entry, "fallback_source_url", "")
            or ""
        ).strip()
        match = GITHUB_BLOB_URL_RE.match(source_url)
        if match is not None:
            branch = branch or str(match.group("branch") or "").strip()
            repo_path = str(match.group("path") or "").strip().lstrip("/")
            if repo_path:
                source_relative_paths = [repo_path]
    return branch or SOURCE_BRANCH, source_relative_paths


def _raw_github_content_url(branch: str, repo_path: str) -> str:
    normalized = str(repo_path or "").strip().lstrip("/")
    return f"{RAW_GITHUB_BASE}/{branch}/{normalized}"


def _iter_include_targets(text: str) -> Iterable[str]:
    for raw_line in str(text or "").splitlines():
        match = ASCIIDOC_INCLUDE_RE.match(raw_line)
        if match is None:
            continue
        target = str(match.group("target") or "").strip()
        if not target or "{" in target or "}" in target:
            continue
        yield target


def _include_repo_path_candidates(current_repo_path: str, include_target: str) -> list[str]:
    current = PurePosixPath(current_repo_path)
    candidates = [
        (current.parent / include_target).as_posix(),
        PurePosixPath(include_target).as_posix(),
    ]
    resolved: list[str] = []
    for candidate in candidates:
        normalized = candidate.strip().lstrip("/")
        if normalized and ".." not in PurePosixPath(normalized).parts and normalized not in resolved:
            resolved.append(normalized)
    return resolved


def hydrate_source_repo_artifacts(settings: Settings, entry) -> list[Path]:
    branch, source_relative_paths = _entry_branch_and_paths(settings, entry)
    if not source_relative_paths:
        raise ValueError(f"repo/AsciiDoc binding missing for {entry.book_slug}")

    mirror_root = source_mirror_root(settings.root_dir)
    visited: set[str] = set()

    def hydrate(repo_path: str) -> None:
        normalized = str(repo_path or "").strip().lstrip("/")
        if not normalized or normalized in visited:
            return
        visited.add(normalized)
        target = mirror_root / Path(normalized)
        if target.exists():
            text = target.read_text(encoding="utf-8", errors="ignore")
        else:
            url = _raw_github_content_url(branch, normalized)
            response = requests.get(
                url,
                headers={"User-Agent": settings.user_agent},
                timeout=settings.request_timeout_seconds,
            )
            response.raise_for_status()
            text = _decode_response_text(response)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        if target.suffix.lower() not in {".adoc", ".asciidoc"}:
            return
        for include_target in _iter_include_targets(text):
            for include_repo_path in _include_repo_path_candidates(normalized, include_target):
                try:
                    hydrate(include_repo_path)
                    break
                except requests.HTTPError:
                    continue

    for relative_path in source_relative_paths:
        hydrate(relative_path)

    return [(mirror_root / Path(relative_path)).resolve() for relative_path in source_relative_paths]
