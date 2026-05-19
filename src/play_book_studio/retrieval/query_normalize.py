"""Single-query normalization for recall-first retrieval."""
from __future__ import annotations

from .alias_table import expand_with_aliases, load_alias_table
_ALIAS_TABLE = load_alias_table()


def normalize_query(query: str) -> str:
    collapsed = " ".join(str(query).split())
    return expand_with_aliases(collapsed, _ALIAS_TABLE)
