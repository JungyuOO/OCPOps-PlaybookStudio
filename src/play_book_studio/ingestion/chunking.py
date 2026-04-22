"""canonical section을 retrieval/indexing 단위 chunk로 나눈다.

`normalize.py` 다음에 이 파일을 보면, 하나의 section이 어떻게 여러 BM25/vector
레코드로 바뀌는지와 chunk-size 튜닝 지점을 이해할 수 있다.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

from .models import ChunkRecord, NormalizedSection
from .sentence_model import load_sentence_model
from play_book_studio.config.corpus_policy import chunk_profile_for_book_slug
from play_book_studio.config.settings import Settings


def _split_text_for_tokenizer(text: str, max_chars: int) -> list[str]:
    if max_chars <= 0 or len(text) <= max_chars:
        return [text]

    parts: list[str] = []
    remaining = text
    minimum_split = max(1, max_chars // 2)

    while len(remaining) > max_chars:
        split_at = remaining.rfind("\n", 0, max_chars + 1)
        if split_at < minimum_split:
            split_at = remaining.rfind(" ", 0, max_chars + 1)
        if split_at < minimum_split:
            split_at = max_chars

        piece = remaining[:split_at].strip()
        if not piece:
            piece = remaining[:max_chars]
            split_at = max_chars
        parts.append(piece)
        remaining = remaining[split_at:].lstrip()

    if remaining.strip():
        parts.append(remaining.strip())
    return parts


@dataclass(slots=True)
class TokenCounter:
    """chunk 크기 계산에 쓰는 embedding 모델 tokenizer 래퍼."""

    model_name: str
    _encoder: object | None = None
    _load_error: Exception | None = None

    def _get_encoder(self):
        if self._encoder is None and self._load_error is None:
            try:
                self._encoder = load_sentence_model(self.model_name)
            except Exception as exc:  # noqa: BLE001
                self._load_error = exc
        if self._load_error is not None:
            raise ValueError(
                f"Failed to load sentence-transformer model '{self.model_name}'."
            ) from self._load_error
        return self._encoder

    def _get_tokenizer(self):
        return self._get_encoder().tokenizer

    def encode(self, text: str) -> list[int]:
        tokenizer = self._get_tokenizer()
        model_max_length = getattr(tokenizer, "model_max_length", 0)
        if not isinstance(model_max_length, int) or model_max_length <= 0:
            model_max_length = 2048
        max_chars = max(2000, model_max_length * 3)

        token_ids: list[int] = []
        for piece in _split_text_for_tokenizer(text, max_chars):
            encoded = tokenizer(
                piece,
                add_special_tokens=False,
                return_attention_mask=False,
                return_token_type_ids=False,
                verbose=False,
            )
            token_ids.extend(encoded["input_ids"])
        return token_ids

    def count(self, text: str) -> int:
        return len(self.encode(text))


def _section_prefix(section: NormalizedSection) -> str:
    path = " > ".join(part for part in section.section_path if part)
    if path:
        return f"{section.book_title}\n{path}\n\n"
    return f"{section.book_title}\n\n"


def _chunk_type_for_section(section: NormalizedSection) -> str:
    if section.error_strings:
        return "troubleshooting"
    if section.cli_commands and section.semantic_role == "procedure":
        return "command"
    if section.semantic_role == "procedure":
        return "procedure"
    if section.semantic_role in {"concept", "overview"}:
        return "concept"
    if section.semantic_role in {"reference", "appendix"}:
        return "reference"
    if "note" in section.block_kinds:
        return "warning"
    if section.cli_commands:
        return "command"
    return "reference"


def _split_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    in_block = False
    end_tag = ""

    def flush() -> None:
        nonlocal current
        chunk = "\n".join(current).strip()
        if chunk:
            blocks.append(chunk)
        current = []

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[CODE") or stripped.startswith("[TABLE"):
            flush()
            in_block = True
            end_tag = "[/CODE]" if stripped.startswith("[CODE") else "[/TABLE]"
            current.append(stripped)
            continue
        if in_block:
            current.append(line)
            if stripped == end_tag:
                flush()
                in_block = False
                end_tag = ""
            continue
        if stripped == "":
            flush()
            continue
        current.append(line)
    flush()
    return blocks


def _hard_split_text(text: str, token_counter: TokenCounter, chunk_size: int) -> list[str]:
    tokens = token_counter.encode(text)
    if len(tokens) <= chunk_size:
        return [text]
    tokenizer = token_counter._get_tokenizer()
    parts: list[str] = []
    for start in range(0, len(tokens), chunk_size):
        piece = tokenizer.decode(tokens[start : start + chunk_size]).strip()
        if piece:
            parts.append(piece)
    return parts


def chunk_sections(sections: list[NormalizedSection], settings: Settings) -> list[ChunkRecord]:
    # chunking은 book slug별 정책을 따른다. 그래서 API/reference-heavy 문서와
    # 개념 설명 문서를 서로 다르게 쪼갤 수 있다.
    token_counter = TokenCounter(settings.embedding_model)
    chunks: list[ChunkRecord] = []

    for section in sections:
        chunk_size, chunk_overlap = chunk_profile_for_book_slug(
            section.book_slug,
            default_chunk_size=settings.chunk_size,
            default_chunk_overlap=settings.chunk_overlap,
        )
        prefix = _section_prefix(section)
        blocks = _split_blocks(section.text)
        current_blocks: list[str] = []
        current_tokens = 0
        ordinal = 0

        def finalize() -> None:
            nonlocal current_blocks, current_tokens, ordinal
            if not current_blocks:
                return
            body = "\n\n".join(current_blocks).strip()
            final_text = f"{prefix}{body}".strip()
            token_count = token_counter.count(final_text)
            raw_key = f"{section.book_slug}:{section.anchor}:{ordinal}:{final_text}"
            chunk_id = str(uuid.uuid5(uuid.NAMESPACE_URL, raw_key))
            chunks.append(
                ChunkRecord(
                    chunk_id=chunk_id,
                    book_slug=section.book_slug,
                    book_title=section.book_title,
                    chapter=section.section_path[0] if section.section_path else section.book_title,
                    section=section.heading,
                    section_id=section.section_id,
                    anchor=section.anchor,
                    source_url=section.source_url,
                    viewer_path=section.viewer_path,
                    text=final_text,
                    token_count=token_count,
                    ordinal=ordinal,
                    section_path=tuple(section.section_path),
                    chunk_type=_chunk_type_for_section(section),
                    source_id=section.source_id,
                    source_lane=section.source_lane,
                    source_type=section.source_type,
                    source_collection=section.source_collection,
                    product=section.product,
                    version=section.version,
                    locale=section.locale,
                    source_language=section.source_language,
                    display_language=section.display_language,
                    translation_status=section.translation_status,
                    translation_stage=section.translation_stage,
                    translation_source_language=section.translation_source_language,
                    translation_source_url=section.translation_source_url,
                    translation_source_fingerprint=section.translation_source_fingerprint,
                    original_title=section.original_title or section.book_title,
                    legal_notice_url=section.legal_notice_url,
                    license_or_terms=section.license_or_terms,
                    review_status=section.review_status,
                    trust_score=section.trust_score,
                    verifiability=section.verifiability,
                    updated_at=section.updated_at,
                    parsed_artifact_id=section.parsed_artifact_id,
                    tenant_id=section.tenant_id,
                    workspace_id=section.workspace_id,
                    parent_pack_id=section.parent_pack_id,
                    pack_version=section.pack_version,
                    bundle_scope=section.bundle_scope,
                    classification=section.classification,
                    access_groups=section.access_groups,
                    provider_egress_policy=section.provider_egress_policy,
                    approval_state=section.approval_state,
                    publication_state=section.publication_state,
                    redaction_state=section.redaction_state,
                    citation_eligible=section.translation_status == "approved_ko",
                    citation_block_reason="" if section.translation_status == "approved_ko" else "translation_or_review_pending",
                    cli_commands=section.cli_commands,
                    error_strings=section.error_strings,
                    k8s_objects=section.k8s_objects,
                    operator_names=section.operator_names,
                    verification_hints=section.verification_hints,
                )
            )
            ordinal += 1
            if chunk_overlap <= 0:
                current_blocks = []
                current_tokens = 0
                return
            overlap_blocks: list[str] = []
            overlap_tokens = 0
            for block in reversed(current_blocks):
                block_tokens = token_counter.count(block)
                if overlap_tokens >= chunk_overlap:
                    break
                overlap_blocks.insert(0, block)
                overlap_tokens += block_tokens
            current_blocks = overlap_blocks
            current_tokens = overlap_tokens

        for block in blocks:
            block_tokens = token_counter.count(block)
            if block_tokens > chunk_size and block.startswith("[CODE]"):
                finalize()
                current_blocks = [block]
                current_tokens = block_tokens
                finalize()
                continue
            if block_tokens > chunk_size:
                finalize()
                for piece in _hard_split_text(block, token_counter, chunk_size):
                    current_blocks = [piece]
                    current_tokens = token_counter.count(piece)
                    finalize()
                continue
            if current_tokens and current_tokens + block_tokens > chunk_size:
                finalize()
            current_blocks.append(block)
            current_tokens += block_tokens

        finalize()

    return chunks
