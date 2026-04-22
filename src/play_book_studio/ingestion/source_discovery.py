"""약한 문서의 대체 소스 후보를 수집한다.

공식 KO가 gold 품질을 못 채우는 책은 여기서 공식 EN, openshift-docs 소스,
관련 issue/PR 후보를 한꺼번에 모아 translation/manual-review lane으로 넘긴다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from pathlib import PurePosixPath
from urllib.parse import urlencode

import requests

from play_book_studio.config.settings import Settings

from .approval_report import build_corpus_gap_report, build_source_approval_report


TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
LANGUAGE_FALLBACK_RE = re.compile(
    r"This content is not available in (the )?selected language|"
    r"이 콘텐츠는 선택한 언어로 제공되지 않습니다",
    re.IGNORECASE,
)
STOPWORDS = {
    "a",
    "an",
    "and",
    "any",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}
IMAGE_SUFFIXES = {".png", ".svg", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico"}
LOW_VALUE_REPO_LEAF_NAMES = {"images", "modules", "snippets"}
GITHUB_TREE_URL = "https://api.github.com/repos/openshift/openshift-docs/git/trees/main?recursive=1"
GITHUB_ISSUE_SEARCH_URL = "https://api.github.com/search/issues"
_TREE_PATH_CACHE: dict[tuple[int, str, int], tuple[str, ...]] = {}


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


def _extract_title_hint(html: str) -> str:
    match = TITLE_RE.search(html or "")
    if not match:
        return ""
    return " ".join(match.group(1).split()).strip()


def _split_terms(value: str) -> list[str]:
    return [
        token
        for token in re.split(r"[^a-z0-9]+", (value or "").lower())
        if token and token not in STOPWORDS and len(token) > 1
    ]


def _normalized_title(title: str) -> str:
    return " ".join((title or "").split()).strip()


def _book_aliases(slug: str, title: str) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        normalized = " ".join(value.split()).strip().lower()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        aliases.append(normalized)

    slug = (slug or "").strip()
    title = _normalized_title(title)
    add(slug)
    add(slug.replace("_", "-"))
    add(slug.replace("_", " "))
    add(title)
    add(title.replace(" ", "-"))
    add(title.replace(" ", "_"))

    title_terms = set(_split_terms(title))
    if {"installing", "platform"}.issubset(title_terms):
        add("installing_platform_agnostic")
        add("installing-platform-agnostic")
        add("installing/installing_platform_agnostic")
    if "backup" in title_terms and "restore" in title_terms:
        add("backup_and_restore")
    if "machine" in title_terms and "configuration" in title_terms:
        add("machine_configuration")
    if "monitoring" in title_terms:
        add("monitoring")
    if "operator" in title_terms or "operators" in title_terms:
        add("operators")
    if "etcd" in title_terms:
        add("etcd")
    return aliases


def _docs_page_queries(slug: str, title: str) -> list[str]:
    queries: list[str] = []
    for alias in _book_aliases(slug, title):
        if " " in alias:
            queries.append(f'repo:openshift/openshift-docs "{alias}"')
        else:
            queries.append(f"repo:openshift/openshift-docs {alias}")
    seen: set[str] = set()
    ordered: list[str] = []
    for query in queries:
        if query in seen:
            continue
        seen.add(query)
        ordered.append(query)
    return ordered


def _useful_repo_blob(path: str) -> bool:
    repo_path = PurePosixPath(path)
    name = repo_path.name.lower()
    suffix = repo_path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return False
    if name in LOW_VALUE_REPO_LEAF_NAMES and not suffix:
        return False
    if suffix in {".adoc", ".asciidoc", ".md", ".txt", ".yaml", ".yml", ".json"}:
        return True
    return name == "_attributes"


def _repo_candidate_score(path: str, slug: str, title: str) -> tuple[int, int, str]:
    repo_path = PurePosixPath(path)
    parts = [part.lower() for part in repo_path.parts]
    name = repo_path.name.lower()
    text = "/".join(parts)
    title_terms = _split_terms(title)
    aliases = _book_aliases(slug, title)

    exact_alias_hits = 0
    prefix_alias_hits = 0
    term_hits = 0

    for alias in aliases:
        if alias in parts or alias == name:
            exact_alias_hits += 1
        elif alias in text:
            prefix_alias_hits += 1

    for term in title_terms:
        if term in parts or term == name or term in text:
            term_hits += 1

    suffix_bonus = 5 if repo_path.suffix.lower() in {".adoc", ".asciidoc"} else 0
    root_bonus = 3 if parts and parts[0] in {slug.split("_", 1)[0], title_terms[0] if title_terms else ""} else 0
    exact_component_bonus = 8 if any(part == slug for part in parts) else 0

    score = (
        exact_alias_hits * 100
        + prefix_alias_hits * 20
        + term_hits * 15
        + exact_component_bonus
        + suffix_bonus
        + root_bonus
        - len(parts)
    )
    return (score, len(parts), path)


def _repo_path_hint(repo_candidates: list[str]) -> str:
    if not repo_candidates:
        return ""
    parts = [part for part in PurePosixPath(repo_candidates[0]).parts if part]
    if not parts:
        return ""
    root = parts[0].lower()
    if root in {"virt", "observability", "microshift_running_apps"} and len(parts) > 1:
        return f"{parts[0]}/{parts[1]}"
    return parts[0]


def _github_tree_blob_paths(settings: Settings) -> tuple[str, ...]:
    cache_key = (id(_get), settings.user_agent, settings.request_timeout_seconds)
    if cache_key not in _TREE_PATH_CACHE:
        payload = _get(GITHUB_TREE_URL, settings)
        data = payload.json()
        _TREE_PATH_CACHE[cache_key] = tuple(
            str(item["path"])
            for item in data.get("tree", [])
            if item.get("type") == "blob"
        )
    return _TREE_PATH_CACHE[cache_key]


def _docs_url(settings: Settings, *, language: str, slug: str) -> str:
    return (
        f"https://docs.redhat.com/{language}/documentation/"
        f"openshift_container_platform/{settings.ocp_version}/html-single/{slug}/index"
    )


def _docs_page_summary(settings: Settings, *, language: str, slug: str) -> dict[str, object]:
    url = _docs_url(settings, language=language, slug=slug)
    response = _get(url, settings)
    html = _decode_response_text(response)
    return {
        "url": response.url,
        "status_code": response.status_code,
        "contains_language_fallback_banner": bool(LANGUAGE_FALLBACK_RE.search(html)),
        "title_hint": _extract_title_hint(html),
    }


def _repo_path_candidates(settings: Settings, slug: str, title: str) -> list[str]:
    ranked = [
        _repo_candidate_score(path, slug, title)
        for path in _github_tree_blob_paths(settings)
        if _useful_repo_blob(path)
    ]
    ranked.sort(reverse=True)
    candidates: list[str] = []
    seen: set[str] = set()
    for score, _, path in ranked:
        if score <= 0 or path in seen:
            continue
        seen.add(path)
        candidates.append(path)
        if len(candidates) >= 50:
            break
    return candidates


def _issue_pr_candidates(settings: Settings, queries: list[str]) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    seen_numbers: set[int] = set()
    for query in queries:
        try:
            response = _get(
                GITHUB_ISSUE_SEARCH_URL,
                settings,
                params={
                    "q": query,
                    "per_page": 10,
                    "sort": "updated",
                    "order": "desc",
                },
            )
        except requests.HTTPError as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code == 403:
                break
            continue
        except requests.RequestException:
            continue
        payload = response.json()
        for item in payload.get("items", []):
            number = item.get("number")
            if not isinstance(number, int) or number in seen_numbers:
                continue
            seen_numbers.add(number)
            items.append(
                {
                    "number": number,
                    "title": item.get("title"),
                    "state": item.get("state"),
                    "html_url": item.get("html_url"),
                    "pull_request": "pull_request" in item,
                    "updated_at": item.get("updated_at"),
                }
            )
            if len(items) >= 10:
                return items
    return items


def _current_book_context(settings: Settings, slug: str) -> dict[str, object]:
    approval_report = build_source_approval_report(settings)
    books = {str(item["book_slug"]): item for item in approval_report["books"]}
    gap_report = build_corpus_gap_report(settings)
    gap_lane = "approved"
    if any(str(item["book_slug"]) == slug for item in gap_report["translation_first"]):
        gap_lane = "translation_first"
    elif any(str(item["book_slug"]) == slug for item in gap_report["manual_review_first"]):
        gap_lane = "manual_review_first"
    elif any(str(item["book_slug"]) == slug for item in gap_report["remaining_gaps"]):
        gap_lane = "remaining_gap"
    return {
        "book": books.get(slug, {}),
        "gap_lane": gap_lane,
    }


def build_source_dossier(settings: Settings, slug: str) -> dict[str, object]:
    context = _current_book_context(settings, slug)
    book = context["book"]
    title = str(book.get("title", "")).strip()
    repo_candidates = _repo_path_candidates(settings, slug, title)
    path_hint = _repo_path_hint(repo_candidates)

    def qualify(base_query: str) -> str:
        prefix = "repo:openshift/openshift-docs"
        if path_hint:
            prefix = f"{prefix} path:{path_hint}"
        return f"{prefix} {base_query}"

    normalized_title = _normalized_title(title)
    exact_queries: list[str] = []
    if normalized_title:
        exact_queries.append(qualify(f'"{normalized_title}"'))
    exact_queries.append(qualify(slug))
    related_queries: list[str] = []
    for alias in _book_aliases(slug, title):
        if alias in {slug, normalized_title.lower()}:
            continue
        related_queries.append(qualify(f'"{alias}"' if " " in alias else alias))
    exact_seen: set[str] = set()
    exact_queries = [query for query in exact_queries if not (query in exact_seen or exact_seen.add(query))]
    related_seen: set[str] = set()
    related_queries = [query for query in related_queries if not (query in related_seen or related_seen.add(query))]
    return {
        "slug": slug,
        "current_status": {
            "content_status": str(book.get("content_status", "")),
            "gap_lane": str(context["gap_lane"]),
            "gap_action": str(book.get("gap_action", "")),
            "fallback_detected": bool(book.get("fallback_detected", False)),
            "hangul_chunk_ratio": float(book.get("hangul_chunk_ratio", 0.0)),
            "title": str(book.get("title", "")),
        },
        "official_docs": {
            "ko": _docs_page_summary(settings, language="ko", slug=slug),
            "en": _docs_page_summary(settings, language="en", slug=slug),
        },
        "openshift_docs_repo_candidates": repo_candidates,
        "issue_pr_candidates_exact_slug": _issue_pr_candidates(settings, exact_queries[:7]),
        "issue_pr_candidates_related_terms": _issue_pr_candidates(settings, related_queries[:7]),
        "repo_search_terms": {
            "slug": slug,
            "title": title,
            "aliases": _book_aliases(slug, title),
            "path_hint": path_hint,
            "exact_queries": exact_queries[:4],
            "related_queries": related_queries[:4],
        },
    }


def default_dossier_slugs(settings: Settings) -> list[str]:
    gap_report = build_corpus_gap_report(settings)
    ordered = [
        *gap_report["translation_first"],
        *gap_report["manual_review_first"],
        *gap_report["remaining_gaps"],
    ]
    seen: set[str] = set()
    slugs: list[str] = []
    for item in ordered:
        slug = str(item["book_slug"])
        if slug in seen:
            continue
        seen.add(slug)
        slugs.append(slug)
    return slugs


def write_source_dossier(path: Path, dossier: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dossier, ensure_ascii=False, indent=2), encoding="utf-8")


def build_issue_search_url(query: str) -> str:
    return f"https://github.com/search?{urlencode({'q': query, 'type': 'issues'})}"
