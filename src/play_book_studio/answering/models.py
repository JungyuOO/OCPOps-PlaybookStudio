# answering 단계가 주고받는 결과 계약과 dataclass를 모아 둔 파일.
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Citation:
    index: int
    chunk_id: str
    book_slug: str
    section: str
    anchor: str
    source_url: str
    viewer_path: str
    excerpt: str
    section_path: tuple[str, ...] = field(default_factory=tuple)
    section_path_label: str = ""
    chunk_type: str = "reference"
    semantic_role: str = "unknown"
    source_collection: str = "core"
    block_kinds: tuple[str, ...] = field(default_factory=tuple)
    cli_commands: tuple[str, ...] = field(default_factory=tuple)
    error_strings: tuple[str, ...] = field(default_factory=tuple)
    k8s_objects: tuple[str, ...] = field(default_factory=tuple)
    operator_names: tuple[str, ...] = field(default_factory=tuple)
    verification_hints: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ContextBundle:
    prompt_context: str
    citations: list[Citation]

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_context": self.prompt_context,
            "citations": [citation.to_dict() for citation in self.citations],
        }


@dataclass(slots=True)
class AnswerResult:
    query: str
    mode: str
    answer: str
    rewritten_query: str
    citations: list[Citation]
    response_kind: str = "rag"
    cited_indices: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    retrieval_trace: dict[str, Any] = field(default_factory=dict)
    pipeline_trace: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "mode": self.mode,
            "answer": self.answer,
            "rewritten_query": self.rewritten_query,
            "response_kind": self.response_kind,
            "citations": [citation.to_dict() for citation in self.citations],
            "cited_indices": self.cited_indices,
            "warnings": self.warnings,
            "retrieval_trace": self.retrieval_trace,
            "pipeline_trace": self.pipeline_trace,
        }
