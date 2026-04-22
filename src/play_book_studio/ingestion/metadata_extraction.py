"""정규화 section에서 운영형 메타데이터를 추출한다."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import NormalizedSection


ERROR_TOKEN_RE = re.compile(
    r"\b(?:[A-Z][A-Za-z0-9]+(?:BackOff|Error|Failed|CrashLoop|NotReady|Timeout|Denied)|ImagePullBackOff|CrashLoopBackOff|FailedScheduling|ErrImagePull|Evicted|OOMKilled|Pending|Terminating|NotReady)\b"
)
K8S_OBJECT_RE = re.compile(
    r"\b(?:Pod|Pods|Deployment|Deployments|DeploymentConfig|Service|Route|Ingress|Node|Nodes|Namespace|Project|ConfigMap|Secret|MachineConfigPool|MachineConfig|ClusterVersion|StatefulSet|DaemonSet|ReplicaSet|PVC|PV|Job|CronJob)\b"
)
OPERATOR_NAME_RE = re.compile(
    r"\b(?:[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*\s+Operator|Operator Lifecycle Manager|OLM|Machine Config Operator|Cluster Version Operator)\b"
)
CLI_COMMAND_RE = re.compile(r"(?m)^\s*(?:[$#]\s*)?(?:oc|kubectl)\s+[^\n]+$")
VERIFICATION_PREFIX_RE = re.compile(
    r"^(확인|검증|점검|verify|validation|check)(?:\s*[:：-])?\s*",
    re.IGNORECASE,
)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass(slots=True)
class SectionMetadata:
    cli_commands: tuple[str, ...]
    error_strings: tuple[str, ...]
    k8s_objects: tuple[str, ...]
    operator_names: tuple[str, ...]
    verification_hints: tuple[str, ...]


def _ordered_unique(items: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        normalized = item.strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(normalized)
    return tuple(ordered)


def _normalize_cli_command(text: str) -> str:
    normalized = text.strip()
    normalized = re.sub(r"^(?:[$#]\s*)+", "", normalized)
    return normalized.strip()


def extract_section_metadata(section: NormalizedSection) -> SectionMetadata:
    text = section.text or ""
    cli_command_candidates = [
        _normalize_cli_command(match.group(0))
        for match in CLI_COMMAND_RE.finditer(text)
    ]
    cli_commands = _ordered_unique(cli_command_candidates)
    error_strings = _ordered_unique([match.group(0).strip() for match in ERROR_TOKEN_RE.finditer(text)])
    k8s_objects = _ordered_unique([match.group(0).strip() for match in K8S_OBJECT_RE.finditer(text)])
    operator_names = _ordered_unique([match.group(0).strip() for match in OPERATOR_NAME_RE.finditer(text)])

    verification_candidates: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        segments = [segment.strip() for segment in SENTENCE_SPLIT_RE.split(stripped) if segment.strip()]
        for segment in segments:
            if VERIFICATION_PREFIX_RE.match(segment):
                verification_candidates.append(segment)
            cli_source = VERIFICATION_PREFIX_RE.sub("", segment, count=1) if VERIFICATION_PREFIX_RE.match(segment) else segment
            normalized_cli = _normalize_cli_command(cli_source)
            if normalized_cli.startswith(("oc ", "kubectl ")) and any(
                token in normalized_cli for token in ("get ", "describe ", "logs ", "adm ", "wait ")
            ):
                verification_candidates.append(normalized_cli)
    verification_hints = _ordered_unique(verification_candidates)

    return SectionMetadata(
        cli_commands=cli_commands,
        error_strings=error_strings,
        k8s_objects=k8s_objects,
        operator_names=operator_names,
        verification_hints=verification_hints,
    )
