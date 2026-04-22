"""원본 HTML을 가져와 fingerprint와 함께 캐시한다.

정규화 전에 코퍼스가 실제로 어디서 오는지 알고 싶다면 가장 먼저 볼 파일이다.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .models import SourceManifestEntry
from play_book_studio.config.settings import Settings

LEGAL_NOTICE_HREF_RE = re.compile(r"legal[-_]notice", re.IGNORECASE)
LEGAL_NOTICE_TEXT_RE = re.compile(r"^(legal notice|법적 공지)$", re.IGNORECASE)
APACHE_LICENSE_RE = re.compile(
    r"OpenShift documentation is licensed under the Apache License 2\.0\.",
    re.IGNORECASE,
)
TRADEMARK_RE = re.compile(
    r"Modified versions must remove all Red Hat trademarks\.",
    re.IGNORECASE,
)


def _decode_response_text(response: requests.Response) -> str:
    encoding = response.encoding
    if not encoding or encoding.lower() == "iso-8859-1":
        encoding = response.apparent_encoding or "utf-8"
    response.encoding = encoding
    return response.text


def _resolved_language_from_url(url: str, default: str) -> str:
    normalized = url.replace("\\", "/")
    if "/ko/" in normalized:
        return "ko"
    if "/en/" in normalized:
        return "en"
    return default


def fetch_html_response(url: str, settings: Settings) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(1, settings.request_retries + 1):
        try:
            response = requests.get(
                url,
                headers={"User-Agent": settings.user_agent},
                timeout=settings.request_timeout_seconds,
            )
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt == settings.request_retries:
                break
            time.sleep(settings.request_backoff_seconds * attempt)
    assert last_error is not None
    raise last_error


def fetch_html_text(url: str, settings: Settings) -> str:
    return _decode_response_text(fetch_html_response(url, settings))


def raw_html_path(settings: Settings, book_slug: str) -> Path:
    return settings.raw_html_dir / f"{book_slug}.html"


def raw_html_metadata_path(settings: Settings, book_slug: str) -> Path:
    return settings.raw_html_dir / f"{book_slug}.meta.json"


def _html_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _response_headers(response: requests.Response) -> dict[str, str]:
    headers = getattr(response, "headers", {}) or {}
    return {str(key): str(value) for key, value in dict(headers).items()}


def _http_datetime_from_headers(response: requests.Response) -> str:
    headers = _response_headers(response)
    for header_name in ("Last-Modified", "Date"):
        raw_value = headers.get(header_name) or headers.get(header_name.lower())
        if not raw_value:
            continue
        try:
            parsed = parsedate_to_datetime(str(raw_value))
        except (TypeError, ValueError, IndexError):
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return ""


def _extract_legal_notice_url(html: str, *, base_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for link in soup.find_all("a", href=True):
        href = str(link.get("href") or "").strip()
        label = " ".join(link.get_text(" ", strip=True).split())
        if not href:
            continue
        if LEGAL_NOTICE_HREF_RE.search(href) or LEGAL_NOTICE_TEXT_RE.match(label):
            return urljoin(base_url, href)
    return ""


def _default_license_or_terms(entry: SourceManifestEntry, *, legal_notice_url: str) -> str:
    source_candidates = (
        entry.source_url,
        entry.resolved_source_url,
        legal_notice_url,
        entry.translation_source_url,
    )
    if any(
        "docs.redhat.com" in candidate and "openshift_container_platform" in candidate
        for candidate in source_candidates
        if candidate
    ):
        return "OpenShift documentation is licensed under the Apache License 2.0."
    return ""


def _extract_license_or_terms(
    html: str,
    *,
    entry: SourceManifestEntry,
    legal_notice_url: str,
) -> str:
    text = " ".join(BeautifulSoup(html, "html.parser").get_text(" ", strip=True).split())
    fragments: list[str] = []
    if APACHE_LICENSE_RE.search(text):
        fragments.append("OpenShift documentation is licensed under the Apache License 2.0.")
    if TRADEMARK_RE.search(text):
        fragments.append("Modified versions must remove all Red Hat trademarks.")
    if fragments:
        return " ".join(fragments)
    if entry.license_or_terms.strip():
        return entry.license_or_terms.strip()
    return _default_license_or_terms(entry, legal_notice_url=legal_notice_url)


def load_raw_html_metadata(settings: Settings, book_slug: str) -> dict[str, object]:
    metadata_path = raw_html_metadata_path(settings, book_slug)
    if not metadata_path.exists():
        return {}
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def entry_with_collected_metadata(settings: Settings, entry: SourceManifestEntry) -> SourceManifestEntry:
    payload = load_raw_html_metadata(settings, entry.book_slug)
    if not payload:
        return entry
    return SourceManifestEntry(
        **{
            **entry.to_dict(),
            "resolved_source_url": str(payload.get("resolved_source_url") or entry.resolved_source_url),
            "resolved_language": str(payload.get("resolved_language") or entry.resolved_language),
            "fallback_detected": bool(payload.get("fallback_detected", entry.fallback_detected)),
            "legal_notice_url": str(payload.get("legal_notice_url") or entry.legal_notice_url),
            "license_or_terms": str(payload.get("license_or_terms") or entry.license_or_terms),
            "updated_at": str(payload.get("updated_at") or entry.updated_at),
        }
    )


def _write_raw_html_metadata(
    settings: Settings,
    entry: SourceManifestEntry,
    *,
    html: str,
    response: requests.Response,
) -> None:
    legal_notice_url = _extract_legal_notice_url(
        html,
        base_url=entry.resolved_source_url or entry.source_url,
    )
    license_or_terms = _extract_license_or_terms(
        html,
        entry=entry,
        legal_notice_url=legal_notice_url,
    )
    metadata = {
        "product_slug": entry.product_slug,
        "ocp_version": entry.ocp_version,
        "docs_language": entry.docs_language,
        "source_kind": entry.source_kind,
        "book_slug": entry.book_slug,
        "index_url": entry.index_url,
        "source_url": entry.source_url,
        "resolved_source_url": entry.resolved_source_url,
        "resolved_language": entry.resolved_language,
        "source_state": entry.source_state,
        "source_state_reason": entry.source_state_reason,
        "source_fingerprint": entry.source_fingerprint,
        "raw_html_sha256": _html_sha256(html),
        "fallback_detected": entry.fallback_detected,
        "content_length": len(html),
        "legal_notice_url": legal_notice_url,
        "license_or_terms": license_or_terms,
        "updated_at": _http_datetime_from_headers(response),
        "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "primary_input_kind": entry.primary_input_kind,
        "fallback_input_kind": entry.fallback_input_kind,
        "source_repo": entry.source_repo,
        "source_branch": entry.source_branch,
        "source_relative_path": entry.source_relative_path,
        "source_mirror_root": entry.source_mirror_root,
        "fallback_source_url": entry.fallback_source_url,
        "fallback_viewer_path": entry.fallback_viewer_path,
        "collected_input_kind": (
            "html_single_fallback"
            if entry.primary_input_kind == "source_repo"
            else "html_single"
        ),
    }
    raw_html_metadata_path(settings, entry.book_slug).write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _metadata_matches_entry(settings: Settings, entry: SourceManifestEntry) -> bool:
    metadata_path = raw_html_metadata_path(settings, entry.book_slug)
    html_path = raw_html_path(settings, entry.book_slug)
    if not metadata_path.exists() or not html_path.exists():
        return False
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return (
        payload.get("ocp_version") == entry.ocp_version
        and payload.get("docs_language") == entry.docs_language
        and payload.get("source_kind") == entry.source_kind
        and payload.get("source_url") == entry.source_url
        and payload.get("source_fingerprint") == entry.source_fingerprint
        and bool(str(payload.get("legal_notice_url", "")).strip())
        and bool(str(payload.get("license_or_terms", "")).strip())
        and bool(str(payload.get("updated_at", "")).strip())
    )


def collect_entry(entry: SourceManifestEntry, settings: Settings, force: bool = False) -> Path:
    # source URL 또는 fingerprint가 바뀌었을 때만 다시 수집한다.
    # 강제 새로고침이 들어오면 예외적으로 무조건 다시 받는다.
    if (
        entry.source_kind == "source-first"
        and not getattr(settings, "official_html_fallback_allowed", False)
    ):
        raise RuntimeError(
            "official source-first HTML fallback is blocked until explicit approval; "
            "use repo/AsciiDoc parse path for this rebuild"
        )
    target = raw_html_path(settings, entry.book_slug)
    if target.exists() and not force and _metadata_matches_entry(settings, entry):
        return target
    response = fetch_html_response(entry.source_url, settings)
    html = _decode_response_text(response)
    resolved_source_url = response.url.rstrip("/")
    resolved_language = _resolved_language_from_url(resolved_source_url, entry.docs_language)
    entry = SourceManifestEntry(
        **{
            **entry.to_dict(),
            "resolved_source_url": resolved_source_url,
            "resolved_language": resolved_language,
            "fallback_detected": entry.docs_language == "ko" and resolved_language == "en",
        }
    )
    target.write_text(html, encoding="utf-8")
    _write_raw_html_metadata(settings, entry, html=html, response=response)
    return target
