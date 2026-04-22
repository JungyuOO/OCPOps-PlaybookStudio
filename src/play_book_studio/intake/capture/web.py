from __future__ import annotations

# 웹 URL을 html-single 우선 capture 경로로 바꾸는 helper.

from urllib.parse import urlparse


DOCS_REDHAT_HOSTS = {"docs.redhat.com", "access.redhat.com"}


def resolve_web_capture_url(uri: str) -> tuple[str, str]:
    normalized = (uri or "").strip()
    if not normalized:
        return "", "direct_html_fetch_v1"

    parsed = urlparse(normalized)
    host = (parsed.netloc or "").lower()
    path = parsed.path.rstrip("/")
    parts = [part for part in path.split("/") if part]

    if host in DOCS_REDHAT_HOSTS:
        if "html-single" in parts:
            return normalized, "docs_redhat_html_single_v1"
        if "html" in parts:
            html_index = parts.index("html")
            if html_index + 1 < len(parts):
                slug = parts[html_index + 1]
                rebuilt_path = "/" + "/".join(parts[:html_index] + ["html-single", slug, "index"])
                rebuilt = parsed._replace(path=rebuilt_path, params="", query="", fragment="")
                return rebuilt.geturl(), "docs_redhat_html_single_v1"

    return normalized, "direct_html_fetch_v1"


__all__ = ["resolve_web_capture_url"]
