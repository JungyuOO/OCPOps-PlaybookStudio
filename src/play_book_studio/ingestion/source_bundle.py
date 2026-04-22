"""약한 책의 대체 소스를 bronze bundle로 저장한다."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from pathlib import PurePosixPath

import requests

from play_book_studio.config.settings import Settings

from .source_discovery import build_source_dossier, write_source_dossier


RAW_GITHUB_BASE = "https://raw.githubusercontent.com/openshift/openshift-docs/main/"
LOW_VALUE_REPO_LEAF_NAMES = {"images", "modules", "snippets"}
HIGH_VALUE_REPO_SUFFIXES = {".adoc", ".asciidoc", ".yaml", ".yml", ".json", ".sh", ".txt", ".md"}


def raw_github_content_url(path: str) -> str:
    normalized = (path or "").strip().lstrip("/")
    return f"{RAW_GITHUB_BASE}{normalized}"


def _get(url: str, settings: Settings, **kwargs) -> requests.Response:
    response = requests.get(
        url,
        headers={"User-Agent": settings.user_agent},
        timeout=settings.request_timeout_seconds,
        **kwargs,
    )
    response.raise_for_status()
    return response


def _decode_response_text(response: requests.Response) -> str:
    encoding = response.encoding
    if not encoding or encoding.lower() == "iso-8859-1":
        encoding = response.apparent_encoding or "utf-8"
    response.encoding = encoding
    return response.text


def _bundle_root(settings: Settings, slug: str) -> Path:
    return settings.bronze_dir / "source_bundles" / slug


def _reset_bundle_root(settings: Settings, slug: str) -> Path:
    bundle_root = _bundle_root(settings, slug)
    source_bundle_root = (settings.bronze_dir / "source_bundles").resolve()
    resolved_bundle_root = bundle_root.resolve()
    if source_bundle_root not in resolved_bundle_root.parents:
        raise ValueError(f"Refusing to reset unexpected bundle path: {resolved_bundle_root}")
    if resolved_bundle_root.exists():
        shutil.rmtree(resolved_bundle_root)
    resolved_bundle_root.mkdir(parents=True, exist_ok=True)
    return resolved_bundle_root


def _is_useful_repo_candidate(path: str) -> bool:
    repo_path = PurePosixPath(path)
    name = repo_path.name
    suffix = repo_path.suffix.lower()
    if name in LOW_VALUE_REPO_LEAF_NAMES and not suffix:
        return False
    if suffix in HIGH_VALUE_REPO_SUFFIXES or name == "_attributes":
        return True
    return "." in name


def _selected_repo_candidates(dossier: dict[str, object], max_repo_files: int) -> list[str]:
    raw_candidates = list(dossier.get("openshift_docs_repo_candidates", []))
    unique_candidates: list[str] = []
    seen: set[str] = set()
    for item in raw_candidates:
        path = str(item).strip()
        if not path or path in seen or not _is_useful_repo_candidate(path):
            continue
        seen.add(path)
        unique_candidates.append(path)
    return unique_candidates[:max_repo_files]


def harvest_source_bundle(
    settings: Settings,
    slug: str,
    *,
    max_repo_files: int = 20,
    max_issue_pr_candidates: int = 10,
) -> dict[str, object]:
    dossier = build_source_dossier(settings, slug)
    bundle_root = _reset_bundle_root(settings, slug)

    dossier_path = bundle_root / "dossier.json"
    write_source_dossier(dossier_path, dossier)

    official_docs_manifest: dict[str, object] = {}
    for language in ("ko", "en"):
        doc_info = dossier["official_docs"][language]
        url = str(doc_info["url"])
        response = _get(url, settings)
        html = _decode_response_text(response)
        target_dir = bundle_root / "official_docs" / language
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / "source.html"
        target_path.write_text(html, encoding="utf-8")
        official_docs_manifest[language] = {
            **doc_info,
            "artifact_path": str(target_path),
            "content_length": len(html),
        }

    repo_candidates = _selected_repo_candidates(dossier, max_repo_files)
    repo_artifacts: list[dict[str, object]] = []
    for repo_path in repo_candidates:
        raw_url = raw_github_content_url(str(repo_path))
        response = _get(raw_url, settings)
        text = _decode_response_text(response)
        target_path = bundle_root / "openshift_docs_repo" / Path(str(repo_path))
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(text, encoding="utf-8")
        repo_artifacts.append(
            {
                "repo_path": str(repo_path),
                "raw_url": raw_url,
                "artifact_path": str(target_path),
                "content_length": len(text),
            }
        )

    issue_pr_candidates = {
        "exact_slug": list(dossier.get("issue_pr_candidates_exact_slug", []))[:max_issue_pr_candidates],
        "related_terms": list(dossier.get("issue_pr_candidates_related_terms", []))[:max_issue_pr_candidates],
    }
    issue_pr_path = bundle_root / "issue_pr_candidates.json"
    issue_pr_path.write_text(json.dumps(issue_pr_candidates, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest = {
        "slug": slug,
        "bundle_root": str(bundle_root),
        "dossier_path": str(dossier_path),
        "official_docs": official_docs_manifest,
        "repo_artifacts": repo_artifacts,
        "issue_pr_candidates_path": str(issue_pr_path),
    }
    manifest_path = bundle_root / "bundle_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
