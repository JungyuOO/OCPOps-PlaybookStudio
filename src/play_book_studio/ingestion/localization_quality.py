from __future__ import annotations

import re
from typing import Any


HANGUL_RE = re.compile(r"[가-힣]")
CYRILLIC_RE = re.compile(r"[А-Яа-я]")
URL_RE = re.compile(r"https?://\S+")
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
TAG_RE = re.compile(r"<[^>]+>")
EN_WORD_RE = re.compile(r"\b[A-Za-z][A-Za-z'-]{1,}\b")
CODE_LIKE_RE = re.compile(r"[/{}_$=<>]|[A-Za-z0-9_.-]+\.[A-Za-z0-9_.-]+")
CAMEL_OR_API_RE = re.compile(r"[a-z][A-Z]|^[A-Z0-9_]{2,}$")
NUMERIC_FRAGMENT_RE = re.compile(r"\d")
API_FIELD_PATH_RE = re.compile(
    r"^(?:\d+(?:\.\d+)*\.\s+)?"
    r"\.[A-Za-z0-9_.\[\]-]+$"
)
NUMBERED_HEADING_PREFIX_RE = re.compile(
    r"^(?:chapter\s+)?\d+(?:\.\d+)*\.?\s+",
    re.IGNORECASE,
)
COMMAND_HEADING_RE = re.compile(
    r"^(?:\d+(?:\.\d+)*\.\s+)?"
    r"(?:oc|kubectl|podman|docker|helm|operator-sdk|odo|opm)\b",
    re.IGNORECASE,
)
CLI_ARGUMENT_HEADING_RE = re.compile(r"^[A-Za-z0-9_.-]+\s+\[[^\]]+\]$")
OFFICIAL_NAME_MARKER_RE = re.compile(
    r"\b(?:API|APIs|CCM|CoreOS|Foundation|HSTS|ID|Manager|Management|OLM|Operator|RHCOS|RHACM)\b"
)

ACTION_HEADING_PREFIX_WORDS = {
    "about",
    "adding",
    "builds",
    "building",
    "configuring",
    "creating",
    "deploying",
    "enabling",
    "installing",
    "managing",
    "performing",
    "replacing",
    "troubleshooting",
    "understanding",
    "using",
}

PRESERVED_OFFICIAL_HEADING_PHRASES = {
    "aws load balancer operator",
    "cloud credential operator",
    "cloud controller manager operator",
    "cluster csi snapshot controller operator",
    "cluster machine approver operator",
    "hsts(http strict transport security)",
    "huge page",
    "kube controller manager",
    "lifecycle agent",
    "machine config operator",
    "microsoft entra workload id",
    "openshift api for data protection api",
    "openshift data foundation",
    "openstack cloud controller manager",
    "openstack cloud controller manager (ccm) config map",
    "openstack cloud controller manager(ccm) config map",
    "operator lifecycle manager",
    "olm(operator lifecycle manager) classic",
    "red hat advanced cluster management",
    "red hat advanced cluster management(rhacm)",
    "red hat build of opentelemetry",
    "rhcos(red hat enterprise linux coreos)",
    "red hat openshift data foundation",
    "red hat single sign-on",
}

TECHNICAL_TERMS = {
    "api",
    "apis",
    "aws",
    "amazon",
    "azure",
    "buildconfig",
    "buildconfigs",
    "cli",
    "cpu",
    "crd",
    "dns",
    "etcd",
    "gitops",
    "gpu",
    "helm",
    "http",
    "https",
    "image",
    "identity",
    "imagestream",
    "imagestreams",
    "io",
    "ip",
    "ipv4",
    "ipv6",
    "jenkins",
    "jenkinsfile",
    "json",
    "cluster",
    "container",
    "kubelet",
    "kubernetes",
    "linux",
    "macos",
    "namespace",
    "namespaces",
    "nodepool",
    "nodepools",
    "oc",
    "openshift",
    "operator",
    "operators",
    "platform",
    "pod",
    "pods",
    "prometheus",
    "red",
    "redhat",
    "rhel",
    "route",
    "routes",
    "block",
    "tekton",
    "url",
    "vmware",
    "web",
    "yaml",
    "ebs",
    "elastic",
    "services",
    "storage",
    "coreos",
    "cidr",
    "client",
    "compute",
    "configmap",
    "configmaps",
    "fip",
    "fips",
    "gcp",
    "google",
    "rhosp",
    "s2i",
    "disk",
    "encryption",
    "nbde",
    "network-bound",
    "node",
    "nodes",
    "persistent",
    "server",
    "tang",
    "total",
    "trust",
    "workload",
    "workloads",
    "zero",
}

TRANSLATABLE_UI_PHRASES = {
    "abstract": "개요",
    "additional resources": "추가 리소스",
    "example output": "예제 출력",
    "expand": "펼치기",
    "important": "중요",
    "issue": "문제",
    "note": "참고",
    "prerequisites": "사전 요구 사항",
    "procedure": "절차",
    "resolution": "해결",
    "tip": "팁",
    "warning": "경고",
}

PROSE_TITLE_WORDS = {
    "access",
    "about",
    "additional",
    "advanced",
    "and",
    "backup",
    "build",
    "builds",
    "building",
    "certificate",
    "configuring",
    "creating",
    "custom",
    "deploying",
    "distributed",
    "extension",
    "failure",
    "installing",
    "managing",
    "monitoring",
    "networking",
    "observability",
    "overview",
    "release",
    "restore",
    "security",
    "storage",
    "tracing",
    "troubleshooting",
    "understanding",
    "using",
    "with",
}

PROSE_SIGNAL_WORDS = {
    "a",
    "an",
    "another",
    "are",
    "be",
    "between",
    "by",
    "can",
    "created",
    "deprecated",
    "fails",
    "for",
    "from",
    "has",
    "have",
    "including",
    "into",
    "is",
    "manage",
    "must",
    "of",
    "or",
    "should",
    "the",
    "their",
    "this",
    "to",
    "update",
    "using",
    "where",
    "with",
    "you",
    "your",
}


def _clean_visible_text(text: str) -> str:
    cleaned = TAG_RE.sub(" ", str(text or ""))
    cleaned = INLINE_CODE_RE.sub(" ", cleaned)
    cleaned = URL_RE.sub(" ", cleaned)
    return " ".join(cleaned.split())


def _strip_numbered_heading_prefix(text: str) -> str:
    return NUMBERED_HEADING_PREFIX_RE.sub("", str(text or "").strip()).strip()


def _normalized_phrase(text: str) -> str:
    cleaned = _strip_numbered_heading_prefix(_clean_visible_text(text))
    return cleaned.lower().strip(" :.-")


def _is_preserved_official_heading(text: str) -> bool:
    heading = _strip_numbered_heading_prefix(_clean_visible_text(text))
    if not heading:
        return True
    if CLI_ARGUMENT_HEADING_RE.match(heading):
        return True
    compact = " ".join(heading.lower().split()).strip(" :.-")
    compact = compact.replace(" (", "(").replace("( ", "(")
    compact = compact.replace(" )", ")")
    if compact in PRESERVED_OFFICIAL_HEADING_PHRASES:
        return True
    first_word_match = EN_WORD_RE.search(heading)
    first_word = first_word_match.group(0).lower() if first_word_match else ""
    return bool(
        first_word not in ACTION_HEADING_PREFIX_WORDS
        and OFFICIAL_NAME_MARKER_RE.search(heading)
        and len(EN_WORD_RE.findall(heading)) <= 10
    )


def _untranslated_ui_phrase_reason(text: str) -> str:
    phrase = _normalized_phrase(text)
    if phrase in TRANSLATABLE_UI_PHRASES:
        return "untranslated_glossary_phrase"
    return ""


def _is_code_like_text(text: str) -> bool:
    cleaned = _clean_visible_text(text)
    if not cleaned:
        return True
    if COMMAND_HEADING_RE.match(cleaned):
        return True
    if API_FIELD_PATH_RE.match(cleaned):
        return True
    if cleaned.startswith("- ") and ("spec." in cleaned or ".spec." in cleaned):
        return True
    if cleaned.count("spec.") >= 2 or cleaned.count(".spec.") >= 2:
        return True
    if "/" in cleaned and ("{" in cleaned or "}" in cleaned or "/apis/" in cleaned):
        return True
    if "-----BEGIN CERTIFICATE" in cleaned or cleaned.startswith("apiVersion:"):
        return True
    if " schema" in cleaned and "." in cleaned:
        return True
    if cleaned.count(":") >= 3 and ("-" in cleaned or "." in cleaned):
        return True
    if (
        NUMERIC_FRAGMENT_RE.search(cleaned)
        and any(char in cleaned for char in ";()")
        and len(EN_WORD_RE.findall(cleaned)) <= 12
    ):
        return True
    heading_stripped = _strip_numbered_heading_prefix(cleaned)
    if (
        len(cleaned) <= 80
        and heading_stripped == cleaned
        and CODE_LIKE_RE.search(cleaned)
    ):
        return True
    words = EN_WORD_RE.findall(cleaned)
    if not words:
        return True
    punctuation_count = sum(cleaned.count(char) for char in "/{}_$=<>`|")
    return punctuation_count >= 3 and len(words) <= 8


def _prose_words(text: str) -> list[str]:
    words: list[str] = []
    for word in EN_WORD_RE.findall(_clean_visible_text(text)):
        lowered = word.lower().strip("'")
        if lowered in TECHNICAL_TERMS:
            continue
        if CAMEL_OR_API_RE.search(word):
            continue
        if len(lowered) <= 2:
            continue
        words.append(lowered)
    return words


def _english_prose_reason(text: str, *, field: str) -> str:
    cleaned = _clean_visible_text(text)
    if not cleaned:
        return ""
    if CYRILLIC_RE.search(cleaned):
        return "cyrillic_translation_contamination"
    ui_phrase_reason = _untranslated_ui_phrase_reason(cleaned)
    if ui_phrase_reason:
        return ui_phrase_reason
    if field in {"title", "heading"}:
        heading_text = _strip_numbered_heading_prefix(cleaned)
        if not heading_text:
            return ""
        if _is_preserved_official_heading(heading_text):
            return ""
        if _is_code_like_text(heading_text):
            return ""
        words = _prose_words(heading_text)
        if not words:
            return ""
        has_hangul = bool(HANGUL_RE.search(heading_text))
        prose_title_words = [word for word in words if word in PROSE_TITLE_WORDS]
        if not has_hangul and (len(prose_title_words) >= 1 or len(words) >= 2):
            return "english_title_or_heading"
        return ""
    if _is_code_like_text(cleaned):
        return ""
    words = _prose_words(cleaned)
    if not words:
        return ""
    has_hangul = bool(HANGUL_RE.search(cleaned))
    signal_words = [word for word in words if word in PROSE_SIGNAL_WORDS]
    if not has_hangul and field == "body" and (
        len(words) >= 5
        or (len(words) >= 3 and len(signal_words) >= 2)
    ):
        return "english_body_prose"
    if not has_hangul and len(words) >= 8:
        return "english_body_prose"
    if has_hangul and "예:" in cleaned and "," in cleaned:
        return ""
    if has_hangul and len(words) >= 12 and len(signal_words) >= 3:
        return "mixed_body_has_large_english_prose"
    return ""


def english_prose_reason(text: str, *, field: str) -> str:
    return _english_prose_reason(text, field=field)


def _iter_visible_text(row: dict[str, Any]) -> list[dict[str, str]]:
    values: list[dict[str, str]] = []
    title = str(row.get("title") or "").strip()
    if title:
        values.append({"field": "title", "section": "", "text": title})
    for section in row.get("sections") or []:
        if not isinstance(section, dict):
            continue
        heading = str(section.get("heading") or "").strip()
        if heading:
            values.append({"field": "heading", "section": heading, "text": heading})
        for block in section.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            kind = str(block.get("kind") or "").strip()
            if kind == "code":
                caption = str(block.get("caption") or "").strip()
                if caption:
                    values.append({"field": "body", "section": heading, "text": caption})
                continue
            if kind == "figure":
                for key in ("caption", "alt"):
                    value = str(block.get(key) or "").strip()
                    if value:
                        values.append({"field": "body", "section": heading, "text": value})
                continue
            if kind == "paragraph":
                values.append({"field": "body", "section": heading, "text": str(block.get("text") or "")})
                continue
            if kind == "note":
                for key in ("title", "text"):
                    value = str(block.get(key) or "").strip()
                    if value:
                        values.append({"field": "body", "section": heading, "text": value})
                continue
            if kind == "prerequisite":
                for item in block.get("items") or []:
                    values.append({"field": "body", "section": heading, "text": str(item or "")})
                continue
            if kind == "procedure":
                for step in block.get("steps") or []:
                    if not isinstance(step, dict):
                        continue
                    values.append({"field": "body", "section": heading, "text": str(step.get("text") or "")})
                    for substep in step.get("substeps") or []:
                        values.append({"field": "body", "section": heading, "text": str(substep or "")})
                continue
            if kind == "table":
                for value in block.get("headers") or []:
                    values.append({"field": "body", "section": heading, "text": str(value or "")})
                caption = str(block.get("caption") or "").strip()
                if caption:
                    values.append({"field": "body", "section": heading, "text": caption})
    return values


def build_official_ko_localization_audit(
    playbook_rows: list[dict[str, Any]],
    *,
    max_examples: int = 20,
) -> dict[str, Any]:
    """Detect user-facing English prose that would leak into the Korean official book."""

    failing_books: dict[str, dict[str, Any]] = {}
    status_counts: dict[str, int] = {}
    for row in playbook_rows:
        slug = str(row.get("book_slug") or "").strip()
        if not slug:
            continue
        translation_status = str(row.get("translation_status") or "").strip() or "unknown"
        status_counts[translation_status] = status_counts.get(translation_status, 0) + 1
        for item in _iter_visible_text(row):
            reason = _english_prose_reason(item["text"], field=item["field"])
            if not reason:
                continue
            failure = failing_books.setdefault(
                slug,
                {
                    "book_slug": slug,
                    "title": str(row.get("title") or "").strip(),
                    "translation_status": translation_status,
                    "findings": [],
                },
            )
            if len(failure["findings"]) < 3:
                failure["findings"].append(
                    {
                        "reason": reason,
                        "field": item["field"],
                        "section": item["section"],
                        "sample": _clean_visible_text(item["text"])[:220],
                    }
                )
            break
    examples = list(failing_books.values())[:max_examples]
    return {
        "status": "ok" if not failing_books else "fail",
        "book_count": len([row for row in playbook_rows if str(row.get("book_slug") or "").strip()]),
        "failing_book_count": len(failing_books),
        "failing_book_slugs": sorted(failing_books),
        "translation_status_counts": status_counts,
        "examples": examples,
    }
