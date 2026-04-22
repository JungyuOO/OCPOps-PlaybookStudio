from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[3]
WIKI_RELATIONS_DIR = ROOT_DIR / "data" / "wiki_relations"


def _load_json_asset(name: str) -> dict[str, Any]:
    path = WIKI_RELATIONS_DIR / name
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    return payload


def load_wiki_relation_assets() -> dict[str, dict[str, Any]]:
    return {
        "entity_hubs": _load_json_asset("entity_hubs.json"),
        "chat_navigation_aliases": _load_json_asset("chat_navigation_aliases.json"),
        "candidate_relations": _load_json_asset("candidate_relations.json"),
        "figure_assets": _load_json_asset("figure_assets.json"),
        "figure_entity_index": _load_json_asset("figure_entity_index.json"),
        "figure_section_index": _load_json_asset("figure_section_index.json"),
        "section_relation_index": _load_json_asset("section_relation_index.json"),
    }


__all__ = [
    "WIKI_RELATIONS_DIR",
    "load_wiki_relation_assets",
]
