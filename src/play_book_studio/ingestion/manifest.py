# 수집 대상 source catalog와 승인 manifest를 읽고 갱신하는 로직.
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup

from play_book_studio.config.settings import HIGH_VALUE_SLUGS, Settings
from .source_first import (
    SOURCE_BRANCH,
    SOURCE_REPO_URL,
    resolve_repo_relative_path,
    source_mirror_root,
)
from .models import (
    SOURCE_STATE_EN_ONLY,
    SOURCE_STATE_PUBLISHED_NATIVE,
    SourceManifestEntry,
)


CATALOG_SCHEMA_VERSION = 2
MANIFEST_SOURCE_LABEL = "openshift-docs repo-first catalog with docs.redhat html fallback"
DOCS_ROUTE_RE = re.compile(
    r"^/(?P<lang>ko|en)/documentation/"
    r"(?P<product>[^/]+)/(?P<version>\d+\.\d+)/html(?:-single)?/(?P<slug>[^/]+)(?:/index)?$"
)
VIEWER_PATH_RE = re.compile(r"^/docs/ocp/(?P<version>\d+\.\d+)/(?P<lang>ko|en)/(?P<slug>[^/]+)/index\.html$")


def _normalize_space(text: str) -> str:
    return " ".join(text.split())


def _decode_response_text(response: requests.Response) -> str:
    encoding = response.encoding
    if not encoding or encoding.lower() == "iso-8859-1":
        encoding = response.apparent_encoding or "utf-8"
    response.encoding = encoding
    return response.text


def _entry_identity_key(entry: SourceManifestEntry) -> tuple[str, str, str, str]:
    return (
        entry.ocp_version,
        entry.docs_language,
        entry.source_kind,
        entry.book_slug,
    )


def _entry_display_key(entry: SourceManifestEntry) -> str:
    return f"{entry.ocp_version}/{entry.docs_language}/{entry.source_kind}/{entry.book_slug}"


def _manifest_item_display_key(item: dict[str, object]) -> str:
    return (
        f"{item['ocp_version']}/{item['docs_language']}/"
        f"{item['source_kind']}/{item['book_slug']}"
    )


def _source_fingerprint(
    *,
    product_slug: str,
    ocp_version: str,
    docs_language: str,
    source_kind: str,
    book_slug: str,
    source_url: str,
    resolved_source_url: str,
    viewer_path: str,
    resolved_language: str,
    source_relative_path: str = "",
    primary_input_kind: str = "",
) -> str:
    payload = "||".join(
        (
            product_slug,
            ocp_version,
            docs_language,
            source_kind,
            book_slug,
            source_url,
            resolved_source_url,
            viewer_path,
            resolved_language,
            source_relative_path,
            primary_input_kind,
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fetch_docs_index(settings: Settings, *, index_url: str | None = None) -> str:
    response = requests.get(
        index_url or settings.docs_index_url,
        headers={"User-Agent": settings.user_agent},
        timeout=settings.request_timeout_seconds,
    )
    response.raise_for_status()
    return _decode_response_text(response)


def _book_href_re(product_slug: str, version: str, language: str) -> re.Pattern[str]:
    product_token = re.escape(product_slug)
    version_token = re.escape(version)
    language_token = re.escape(language)
    return re.compile(
        rf"^/{language_token}/documentation/{product_token}/{version_token}/html/([^/]+)$"
    )


def parse_manifest_entries(
    index_html: str,
    settings: Settings,
    *,
    version: str | None = None,
    language: str | None = None,
    source_kind: str = "source-first",
) -> list[SourceManifestEntry]:
    pack = settings.active_pack
    version = (version or pack.version).strip()
    language = (language or pack.language).strip()
    product_slug = pack.docs_product_slug
    source_url_template = pack.book_url_template
    viewer_path_template = pack.viewer_path_template
    index_url = pack.docs_index_url_template.format(version=version, lang=language)

    soup = BeautifulSoup(index_html, "html.parser")
    books: dict[str, str] = {}
    book_href_re = _book_href_re(product_slug, version, language)

    for link in soup.find_all("a", href=True):
        href = link["href"].rstrip("/")
        match = book_href_re.match(href)
        if not match:
            continue
        slug = match.group(1)
        title = _normalize_space(link.get_text(" ", strip=True)) or slug
        books.setdefault(slug, title)

    entries: list[SourceManifestEntry] = []
    for slug in sorted(books):
        source_url = source_url_template.format(version=version, lang=language, slug=slug)
        viewer_path = viewer_path_template.format(version=version, lang=language, slug=slug)
        source_relative_path = resolve_repo_relative_path(settings.root_dir, slug)
        primary_input_kind = "source_repo" if source_relative_path else "html_single"
        entries.append(
            SourceManifestEntry(
                product_slug=product_slug,
                ocp_version=version,
                docs_language=language,
                source_kind=source_kind,
                book_slug=slug,
                title=books[slug],
                index_url=index_url,
                source_url=source_url,
                resolved_source_url=source_url,
                resolved_language=language,
                source_state=SOURCE_STATE_PUBLISHED_NATIVE,
                source_state_reason="discovered_in_requested_language_index",
                catalog_source_label=MANIFEST_SOURCE_LABEL,
                viewer_path=viewer_path,
                high_value=slug in HIGH_VALUE_SLUGS,
                source_fingerprint=_source_fingerprint(
                    product_slug=product_slug,
                    ocp_version=version,
                    docs_language=language,
                    source_kind=source_kind,
                    book_slug=slug,
                    source_url=source_url,
                    resolved_source_url=source_url,
                    viewer_path=viewer_path,
                    resolved_language=language,
                    source_relative_path=source_relative_path,
                    primary_input_kind=primary_input_kind,
                ),
                primary_input_kind=primary_input_kind,
                fallback_input_kind="html_single" if primary_input_kind == "source_repo" else "",
                source_repo=SOURCE_REPO_URL if source_relative_path else "",
                source_branch=SOURCE_BRANCH if source_relative_path else "",
                source_relative_path=source_relative_path,
                source_mirror_root=str(source_mirror_root(settings.root_dir)) if source_relative_path else "",
                fallback_source_url=source_url if primary_input_kind == "source_repo" else "",
                fallback_viewer_path=viewer_path if primary_input_kind == "source_repo" else "",
            )
        )
    return entries


def _reconcile_source_states(entries: Iterable[SourceManifestEntry]) -> list[SourceManifestEntry]:
    ordered = list(entries)
    grouped_languages: dict[tuple[str, str, str], set[str]] = {}
    for entry in ordered:
        key = (entry.product_slug, entry.ocp_version, entry.book_slug)
        grouped_languages.setdefault(key, set()).add(entry.docs_language)

    reconciled: list[SourceManifestEntry] = []
    for entry in ordered:
        key = (entry.product_slug, entry.ocp_version, entry.book_slug)
        languages = grouped_languages.get(key, set())
        source_state = entry.source_state
        source_state_reason = entry.source_state_reason
        if entry.docs_language == "en" and "ko" not in languages:
            source_state = SOURCE_STATE_EN_ONLY
            source_state_reason = "missing_korean_index_entry"
        else:
            source_state = SOURCE_STATE_PUBLISHED_NATIVE
            source_state_reason = "discovered_in_requested_language_index"
        reconciled.append(
            SourceManifestEntry(
                **{
                    **entry.to_dict(),
                    "source_state": source_state,
                    "source_state_reason": source_state_reason,
                    "source_fingerprint": _source_fingerprint(
                        product_slug=entry.product_slug,
                        ocp_version=entry.ocp_version,
                        docs_language=entry.docs_language,
                        source_kind=entry.source_kind,
                        book_slug=entry.book_slug,
                        source_url=entry.source_url,
                        resolved_source_url=entry.resolved_source_url,
                        viewer_path=entry.viewer_path,
                        resolved_language=entry.resolved_language,
                    ),
                }
            )
        )
    return sorted(reconciled, key=_entry_identity_key)


def build_source_catalog_entries(settings: Settings) -> list[SourceManifestEntry]:
    catalog_entries: list[SourceManifestEntry] = []
    for pack in settings.source_catalog_scope:
        index_url = pack.docs_index_url_template.format(version=pack.version, lang=pack.language)
        index_html = fetch_docs_index(settings, index_url=index_url)
        catalog_entries.extend(
            parse_manifest_entries(
                index_html,
                settings,
                version=pack.version,
                language=pack.language,
                source_kind="source-first",
            )
        )
    return _reconcile_source_states(catalog_entries)


def runtime_catalog_entries(
    entries: Iterable[SourceManifestEntry],
    settings: Settings,
) -> list[SourceManifestEntry]:
    runtime_version = getattr(settings, "ocp_version", "4.20")
    runtime_language = getattr(settings, "docs_language", "ko")
    return [
        entry
        for entry in entries
        if entry.ocp_version == runtime_version
        and entry.docs_language == runtime_language
    ]


def _catalog_payload(entries: list[SourceManifestEntry]) -> dict[str, object]:
    versions = sorted({entry.ocp_version for entry in entries})
    languages = sorted({entry.docs_language for entry in entries})
    source_kinds = sorted({entry.source_kind for entry in entries})
    return {
        "version": CATALOG_SCHEMA_VERSION,
        "source": MANIFEST_SOURCE_LABEL,
        "product_slug": "openshift_container_platform",
        "versions": versions,
        "languages": languages,
        "source_kinds": source_kinds,
        "count": len(entries),
        "entries": [entry.to_dict() for entry in entries],
    }


def write_manifest(path: Path, entries: list[SourceManifestEntry]) -> None:
    payload = _catalog_payload(entries)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_route_tokens(item: dict[str, object]) -> tuple[str, str, str]:
    source_url = str(item.get("source_url", ""))
    viewer_path = str(item.get("viewer_path", ""))
    source_match = DOCS_ROUTE_RE.match(source_url.replace("https://docs.redhat.com", ""))
    if source_match:
        return (
            source_match.group("product"),
            source_match.group("version"),
            source_match.group("lang"),
        )
    viewer_match = VIEWER_PATH_RE.match(viewer_path)
    if viewer_match:
        return (
            "openshift_container_platform",
            viewer_match.group("version"),
            viewer_match.group("lang"),
        )
    return ("openshift_container_platform", "4.20", "ko")


def _entry_from_item(item: dict[str, object]) -> SourceManifestEntry:
    product_slug, ocp_version, docs_language = _parse_route_tokens(item)
    source_kind = str(item.get("source_kind") or "html-single")
    source_url = str(item.get("source_url", ""))
    viewer_path = str(item.get("viewer_path", ""))
    resolved_source_url = str(item.get("resolved_source_url") or source_url)
    resolved_language = str(item.get("resolved_language") or docs_language)
    entry_kwargs = {
        "product_slug": str(item.get("product_slug") or product_slug),
        "ocp_version": str(item.get("ocp_version") or ocp_version),
        "docs_language": str(item.get("docs_language") or docs_language),
        "source_kind": source_kind,
        "book_slug": str(item["book_slug"]),
        "title": str(item["title"]),
        "index_url": str(item.get("index_url") or ""),
        "source_url": source_url,
        "resolved_source_url": resolved_source_url,
        "resolved_language": resolved_language,
        "source_state": str(item.get("source_state") or SOURCE_STATE_PUBLISHED_NATIVE),
        "source_state_reason": str(
            item.get("source_state_reason") or "historical_manifest_entry_backfilled"
        ),
        "catalog_source_label": str(item.get("catalog_source_label") or MANIFEST_SOURCE_LABEL),
        "viewer_path": viewer_path,
        "high_value": bool(item["high_value"]),
        "vendor_title": str(item.get("vendor_title", "")),
        "content_status": str(item.get("content_status", "unknown")),
        "citation_eligible": bool(item.get("citation_eligible", False)),
        "citation_block_reason": str(item.get("citation_block_reason", "")),
        "viewer_strategy": str(item.get("viewer_strategy", "raw_html")),
        "body_language_guess": str(item.get("body_language_guess", "unknown")),
        "hangul_section_ratio": float(item.get("hangul_section_ratio", 0.0)),
        "hangul_chunk_ratio": float(item.get("hangul_chunk_ratio", 0.0)),
        "fallback_detected": bool(item.get("fallback_detected", False)),
        "source_fingerprint": str(item.get("source_fingerprint", "")),
        "approval_status": str(item.get("approval_status", "unreviewed")),
        "approval_notes": str(item.get("approval_notes", "")),
        "source_id": str(item.get("source_id", "")),
        "source_lane": str(item.get("source_lane", "")),
        "source_type": str(item.get("source_type", "official_doc")),
        "source_collection": str(item.get("source_collection", "core")),
        "legal_notice_url": str(item.get("legal_notice_url", "")),
        "original_title": str(item.get("original_title", "")),
        "license_or_terms": str(item.get("license_or_terms", "")),
        "review_status": str(item.get("review_status", "unreviewed")),
        "trust_score": float(item.get("trust_score", 1.0)),
        "verifiability": str(item.get("verifiability", "anchor_backed")),
        "updated_at": str(item.get("updated_at", "")),
        "translation_source_language": str(item.get("translation_source_language", "")),
        "translation_target_language": str(item.get("translation_target_language", "ko")),
        "translation_source_url": str(item.get("translation_source_url", "")),
        "translation_source_fingerprint": str(item.get("translation_source_fingerprint", "")),
        "translation_stage": str(item.get("translation_stage", "")),
        "tenant_id": str(item.get("tenant_id", "public")),
        "workspace_id": str(item.get("workspace_id", "core")),
        "pack_id": str(item.get("pack_id", "")),
        "pack_version": str(item.get("pack_version", "")),
        "bundle_scope": str(item.get("bundle_scope", "official")),
        "classification": str(item.get("classification", "public")),
        "access_groups": tuple(item.get("access_groups", ("public",))),
        "provider_egress_policy": str(item.get("provider_egress_policy", "unspecified")),
        "approval_state": str(item.get("approval_state", "")),
        "publication_state": str(item.get("publication_state", "")),
        "redaction_state": str(item.get("redaction_state", "not_required")),
        "primary_input_kind": str(item.get("primary_input_kind", "html_single")),
        "fallback_input_kind": str(item.get("fallback_input_kind", "")),
        "source_repo": str(item.get("source_repo", "")),
        "source_branch": str(item.get("source_branch", "")),
        "source_relative_path": str(item.get("source_relative_path", "")),
        "source_mirror_root": str(item.get("source_mirror_root", "")),
        "fallback_source_url": str(item.get("fallback_source_url", "")),
        "fallback_viewer_path": str(item.get("fallback_viewer_path", "")),
    }
    if not entry_kwargs["source_fingerprint"]:
        entry_kwargs["source_fingerprint"] = _source_fingerprint(
            product_slug=entry_kwargs["product_slug"],
            ocp_version=entry_kwargs["ocp_version"],
            docs_language=entry_kwargs["docs_language"],
            source_kind=entry_kwargs["source_kind"],
            book_slug=entry_kwargs["book_slug"],
            source_url=entry_kwargs["source_url"],
            resolved_source_url=entry_kwargs["resolved_source_url"],
            viewer_path=entry_kwargs["viewer_path"],
            resolved_language=entry_kwargs["resolved_language"],
            source_relative_path=entry_kwargs["source_relative_path"],
            primary_input_kind=entry_kwargs["primary_input_kind"],
        )
    return SourceManifestEntry(**entry_kwargs)


def read_manifest(path: Path) -> list[SourceManifestEntry]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [_entry_from_item(item) for item in payload["entries"]]


def build_manifest_update_report(
    previous_entries: list[SourceManifestEntry],
    current_entries: list[SourceManifestEntry],
) -> dict[str, object]:
    previous_by_key = {_entry_identity_key(entry): entry for entry in previous_entries}
    current_by_key = {_entry_identity_key(entry): entry for entry in current_entries}

    previous_keys = set(previous_by_key)
    current_keys = set(current_by_key)

    added = [_manifest_item_display_key(current_by_key[key].to_dict()) for key in sorted(current_keys - previous_keys)]
    removed = [_manifest_item_display_key(previous_by_key[key].to_dict()) for key in sorted(previous_keys - current_keys)]

    changed: list[dict[str, object]] = []
    for key in sorted(previous_keys & current_keys):
        before = previous_by_key[key]
        after = current_by_key[key]
        field_changes: dict[str, dict[str, object]] = {}
        for field_name in (
            "title",
            "source_url",
            "resolved_source_url",
            "resolved_language",
            "viewer_path",
            "high_value",
            "source_state",
            "content_status",
            "approval_status",
            "fallback_detected",
            "source_fingerprint",
        ):
            before_value = getattr(before, field_name)
            after_value = getattr(after, field_name)
            if before_value != after_value:
                field_changes[field_name] = {"before": before_value, "after": after_value}
        if field_changes:
            changed.append(
                {
                    "entry_key": _entry_display_key(after),
                    "book_slug": after.book_slug,
                    "ocp_version": after.ocp_version,
                    "docs_language": after.docs_language,
                    "source_kind": after.source_kind,
                    "changes": field_changes,
                }
            )

    return {
        "summary": {
            "previous_count": len(previous_entries),
            "current_count": len(current_entries),
            "added_count": len(added),
            "removed_count": len(removed),
            "changed_count": len(changed),
        },
        "added": added,
        "removed": removed,
        "changed": changed,
    }
