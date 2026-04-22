from __future__ import annotations

from dataclasses import dataclass
import re


TRANSLATE_TARGET_PROSE = "translate_target_prose"
KEEP_TERMS_CODE_PATHS = "keep_terms_code_paths"
MIXED_LINE = "mixed_line"

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_PATH_RE = re.compile(r"(?:[A-Za-z]:)?[\\/][\w./\\:-]+")
_CODE_FENCE_RE = re.compile(r"^```")
_FIGURE_TAG_RE = re.compile(r"^\[/?FIGURE\b", re.IGNORECASE)
_CLI_START_RE = re.compile(
    r"^(?:\$|#)?\s*(?:oc|kubectl|podman|helm|nmcli|ssh|scp|curl|jq|yq|python|pip|grep|sed|awk|tar|cp|mv|rm|cat)\b",
    re.IGNORECASE,
)
_OPTION_RE = re.compile(r"--[\w-]+")
_ENV_VAR_RE = re.compile(r"\$[A-Z_][A-Z0-9_]*")
_ENGLISH_TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9'/_-]*\b")
_HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")
_MARKDOWN_TRIM_RE = re.compile(r"^(?:[#>*-]+|\d+\.)\s+")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_YAMLISH_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*:\s*[\[{]?$")
_PROTECTED_PHRASES = tuple(
    sorted(
        (
            "OpenShift Container Platform",
            "Red Hat OpenShift",
            "Red Hat Enterprise Linux CoreOS",
            "Operator Lifecycle Manager",
            "Machine Config Operator",
            "Cluster Network Operator",
            "Hosted Control Planes",
            "Advanced Cluster Management",
            "Advanced Cluster Security",
            "MachineConfigPool",
            "MachineSet",
            "MachineConfig",
            "NodePtpDevice",
            "PtpConfig",
            "FRR-K8s",
            "OVN-Kubernetes",
            "MetalLB Operator",
            "REST API",
            "web console",
        ),
        key=len,
        reverse=True,
    )
)
_PROTECTED_TOKENS = {
    "OpenShift",
    "Kubernetes",
    "Red",
    "Hat",
    "Operator",
    "Operators",
    "CLI",
    "API",
    "REST",
    "RHCOS",
    "OLM",
    "AWS",
    "Azure",
    "GCP",
    "ROSA",
    "OVN",
    "MetalLB",
    "BGP",
    "PTP",
    "OVS",
    "NTP",
    "UDP",
    "CRD",
    "CRDs",
    "CR",
    "CRs",
    "DPU",
    "VPC",
    "VNet",
    "NIC",
    "GNSS",
    "linuxptp",
    "Ignition",
    "MachineConfigPool",
    "MachineConfig",
    "MachineSet",
    "NodePtpDevice",
    "PtpConfig",
    "FRR",
    "FRR-K8s",
    "OVN-Kubernetes",
    "YAML",
    "JSON",
    "HTTP",
    "HTTPS",
    "CNO",
    "SCTP",
    "NetworkManager",
    "nmcli",
    "APIService",
    "ConfigMap",
    "Ingress",
    "Route",
    "Pod",
    "Pods",
    "Cluster",
}
_STOP_PREFIXES = (
    "_Source:",
    "[FIGURE",
    "[/FIGURE]",
    "```",
    "http://",
    "https://",
    "/playbooks/",
    "/docs/",
)


@dataclass(frozen=True)
class ResidueLineClassification:
    kind: str | None
    english_token_count: int
    general_word_count: int
    protected_token_count: int
    has_hangul: bool
    codeish: bool


def _normalize_line(line: str) -> str:
    stripped = str(line or "").strip()
    stripped = _MARKDOWN_TRIM_RE.sub("", stripped)
    return stripped.strip()


def _reader_text(text: str) -> str:
    return _MARKDOWN_LINK_RE.sub(r"\1", text)


def _protected_phrase_scrubbed(text: str) -> str:
    scrubbed = _reader_text(text)
    for phrase in _PROTECTED_PHRASES:
        scrubbed = re.sub(re.escape(phrase), " ", scrubbed, flags=re.IGNORECASE)
    scrubbed = _URL_RE.sub(" ", scrubbed)
    scrubbed = _PATH_RE.sub(" ", scrubbed)
    scrubbed = _OPTION_RE.sub(" ", scrubbed)
    scrubbed = _ENV_VAR_RE.sub(" ", scrubbed)
    scrubbed = scrubbed.replace("`", " ")
    return scrubbed


def _codeish_line(text: str) -> bool:
    if not text:
        return False
    if text.startswith(_STOP_PREFIXES):
        return True
    if _FIGURE_TAG_RE.match(text):
        return True
    if _CODE_FENCE_RE.match(text):
        return True
    if _CLI_START_RE.match(text):
        return True
    if _YAMLISH_RE.match(text):
        return True
    analysis_text = _reader_text(text)
    if _URL_RE.search(analysis_text) or _PATH_RE.search(analysis_text):
        return True
    if _OPTION_RE.search(analysis_text) or _ENV_VAR_RE.search(analysis_text):
        return True
    if text.count("`") >= 2:
        return True
    return False


def _hard_keep_line(text: str) -> bool:
    return bool(
        text.startswith(_STOP_PREFIXES)
        or _FIGURE_TAG_RE.match(text)
        or _CLI_START_RE.match(text)
        or _YAMLISH_RE.match(text)
    )


def classify_english_residue_line(line: str) -> ResidueLineClassification:
    text = _normalize_line(line)
    if not text:
        return ResidueLineClassification(
            kind=None,
            english_token_count=0,
            general_word_count=0,
            protected_token_count=0,
            has_hangul=False,
            codeish=False,
        )

    analysis_text = _reader_text(text)
    english_tokens = _ENGLISH_TOKEN_RE.findall(analysis_text)
    if not english_tokens:
        return ResidueLineClassification(
            kind=None,
            english_token_count=0,
            general_word_count=0,
            protected_token_count=0,
            has_hangul=bool(_HANGUL_RE.search(analysis_text)),
            codeish=_codeish_line(text),
        )

    codeish = _codeish_line(text)
    has_hangul = bool(_HANGUL_RE.search(analysis_text))
    protected_token_count = sum(1 for token in english_tokens if token in _PROTECTED_TOKENS)

    scrubbed = _protected_phrase_scrubbed(text)
    general_words = [
        token
        for token in _ENGLISH_TOKEN_RE.findall(scrubbed)
        if token not in _PROTECTED_TOKENS
    ]
    general_word_count = len(general_words)

    if general_word_count == 0:
        return ResidueLineClassification(
            kind=KEEP_TERMS_CODE_PATHS,
            english_token_count=len(english_tokens),
            general_word_count=0,
            protected_token_count=protected_token_count,
            has_hangul=has_hangul,
            codeish=codeish,
        )

    if has_hangul:
        return ResidueLineClassification(
            kind=MIXED_LINE,
            english_token_count=len(english_tokens),
            general_word_count=general_word_count,
            protected_token_count=protected_token_count,
            has_hangul=has_hangul,
            codeish=codeish,
        )

    if _hard_keep_line(text):
        return ResidueLineClassification(
            kind=KEEP_TERMS_CODE_PATHS,
            english_token_count=len(english_tokens),
            general_word_count=general_word_count,
            protected_token_count=protected_token_count,
            has_hangul=has_hangul,
            codeish=codeish,
        )

    if not codeish and general_word_count >= 2:
        return ResidueLineClassification(
            kind=TRANSLATE_TARGET_PROSE,
            english_token_count=len(english_tokens),
            general_word_count=general_word_count,
            protected_token_count=protected_token_count,
            has_hangul=has_hangul,
            codeish=codeish,
        )

    if not codeish and general_word_count == 1 and len(english_tokens) >= 2:
        return ResidueLineClassification(
            kind=TRANSLATE_TARGET_PROSE,
            english_token_count=len(english_tokens),
            general_word_count=general_word_count,
            protected_token_count=protected_token_count,
            has_hangul=has_hangul,
            codeish=codeish,
        )

    return ResidueLineClassification(
        kind=MIXED_LINE,
        english_token_count=len(english_tokens),
        general_word_count=general_word_count,
        protected_token_count=protected_token_count,
        has_hangul=has_hangul,
        codeish=codeish,
    )


__all__ = [
    "KEEP_TERMS_CODE_PATHS",
    "MIXED_LINE",
    "TRANSLATE_TARGET_PROSE",
    "ResidueLineClassification",
    "classify_english_residue_line",
]
