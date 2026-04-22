from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from play_book_studio.config.settings import load_effective_env, load_settings

REPOSITORY_CATEGORIES = ("Official Docs", "Enterprise Knowledge", "Operations Demo", "Troubleshooting")
_DOC_HINT_TERMS = ("doc", "docs", "documentation", "manual", "guide", "guides", "handbook", "runbook", "runbooks", "reference", "references", "tutorial", "tutorials")
_DEMO_HINT_TERMS = ("demo", "demos", "example", "examples", "lab", "labs", "workshop", "showcase", "sample", "samples")
_TROUBLESHOOTING_HINT_TERMS = ("troubleshoot", "troubleshooting", "incident", "incident-response", "recovery", "repair", "debug", "fix")
_ROOT_DOC_NAMES = {"docs", "doc", "documentation", "guide", "guides", "manual", "runbook", "runbooks", "tutorial", "tutorials", "reference", "references"}
_ROOT_DEMO_NAMES = {"demo", "demos", "example", "examples", "lab", "labs", "workshop", "samples"}
_TOKEN_ENV_KEYS = ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_CLASSIC_TOKEN", "GITHUB_PAT")
_GITHUB_API_BASE_URL = "https://api.github.com"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def _normalize_query(value: str) -> str:
    return " ".join(str(value or "").strip().split())

def _normalize_category(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized not in REPOSITORY_CATEGORIES:
        supported = ", ".join(REPOSITORY_CATEGORIES)
        raise ValueError(f"category는 {supported} 중 하나여야 합니다.")
    return normalized

def _github_token(root_dir: Path) -> tuple[str, str]:
    effective_env = load_effective_env(root_dir)
    for key in _TOKEN_ENV_KEYS:
        token = str(effective_env.get(key) or "").strip()
        if token:
            return token, key
    return "", ""

def _github_headers(root_dir: Path) -> tuple[dict[str, str], str]:
    token, _token_key = _github_token(root_dir)
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "PlayBookStudio/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    auth_mode = "public"
    if token:
        headers["Authorization"] = f"token {token}"
        auth_mode = "token"
    return headers, auth_mode

def _rewrite_github_query(query: str) -> str:
    normalized = _normalize_query(query)
    if not normalized:
        raise ValueError("query가 필요합니다.")
    if "/" in normalized and " " not in normalized:
        base_clause = normalized
    elif " " in normalized:
        base_clause = f"\"{normalized}\""
    else:
        base_clause = normalized
    return f"{base_clause} in:name,description,readme archived:false"

def _favorites_path(root_dir: Path) -> Path:
    settings = load_settings(root_dir)
    github_dir = settings.artifacts_dir / "github"
    github_dir.mkdir(parents=True, exist_ok=True)
    return github_dir / "favorites.json"

def _load_favorites_document(root_dir: Path) -> dict[str, Any]:
    path = _favorites_path(root_dir)
    if not path.exists():
        return {
            "version": 1,
            "updated_at": "",
            "items": [],
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {
            "version": 1,
            "updated_at": "",
            "items": [],
        }
    items = payload.get("items")
    if not isinstance(items, list):
        items = []
    return {
        "version": 1,
        "updated_at": str(payload.get("updated_at") or ""),
        "items": [dict(item) for item in items if isinstance(item, dict)],
    }

def _save_favorites_document(root_dir: Path, payload: dict[str, Any]) -> None:
    path = _favorites_path(root_dir)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

def _category_sort_key(category: str) -> int:
    try:
        return REPOSITORY_CATEGORIES.index(category)
    except ValueError:
        return len(REPOSITORY_CATEGORIES)

def list_repository_favorites(root_dir: Path) -> dict[str, Any]:
    document = _load_favorites_document(root_dir)
    items = sorted(
        document["items"],
        key=lambda item: (
            _category_sort_key(str(item.get("favorite_category") or "")),
            str(item.get("full_name") or "").lower(),
        ),
    )
    grouped = {
        category: [item for item in items if str(item.get("favorite_category") or "") == category]
        for category in REPOSITORY_CATEGORIES
    }
    return {
        "count": len(items),
        "categories": list(REPOSITORY_CATEGORIES),
        "updated_at": document.get("updated_at") or "",
        "items": items,
        "groups": grouped,
    }

def _root_listing_summary(
    root_dir: Path,
    *,
    full_name: str,
    default_branch: str,
    headers: dict[str, str],
) -> dict[str, Any]:
    del root_dir
    response = requests.get(
        f"{_GITHUB_API_BASE_URL}/repos/{full_name}/contents",
        headers=headers,
        params={"ref": default_branch},
        timeout=15,
    )
    if response.status_code != 200:
        return {
            "inspection_status": f"http_{response.status_code}",
            "entries": [],
            "entry_names": [],
        }
    payload = response.json()
    entries = payload if isinstance(payload, list) else []
    entry_names = [str(entry.get("name") or "").strip() for entry in entries if isinstance(entry, dict)]
    return {
        "inspection_status": "ok",
        "entries": entries,
        "entry_names": entry_names,
    }

def _docs_signals(
    *,
    query: str,
    repository: dict[str, Any],
    root_listing: dict[str, Any],
) -> dict[str, Any]:
    name = str(repository.get("name") or "")
    full_name = str(repository.get("full_name") or "")
    description = str(repository.get("description") or "")
    topics = [str(topic).strip() for topic in (repository.get("topics") or []) if str(topic).strip()]
    entry_names = [str(name).strip() for name in (root_listing.get("entry_names") or []) if str(name).strip()]
    lower_blob = " ".join(
        [
            query.lower(),
            name.lower(),
            full_name.lower(),
            description.lower(),
            " ".join(topic.lower() for topic in topics),
            " ".join(entry.lower() for entry in entry_names),
        ]
    )

    has_readme = any(entry.lower().startswith("readme") for entry in entry_names)
    has_docs_dir = any(entry.lower() in _ROOT_DOC_NAMES for entry in entry_names)
    has_demo_assets = any(entry.lower() in _ROOT_DEMO_NAMES for entry in entry_names)
    doc_keyword_hits = sum(1 for term in _DOC_HINT_TERMS if term in lower_blob)
    troubleshooting_hits = sum(1 for term in _TROUBLESHOOTING_HINT_TERMS if term in lower_blob)
    demo_hits = sum(1 for term in _DEMO_HINT_TERMS if term in lower_blob)

    score = 0
    if has_readme:
        score += 3
    if has_docs_dir:
        score += 4
    if doc_keyword_hits:
        score += min(doc_keyword_hits, 4)
    if troubleshooting_hits:
        score += 2
    if demo_hits:
        score += 1
    if has_demo_assets:
        score += 1

    summary_bits: list[str] = []
    if has_docs_dir:
        summary_bits.append("docs directory")
    if has_readme:
        summary_bits.append("README")
    if troubleshooting_hits:
        summary_bits.append("troubleshooting keywords")
    if demo_hits:
        summary_bits.append("demo/example assets")
    if not summary_bits:
        summary_bits.append("repo metadata only")

    return {
        "score": score,
        "inspection_status": str(root_listing.get("inspection_status") or "unknown"),
        "has_readme": has_readme,
        "has_docs_dir": has_docs_dir,
        "has_demo_assets": has_demo_assets,
        "doc_keyword_hits": doc_keyword_hits,
        "troubleshooting_hits": troubleshooting_hits,
        "demo_hits": demo_hits,
        "entry_names": entry_names[:12],
        "summary": ", ".join(summary_bits),
    }

def _query_match_score(query: str, repository: dict[str, Any], docs_signals: dict[str, Any]) -> int:
    tokens = [
        token
        for token in _normalize_query(query).lower().split()
        if token and token not in _DOC_HINT_TERMS
    ]
    if not tokens:
        return 0
    name = str(repository.get("name") or "").lower()
    full_name = str(repository.get("full_name") or "").lower()
    description = str(repository.get("description") or "").lower()
    topics = " ".join(str(topic).lower() for topic in (repository.get("topics") or []))
    entry_names = " ".join(str(item).lower() for item in docs_signals.get("entry_names") or [])

    score = 0
    for token in tokens:
        if token in name or token in full_name:
            score += 4
        elif token in description or token in topics:
            score += 2
        elif token in entry_names:
            score += 1
    return score

def _suggest_repository_category(repository: dict[str, Any], docs_signals: dict[str, Any]) -> str:
    description = str(repository.get("description") or "").lower()
    topics = " ".join(str(topic).lower() for topic in (repository.get("topics") or []))
    text = " ".join([description, topics, " ".join(str(item).lower() for item in docs_signals.get("entry_names") or [])])
    if (
        bool(docs_signals.get("has_docs_dir"))
        or int(docs_signals.get("doc_keyword_hits") or 0) >= 2
        or int(docs_signals.get("score") or 0) >= 6
    ):
        return "Official Docs"
    if any(term in text for term in _TROUBLESHOOTING_HINT_TERMS):
        return "Troubleshooting"
    if any(term in text for term in _DEMO_HINT_TERMS):
        return "Operations Demo"
    if bool(docs_signals.get("has_readme")) or int(docs_signals.get("doc_keyword_hits") or 0) > 0:
        return "Official Docs"
    return "Enterprise Knowledge"

def _favorite_lookup(root_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("full_name") or ""): item
        for item in list_repository_favorites(root_dir)["items"]
    }

def search_github_repositories(root_dir: Path, *, query: str, limit: int = 12) -> dict[str, Any]:
    normalized_query = _normalize_query(query)
    if not normalized_query:
        raise ValueError("query가 필요합니다.")
    limit = max(1, min(24, int(limit)))
    github_query = _rewrite_github_query(normalized_query)
    headers, auth_mode = _github_headers(root_dir)
    response = requests.get(
        f"{_GITHUB_API_BASE_URL}/search/repositories",
        headers=headers,
        params={
            "q": github_query,
            "per_page": limit,
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    items = payload.get("items") if isinstance(payload, dict) else []
    if not isinstance(items, list):
        items = []

    favorites = _favorite_lookup(root_dir)
    results: list[dict[str, Any]] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        full_name = str(item.get("full_name") or "").strip()
        if not full_name:
            continue
        root_listing = _root_listing_summary(
            root_dir,
            full_name=full_name,
            default_branch=str(item.get("default_branch") or "HEAD"),
            headers=headers,
        )
        docs_signals = _docs_signals(
            query=normalized_query,
            repository=item,
            root_listing=root_listing,
        )
        query_match_score = _query_match_score(normalized_query, item, docs_signals)
        favorite = favorites.get(full_name) or {}
        ranking_score = (
            query_match_score * 10000
            + int(docs_signals.get("score") or 0) * 1000
            + min(int(item.get("stargazers_count") or 0), 999)
        )
        results.append(
            {
                "id": item.get("id"),
                "name": str(item.get("name") or full_name.split("/")[-1]),
                "full_name": full_name,
                "owner_login": str(((item.get("owner") or {}).get("login")) or full_name.split("/")[0]),
                "html_url": str(item.get("html_url") or f"https://github.com/{full_name}"),
                "description": str(item.get("description") or ""),
                "stargazers_count": int(item.get("stargazers_count") or 0),
                "updated_at": str(item.get("updated_at") or ""),
                "language": str(item.get("language") or ""),
                "default_branch": str(item.get("default_branch") or ""),
                "topics": [str(topic) for topic in (item.get("topics") or []) if str(topic).strip()],
                "archived": bool(item.get("archived")),
                "docs_signals": docs_signals,
                "query_match_score": query_match_score,
                "suggested_category": str(
                    favorite.get("favorite_category")
                    or _suggest_repository_category(item, docs_signals)
                ),
                "is_favorite": bool(favorite),
                "favorite_category": str(favorite.get("favorite_category") or ""),
                "ranking_score": ranking_score,
            }
        )

    results.sort(
        key=lambda item: (
            -int(item.get("ranking_score") or 0),
            -int(item.get("stargazers_count") or 0),
            str(item.get("full_name") or "").lower(),
        )
    )
    return {
        "query": normalized_query,
        "rewritten_query": github_query,
        "count": len(results),
        "auth_mode": auth_mode,
        "categories": list(REPOSITORY_CATEGORIES),
        "results": results,
    }

def _favorite_record(payload: dict[str, Any], *, category: str) -> dict[str, Any]:
    full_name = str(payload.get("full_name") or "").strip()
    if not full_name:
        raise ValueError("repository.full_name이 필요합니다.")
    owner_login = str(payload.get("owner_login") or full_name.split("/")[0]).strip()
    name = str(payload.get("name") or full_name.split("/")[-1]).strip()
    docs_signals = dict(payload.get("docs_signals") or {})
    suggested_category = str(payload.get("suggested_category") or _suggest_repository_category(payload, docs_signals))
    return {
        "id": payload.get("id"),
        "name": name,
        "full_name": full_name,
        "owner_login": owner_login,
        "html_url": str(payload.get("html_url") or f"https://github.com/{full_name}"),
        "description": str(payload.get("description") or ""),
        "stargazers_count": int(payload.get("stargazers_count") or 0),
        "updated_at": str(payload.get("updated_at") or ""),
        "language": str(payload.get("language") or ""),
        "default_branch": str(payload.get("default_branch") or ""),
        "topics": [str(topic) for topic in (payload.get("topics") or []) if str(topic).strip()],
        "docs_signals": docs_signals,
        "suggested_category": suggested_category,
        "favorite_category": category,
        "saved_at": _now_iso(),
    }

def save_repository_favorites(root_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    category = _normalize_category(str(payload.get("category") or ""))
    repositories = payload.get("repositories")
    if not isinstance(repositories, list) or not repositories:
        raise ValueError("저장할 repositories가 필요합니다.")
    document = _load_favorites_document(root_dir)
    items_by_name = {
        str(item.get("full_name") or ""): dict(item)
        for item in document["items"]
        if str(item.get("full_name") or "").strip()
    }
    for repository in repositories:
        if not isinstance(repository, dict):
            continue
        record = _favorite_record(repository, category=category)
        existing = items_by_name.get(record["full_name"]) or {}
        if existing.get("saved_at"):
            record["saved_at"] = str(existing.get("saved_at"))
        items_by_name[record["full_name"]] = record
    document["items"] = list(items_by_name.values())
    document["updated_at"] = _now_iso()
    _save_favorites_document(root_dir, document)
    return list_repository_favorites(root_dir)

def remove_repository_favorite(root_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    full_name = str(payload.get("full_name") or "").strip()
    if not full_name:
        raise ValueError("full_name이 필요합니다.")
    document = _load_favorites_document(root_dir)
    document["items"] = [
        item
        for item in document["items"]
        if str(item.get("full_name") or "").strip() != full_name
    ]
    document["updated_at"] = _now_iso()
    _save_favorites_document(root_dir, document)
    return list_repository_favorites(root_dir)

__all__ = ["REPOSITORY_CATEGORIES", "list_repository_favorites", "remove_repository_favorite", "save_repository_favorites", "search_github_repositories"]
