# retrieval 단계가 주고받는 hit, trace, session context 모델 모음.
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .text_utils import strip_section_prefix


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [
            item.strip()
            for item in value.replace(";", ",").split(",")
            if item.strip()
        ]
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    items: list[str] = []
    for item in value:
        normalized = str(item).strip()
        if normalized and normalized not in seen:
            items.append(normalized)
            seen.add(normalized)
    return items


@dataclass(slots=True)
class SessionContext:
    mode: str | None = None
    user_id: str | None = None
    user_goal: str | None = None
    current_topic: str | None = None
    open_entities: list[str] = field(default_factory=list)
    ocp_version: str | None = None
    selected_draft_ids: list[str] = field(default_factory=list)
    restrict_uploaded_sources: bool = True
    owner_user_id: str | None = None
    active_repository_id: str | None = None
    active_document_id: str | None = None
    unresolved_question: str | None = None
    preferred_source_scope: str | None = None
    enabled_source_scopes: list[str] = field(default_factory=list)
    enabled_official_book_slugs: list[str] = field(default_factory=list)
    enabled_customer_draft_ids: list[str] = field(default_factory=list)
    enabled_customer_document_ids: list[str] = field(default_factory=list)
    enabled_upload_document_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "SessionContext":
        if not payload:
            return cls()
        open_entities = payload.get("open_entities") or []
        if isinstance(open_entities, str):
            open_entities = [open_entities]
        selected_draft_ids = payload.get("selected_draft_ids") or []
        enabled_source_scopes = payload.get("enabled_source_scopes") or []
        return cls(
            mode=payload.get("mode"),
            user_id=(str(payload.get("user_id") or "").strip() or None),
            user_goal=payload.get("user_goal"),
            current_topic=(
                strip_section_prefix(str(payload.get("current_topic") or ""))
                or payload.get("current_topic")
            ),
            open_entities=list(open_entities),
            ocp_version=payload.get("ocp_version"),
            selected_draft_ids=_string_list(selected_draft_ids),
            restrict_uploaded_sources=bool(payload.get("restrict_uploaded_sources", True)),
            owner_user_id=(str(payload.get("owner_user_id") or "").strip() or None),
            active_repository_id=(str(payload.get("active_repository_id") or "").strip() or None),
            active_document_id=(str(payload.get("active_document_id") or "").strip() or None),
            unresolved_question=payload.get("unresolved_question"),
            preferred_source_scope=(str(payload.get("preferred_source_scope") or "").strip() or None),
            enabled_source_scopes=_string_list(enabled_source_scopes),
            enabled_official_book_slugs=_string_list(payload.get("enabled_official_book_slugs")),
            enabled_customer_draft_ids=_string_list(payload.get("enabled_customer_draft_ids")),
            enabled_customer_document_ids=_string_list(payload.get("enabled_customer_document_ids")),
            enabled_upload_document_ids=_string_list(payload.get("enabled_upload_document_ids")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RetrievalHit:
    chunk_id: str
    book_slug: str
    chapter: str
    section: str
    anchor: str
    source_url: str
    viewer_path: str
    text: str
    source: str
    raw_score: float
    fused_score: float = 0.0
    section_id: str = ""
    section_path: tuple[str, ...] = field(default_factory=tuple)
    section_number: str = ""
    heading_title: str = ""
    source_anchor: str = ""
    toc_path: tuple[str, ...] = field(default_factory=tuple)
    chunk_type: str = "reference"
    source_id: str = ""
    source_lane: str = "official_ko"
    source_type: str = "official_doc"
    source_collection: str = "core"
    review_status: str = "unreviewed"
    trust_score: float = 1.0
    parsed_artifact_id: str = ""
    semantic_role: str = "unknown"
    block_kinds: tuple[str, ...] = field(default_factory=tuple)
    cli_commands: tuple[str, ...] = field(default_factory=tuple)
    error_strings: tuple[str, ...] = field(default_factory=tuple)
    k8s_objects: tuple[str, ...] = field(default_factory=tuple)
    operator_names: tuple[str, ...] = field(default_factory=tuple)
    verification_hints: tuple[str, ...] = field(default_factory=tuple)
    graph_relations: tuple[str, ...] = field(default_factory=tuple)
    asset_ids: tuple[str, ...] = field(default_factory=tuple)
    chunk_role: str = "leaf"
    parent_chunk_id: str = ""
    child_chunk_ids: tuple[str, ...] = field(default_factory=tuple)
    navigation_only: bool = False
    beginner_narrative: str = ""
    starter_question_candidates: tuple[str, ...] = field(default_factory=tuple)
    followup_question_candidates: tuple[str, ...] = field(default_factory=tuple)
    question_candidates_version: int = 0
    repository_id: str = ""
    document_source_id: str = ""
    owner_user_id: str = ""
    visibility: str = ""
    source_scope: str = ""
    learning: dict[str, Any] = field(default_factory=dict)
    component_scores: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RetrievalResult:
    query: str
    normalized_query: str
    rewritten_query: str
    top_k: int
    candidate_k: int
    context: dict[str, Any]
    hits: list[RetrievalHit]
    trace: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "normalized_query": self.normalized_query,
            "rewritten_query": self.rewritten_query,
            "top_k": self.top_k,
            "candidate_k": self.candidate_k,
            "context": self.context,
            "hits": [hit.to_dict() for hit in self.hits],
            "trace": self.trace,
        }
