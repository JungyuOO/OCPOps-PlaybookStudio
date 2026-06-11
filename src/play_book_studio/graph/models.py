from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ENTITY_KINDS: tuple[str, ...] = (
    "namespace",
    "deployment",
    "service",
    "route",
    "pvc",
    "storageclass",
    "pipelinerun",
    "repository_cr",
    "secret",
    "pod",
    "cronjob",
    "configmap",
    "operator",
    "github_org",
    "github_repo",
    "webhook_url",
)

RELATION_TYPE_IN_NAMESPACE = "in_namespace"
RELATION_TYPE_CO_REFERENCED = "co_referenced"

RELATION_TYPES: tuple[str, ...] = (
    RELATION_TYPE_IN_NAMESPACE,
    RELATION_TYPE_CO_REFERENCED,
)

SOURCE_KIND_CHUNK = "chunk"
SOURCE_KIND_LIGHTSPEED_ARTIFACT = "lightspeed_artifact"
SOURCE_KIND_CLUSTER_RESOURCE = "cluster_resource"  # reserved for the live-cluster stage


@dataclass(frozen=True, slots=True)
class ExtractedEntity:
    entity_kind: str
    name: str
    display_name: str = ""
    label: str = ""

    @property
    def entity_key(self) -> str:
        return f"{self.entity_kind}:{self.name}"


@dataclass(frozen=True, slots=True)
class ExtractedMention:
    entity: ExtractedEntity
    quote: str
    locator: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class ExtractedRelation:
    subject: ExtractedEntity
    object: ExtractedEntity
    relation_type: str
    quote: str
    locator: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    mentions: tuple[ExtractedMention, ...] = ()
    relations: tuple[ExtractedRelation, ...] = ()

    @property
    def entities(self) -> tuple[ExtractedEntity, ...]:
        seen: dict[str, ExtractedEntity] = {}
        for mention in self.mentions:
            seen.setdefault(mention.entity.entity_key, mention.entity)
        return tuple(seen.values())
