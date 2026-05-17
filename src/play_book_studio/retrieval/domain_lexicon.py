"""Centralized bilingual retrieval concept lexicon."""

from __future__ import annotations

from dataclasses import dataclass

from .korean_text import normalized_token_set


@dataclass(frozen=True)
class DomainLexicon:
    domain: str
    book_slugs: tuple[str, ...]
    objects: tuple[str, ...]
    primary_topics: tuple[str, ...]
    secondary_topics: tuple[str, ...]
    commands: tuple[str, ...]
    command_families: tuple[str, ...]
    match_terms: tuple[str, ...]
    static_terms: tuple[str, ...] = ()
    dynamic_terms: tuple[str, ...] = ()

    @property
    def normalized_match_terms(self) -> set[str]:
        return normalized_token_set(*self.match_terms)

    @property
    def normalized_static_terms(self) -> set[str]:
        return normalized_token_set(*self.static_terms)

    @property
    def normalized_dynamic_terms(self) -> set[str]:
        return normalized_token_set(*self.dynamic_terms)


STORAGE_LEXICON = DomainLexicon(
    domain="storage",
    book_slugs=("storage",),
    objects=("PV", "PVC", "StorageClass"),
    primary_topics=("PV", "PVC", "StorageClass", "storage provisioning"),
    secondary_topics=("volume binding", "PersistentVolume", "PersistentVolumeClaim"),
    commands=("oc get pv", "oc get pvc", "oc describe pvc", "oc get storageclass"),
    command_families=("oc_get", "oc_describe"),
    match_terms=(
        "storage",
        "스토리지",
        "volume",
        "볼륨",
        "provisioning",
        "provision",
        "프로비저닝",
        "PersistentVolume",
        "PersistentVolumeClaim",
        "PVC",
        "PV",
        "StorageClass",
        "영구 볼륨",
    ),
    static_terms=("static", "정적"),
    dynamic_terms=("dynamic", "동적"),
)

DOMAIN_LEXICONS: dict[str, DomainLexicon] = {
    STORAGE_LEXICON.domain: STORAGE_LEXICON,
}


def query_matches_domain(query: str, domain: str) -> bool:
    lexicon = DOMAIN_LEXICONS[domain]
    return bool(normalized_token_set(query) & lexicon.normalized_match_terms)


def query_matches_static_variant(query: str, domain: str) -> bool:
    lexicon = DOMAIN_LEXICONS[domain]
    return bool(normalized_token_set(query) & lexicon.normalized_static_terms)


def query_matches_dynamic_variant(query: str, domain: str) -> bool:
    lexicon = DOMAIN_LEXICONS[domain]
    return bool(normalized_token_set(query) & lexicon.normalized_dynamic_terms)


__all__ = [
    "DOMAIN_LEXICONS",
    "DomainLexicon",
    "query_matches_domain",
    "query_matches_dynamic_variant",
    "query_matches_static_variant",
]
