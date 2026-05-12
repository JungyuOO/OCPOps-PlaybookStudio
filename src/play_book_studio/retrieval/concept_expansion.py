"""Static concept synonym expansion for retrieval queries.

This is intentionally a small JSON-backed term expander, not a graph runtime.
It adds neighboring OpenShift terms to retrieval only; it must not produce
answers or fixed question-answer mappings.
"""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any

from play_book_studio.config.corpus_paths import OCP_CONCEPT_SYNONYMS_PATH


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@lru_cache(maxsize=4)
def load_concept_synonyms(path: str | None = None) -> tuple[dict[str, Any], ...]:
    source_path = Path(path) if path else _repo_root() / OCP_CONCEPT_SYNONYMS_PATH
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ()
    entries = payload.get("concepts") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        return ()
    return tuple(entry for entry in entries if isinstance(entry, dict))


def expand_query_terms(query: str, *, path: str | None = None) -> list[str]:
    text = " ".join(str(query or "").split())
    if not text:
        return []

    terms: list[str] = []
    for concept in load_concept_synonyms(path):
        synonyms = concept.get("synonyms")
        if not isinstance(synonyms, list):
            continue
        if not any(_matches_synonym(text, str(synonym or "")) for synonym in synonyms):
            continue
        adjacent_terms = concept.get("adjacent_terms")
        if isinstance(adjacent_terms, list):
            terms.extend(str(term or "") for term in adjacent_terms)
        display_name = str(concept.get("display_name_ko") or "").strip()
        if display_name:
            terms.append(display_name)
    return _dedupe_terms(terms)


def _matches_synonym(query: str, synonym: str) -> bool:
    cleaned = " ".join(str(synonym or "").split())
    if not cleaned:
        return False
    if re.search(r"[\uac00-\ud7a3]", cleaned):
        return cleaned in query
    return bool(re.search(rf"(?<![A-Za-z0-9_-]){re.escape(cleaned)}(?![A-Za-z0-9_-])", query, re.IGNORECASE))


def _dedupe_terms(values: list[str]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = " ".join(str(value or "").split())
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        terms.append(cleaned)
    return terms


__all__ = ["expand_query_terms", "load_concept_synonyms"]
