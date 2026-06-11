from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from .models import ExtractionResult

if TYPE_CHECKING:  # pragma: no cover - typing only
    from play_book_studio.config.settings import Settings


@runtime_checkable
class EntityExtractor(Protocol):
    name: str
    version: str

    def extract(self, text: str, *, section_path: tuple[str, ...] = ()) -> ExtractionResult: ...


def build_entity_extractor(settings: "Settings") -> EntityExtractor:
    extractor_name = (getattr(settings, "entity_graph_extractor", "rule") or "rule").strip().lower()
    if extractor_name == "rule":
        from .rules import RuleBasedEntityExtractor

        return RuleBasedEntityExtractor()
    raise ValueError(
        f"unsupported entity graph extractor: {extractor_name!r} (stage 1 supports only 'rule')"
    )
