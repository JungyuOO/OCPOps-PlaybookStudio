"""Data-driven query aliases for retrieval normalization."""
from __future__ import annotations

import tomllib
from pathlib import Path

_ALIAS_PATH = Path(__file__).with_name("aliases.toml")


def load_alias_table(path: Path = _ALIAS_PATH) -> dict[str, list[str]]:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    aliases = raw.get("aliases", {})
    return {str(phrase): [str(term) for term in terms] for phrase, terms in aliases.items()}


def expand_with_aliases(query: str, table: dict[str, list[str]]) -> str:
    """Append canonical terms for matched aliases while preserving the user query."""
    original = str(query)
    lowered = original.lower()
    extra: list[str] = []
    seen = set()
    for phrase, canonicals in table.items():
        if phrase.lower() not in lowered:
            continue
        for term in canonicals:
            if term not in seen and term not in original:
                seen.add(term)
                extra.append(term)
    if not extra:
        return original
    return f"{original} {' '.join(extra)}"
