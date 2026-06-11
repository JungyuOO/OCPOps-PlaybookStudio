from __future__ import annotations

import re
from typing import Any

from .models import (
    RELATION_TYPE_CO_REFERENCED,
    RELATION_TYPE_IN_NAMESPACE,
    ExtractedEntity,
    ExtractedMention,
    ExtractedRelation,
    ExtractionResult,
)

RULE_EXTRACTOR_NAME = "rule"
RULE_EXTRACTOR_VERSION = "rule-v1"

_DNS1123_RE = re.compile(r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")
_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)
_PLACEHOLDER_CHARS = "<>${}"
_COMMAND_RE = re.compile(r"\b(?:oc|kubectl)\s+[a-z][a-z-]*(?:\s+[^\s|`]+)*")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{2,}")

_RESOURCE_ALIASES: dict[str, str] = {
    "route": "route",
    "routes": "route",
    "svc": "service",
    "service": "service",
    "services": "service",
    "deploy": "deployment",
    "deployment": "deployment",
    "deployments": "deployment",
    "po": "pod",
    "pod": "pod",
    "pods": "pod",
    "pvc": "pvc",
    "pvcs": "pvc",
    "persistentvolumeclaim": "pvc",
    "persistentvolumeclaims": "pvc",
    "sc": "storageclass",
    "storageclass": "storageclass",
    "storageclasses": "storageclass",
    "pipelinerun": "pipelinerun",
    "pipelineruns": "pipelinerun",
    "repository": "repository_cr",
    "repositories": "repository_cr",
    "secret": "secret",
    "secrets": "secret",
    "cronjob": "cronjob",
    "cronjobs": "cronjob",
    "cm": "configmap",
    "configmap": "configmap",
    "configmaps": "configmap",
}

NAMESPACED_KINDS: frozenset[str] = frozenset(
    {
        "deployment",
        "service",
        "route",
        "pvc",
        "pipelinerun",
        "repository_cr",
        "secret",
        "pod",
        "cronjob",
        "configmap",
    }
)

_NAME_STOPLIST: frozenset[str] = frozenset(
    {
        "events",
        "event",
        "all",
        "status",
        "name",
        "names",
        "true",
        "false",
        "pending",
        "ready",
        "running",
        "error",
        "warning",
        "default",
        "node",
        "nodes",
        "latest",
        "none",
        "null",
        "endpoint",
        "endpoints",
        "namespace",
        "namespaces",
        "oc",
        "kubectl",
        "get",
        "describe",
        "logs",
        "delete",
        "apply",
        "edit",
        "watch",
        "create",
    }
    | set(_RESOURCE_ALIASES)
)

# (english keyword, korean keywords) per kind, checked in order; namespace wins when the
# label says the *value* is a namespace (e.g. "PVC namespace").
_LABEL_KIND_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("namespace", ("namespace", "네임스페이스")),
    ("repository_cr", ("repository cr",)),
    ("github_org", ("github 조직", "github org")),
    ("github_repo", ("repository", "레포지토리")),
    ("storageclass", ("storageclass", "스토리지클래스", "스토리지 클래스")),
    ("pipelinerun", ("pipelinerun", "파이프라인런", "파이프라인 런")),
    ("cronjob", ("cronjob", "크론잡")),
    ("configmap", ("configmap",)),
    ("deployment", ("deployment", "디플로이먼트")),
    ("service", ("service", "서비스")),
    ("route", ("route", "라우트")),
    ("secret", ("secret", "시크릿")),
    ("operator", ("operator", "오퍼레이터")),
    ("pvc", ("pvc",)),
    ("pod", ("pod", "파드")),
)

_PROSE_NS_BEFORE_RE = re.compile(r"([a-z0-9][a-z0-9-]*)\s*(?:namespace|네임스페이스)")
_PROSE_NS_AFTER_RE = re.compile(
    r"(?:namespace|네임스페이스)\s*(?:[:=]|는|은|인|이|가)\s*([a-z0-9][a-z0-9-]*)"
)
_PROSE_NS_POSSESSIVE_RE = re.compile(
    r"([a-z0-9][a-z0-9-]*)\s*(?:namespace|네임스페이스)의\s*([a-z0-9][a-z0-9-]*)"
)
_PROSE_KIND_NAME_RE = re.compile(
    r"(Route|Service|Deployment|PVC|StorageClass|Secret|Repository CR|PipelineRun|Pod|CronJob|ConfigMap)"
    r"\s+`?([a-z0-9][a-z0-9-]*)`?"
)
_PROSE_KIND_MAP: dict[str, str] = {
    "route": "route",
    "service": "service",
    "deployment": "deployment",
    "pvc": "pvc",
    "storageclass": "storageclass",
    "secret": "secret",
    "repository cr": "repository_cr",
    "pipelinerun": "pipelinerun",
    "pod": "pod",
    "cronjob": "cronjob",
    "configmap": "configmap",
}

_QUERY_NAME_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9-]*-[a-z0-9-]*[a-z0-9]")

_KIND_HINT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("namespace", ("namespace", "네임스페이스")),
    ("route", ("route", "라우트")),
    ("service", ("service", "서비스", "svc")),
    ("deployment", ("deployment", "디플로이먼트")),
    ("pvc", ("pvc", "persistentvolumeclaim")),
    ("storageclass", ("storageclass", "스토리지클래스", "스토리지 클래스")),
    ("pipelinerun", ("pipelinerun", "파이프라인런", "파이프라인 런")),
    ("repository_cr", ("repository cr", "repository")),
    ("secret", ("secret", "시크릿")),
    ("pod", ("pod", "파드")),
    ("cronjob", ("cronjob", "크론잡")),
    ("operator", ("operator", "오퍼레이터")),
)


def _is_valid_entity_name(name: str) -> bool:
    if not name or len(name) > 63:
        return False
    if any(ch in name for ch in _PLACEHOLDER_CHARS):
        return False
    if not _DNS1123_RE.match(name):
        return False
    if name in _NAME_STOPLIST:
        return False
    if name.isdigit():
        return False
    if "-" not in name and len(name) < 6:
        return False
    return True


def _kind_from_table_label(label: str, value: str) -> str:
    lowered = label.lower()
    if _URL_RE.match(value) and any(token in lowered for token in ("webhook", "url", "relay")):
        return "webhook_url"
    for kind, keywords in _LABEL_KIND_RULES:
        if any(keyword in lowered for keyword in keywords):
            return kind
    return ""


def detect_kind_hints(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    hints: list[str] = []
    for kind, keywords in _KIND_HINT_KEYWORDS:
        if kind in hints:
            continue
        if any(keyword in lowered for keyword in keywords):
            hints.append(kind)
    return tuple(hints)


def query_name_tokens(text: str) -> tuple[str, ...]:
    tokens: list[str] = []
    for token in _QUERY_NAME_TOKEN_RE.findall(text.lower()):
        if _is_valid_entity_name(token) and token not in tokens:
            tokens.append(token)
    return tuple(tokens)


class _ResultBuilder:
    def __init__(self, *, section_path: tuple[str, ...]) -> None:
        self.section = " > ".join(part for part in section_path if part)
        self._mentions: dict[tuple[str, str], ExtractedMention] = {}
        self._relations: dict[tuple[str, str, str, str], ExtractedRelation] = {}
        self.typed_names: dict[str, str] = {}

    def _locator(self, pattern: str, **extra: Any) -> dict[str, Any]:
        locator: dict[str, Any] = {"pattern": pattern, **extra}
        if self.section:
            locator["section"] = self.section
        return locator

    def add_mention(
        self,
        entity: ExtractedEntity,
        *,
        quote: str,
        pattern: str,
        confidence: float,
        **extra: Any,
    ) -> ExtractedEntity:
        quote = quote.strip()[:500]
        key = (entity.entity_key, quote)
        if key not in self._mentions:
            self._mentions[key] = ExtractedMention(
                entity=entity,
                quote=quote,
                locator=self._locator(pattern, **extra),
                confidence=confidence,
            )
        if entity.entity_kind != "namespace":
            self.typed_names.setdefault(entity.name, entity.entity_kind)
        return entity

    def add_relation(
        self,
        subject: ExtractedEntity,
        obj: ExtractedEntity,
        *,
        relation_type: str,
        quote: str,
        context: str,
        confidence: float,
    ) -> None:
        if subject.entity_key == obj.entity_key:
            return
        if relation_type == RELATION_TYPE_CO_REFERENCED and subject.entity_key > obj.entity_key:
            subject, obj = obj, subject
        quote = quote.strip()[:500]
        key = (subject.entity_key, obj.entity_key, relation_type, quote)
        if key in self._relations:
            return
        self._relations[key] = ExtractedRelation(
            subject=subject,
            object=obj,
            relation_type=relation_type,
            quote=quote,
            locator=self._locator(context),
            confidence=confidence,
        )

    def build(self) -> ExtractionResult:
        return ExtractionResult(
            mentions=tuple(self._mentions.values()),
            relations=tuple(self._relations.values()),
        )


class RuleBasedEntityExtractor:
    name = RULE_EXTRACTOR_NAME
    version = RULE_EXTRACTOR_VERSION

    def extract(self, text: str, *, section_path: tuple[str, ...] = ()) -> ExtractionResult:
        builder = _ResultBuilder(section_path=section_path)
        if not text or not text.strip():
            return builder.build()
        self._extract_commands(text, builder)
        self._extract_tables(text, builder)
        self._extract_prose(text, builder)
        return builder.build()

    # -- pass A: oc/kubectl commands ------------------------------------------------

    def _extract_commands(self, text: str, builder: _ResultBuilder) -> None:
        for match in _COMMAND_RE.finditer(text):
            command = match.group(0).strip()
            tokens = command.split()[1:]  # drop oc/kubectl
            if not tokens:
                continue
            tokens = tokens[1:]  # drop the verb (get/describe/logs/...)
            namespace_name = ""
            positional: list[str] = []
            index = 0
            while index < len(tokens):
                token = tokens[index]
                if token in {"-n", "--namespace"}:
                    if index + 1 < len(tokens):
                        namespace_name = tokens[index + 1].lower()
                        index += 2
                        continue
                elif token.startswith("--namespace="):
                    namespace_name = token.split("=", 1)[1].lower()
                elif not token.startswith("-"):
                    positional.append(token)
                index += 1

            namespace_entity: ExtractedEntity | None = None
            if _is_valid_entity_name(namespace_name):
                namespace_entity = builder.add_mention(
                    ExtractedEntity(
                        entity_kind="namespace",
                        name=namespace_name,
                        display_name=namespace_name,
                    ),
                    quote=command,
                    pattern="oc_command",
                    confidence=1.0,
                )

            resources: list[ExtractedEntity] = []
            position = 0
            while position < len(positional):
                token = positional[position]
                lowered = token.lower()
                if "/" in token:
                    alias, _, raw_name = token.partition("/")
                    kind = _RESOURCE_ALIASES.get(alias.lower(), "")
                    name = raw_name.lower()
                    if kind and _is_valid_entity_name(name):
                        resources.append(
                            builder.add_mention(
                                ExtractedEntity(
                                    entity_kind=kind,
                                    name=name,
                                    display_name=raw_name,
                                ),
                                quote=command,
                                pattern="oc_command",
                                confidence=1.0,
                            )
                        )
                    position += 1
                    continue
                kind = _RESOURCE_ALIASES.get(lowered, "")
                if kind and position + 1 < len(positional):
                    candidate = positional[position + 1]
                    name = candidate.lower()
                    if "/" not in candidate and _is_valid_entity_name(name):
                        resources.append(
                            builder.add_mention(
                                ExtractedEntity(
                                    entity_kind=kind,
                                    name=name,
                                    display_name=candidate,
                                ),
                                quote=command,
                                pattern="oc_command",
                                confidence=1.0,
                            )
                        )
                        position += 2
                        continue
                position += 1

            if namespace_entity is not None:
                for resource in resources:
                    if resource.entity_kind in NAMESPACED_KINDS:
                        builder.add_relation(
                            resource,
                            namespace_entity,
                            relation_type=RELATION_TYPE_IN_NAMESPACE,
                            quote=command,
                            context="command",
                            confidence=1.0,
                        )

    # -- pass B: markdown tables ----------------------------------------------------

    def _extract_tables(self, text: str, builder: _ResultBuilder) -> None:
        current_rows: list[str] = []
        for line in text.splitlines() + [""]:
            stripped = line.strip()
            if stripped.startswith("|"):
                current_rows.append(stripped)
                continue
            if current_rows:
                self._extract_table(current_rows, builder)
                current_rows = []

    def _extract_table(self, rows: list[str], builder: _ResultBuilder) -> None:
        namespace_entities: list[ExtractedEntity] = []
        resource_entities: list[ExtractedEntity] = []
        for row in rows[1:]:  # skip the header row
            if _TABLE_SEPARATOR_RE.match(row):
                continue
            cells = [cell.strip() for cell in row.strip("|").split("|")]
            if len(cells) < 2:
                continue
            label, value = cells[0], cells[1]
            if not label or not value:
                continue
            kind = _kind_from_table_label(label, value)
            if not kind:
                continue
            if kind == "webhook_url":
                name = value.lower()
            else:
                name = value.lower()
                if not _is_valid_entity_name(name):
                    continue
            entity = builder.add_mention(
                ExtractedEntity(
                    entity_kind=kind,
                    name=name,
                    display_name=value,
                    label=label,
                ),
                quote=row,
                pattern="table_row",
                confidence=0.9,
                label=label,
            )
            if kind == "namespace":
                namespace_entities.append(entity)
            else:
                resource_entities.append(entity)

        in_namespace_pairs: set[tuple[str, str]] = set()
        if len(namespace_entities) == 1:
            namespace_entity = namespace_entities[0]
            for resource in resource_entities:
                if resource.entity_kind in NAMESPACED_KINDS:
                    builder.add_relation(
                        resource,
                        namespace_entity,
                        relation_type=RELATION_TYPE_IN_NAMESPACE,
                        quote=self._row_quote(rows, resource),
                        context="table",
                        confidence=0.85,
                    )
                    in_namespace_pairs.add(
                        tuple(sorted((resource.entity_key, namespace_entity.entity_key)))
                    )

        co_candidates = (namespace_entities + resource_entities)[:6]
        for index, first in enumerate(co_candidates):
            for second in co_candidates[index + 1 :]:
                pair = tuple(sorted((first.entity_key, second.entity_key)))
                if pair in in_namespace_pairs:
                    continue
                builder.add_relation(
                    first,
                    second,
                    relation_type=RELATION_TYPE_CO_REFERENCED,
                    quote=self._row_quote(rows, first),
                    context="table",
                    confidence=0.9,
                )

    @staticmethod
    def _row_quote(rows: list[str], entity: ExtractedEntity) -> str:
        for row in rows:
            if entity.display_name and entity.display_name in row:
                return row
        return rows[0] if rows else ""

    # -- pass C: prose --------------------------------------------------------------

    def _extract_prose(self, text: str, builder: _ResultBuilder) -> None:
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("|"):
                continue
            if _COMMAND_RE.search(stripped):
                continue
            quote = stripped[:300]
            for match in _PROSE_NS_BEFORE_RE.finditer(stripped):
                name = match.group(1)
                if _is_valid_entity_name(name):
                    builder.add_mention(
                        ExtractedEntity(
                            entity_kind="namespace", name=name, display_name=name
                        ),
                        quote=quote,
                        pattern="prose",
                        confidence=0.7,
                    )
            for match in _PROSE_NS_AFTER_RE.finditer(stripped):
                name = match.group(1)
                if _is_valid_entity_name(name):
                    builder.add_mention(
                        ExtractedEntity(
                            entity_kind="namespace", name=name, display_name=name
                        ),
                        quote=quote,
                        pattern="prose",
                        confidence=0.7,
                    )
            for match in _PROSE_NS_POSSESSIVE_RE.finditer(stripped):
                namespace_name = match.group(1)
                resource_name = match.group(2)
                if not _is_valid_entity_name(namespace_name):
                    continue
                namespace_entity = builder.add_mention(
                    ExtractedEntity(
                        entity_kind="namespace",
                        name=namespace_name,
                        display_name=namespace_name,
                    ),
                    quote=quote,
                    pattern="prose",
                    confidence=0.7,
                )
                resolved_kind = builder.typed_names.get(resource_name)
                if not resolved_kind or not _is_valid_entity_name(resource_name):
                    continue
                resource_entity = builder.add_mention(
                    ExtractedEntity(
                        entity_kind=resolved_kind,
                        name=resource_name,
                        display_name=resource_name,
                    ),
                    quote=quote,
                    pattern="prose",
                    confidence=0.7,
                )
                if resolved_kind in NAMESPACED_KINDS:
                    builder.add_relation(
                        resource_entity,
                        namespace_entity,
                        relation_type=RELATION_TYPE_IN_NAMESPACE,
                        quote=quote,
                        context="sentence",
                        confidence=0.7,
                    )
            for match in _PROSE_KIND_NAME_RE.finditer(stripped):
                kind = _PROSE_KIND_MAP.get(match.group(1).lower(), "")
                name = match.group(2)
                if not kind or "-" not in name or not _is_valid_entity_name(name):
                    continue
                builder.add_mention(
                    ExtractedEntity(entity_kind=kind, name=name, display_name=name),
                    quote=quote,
                    pattern="prose",
                    confidence=0.7,
                )
