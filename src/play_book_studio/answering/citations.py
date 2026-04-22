# citation 번호 보정, dedupe, fallback 선택을 담당하는 helper 모듈이다.

from __future__ import annotations

import re
from dataclasses import replace


CITATION_RE = re.compile(r"\[(\d+)\]")
ADJACENT_DUPLICATE_CITATION_RE = re.compile(r"(\[\d+\])(?:\s*\1)+")
CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)


def citation_identity(citation) -> tuple[str, str]:
    viewer_path = (citation.viewer_path or "").strip().lower()
    if viewer_path:
        return citation.book_slug, viewer_path
    source_url = (citation.source_url or "").strip().lower()
    anchor = (citation.anchor or "").strip().lower()
    return citation.book_slug, f"{source_url}#{anchor}"


def finalize_citations(
    answer_text: str,
    citations,
) -> tuple[str, list, list[int]]:
    referenced_indices: list[int] = []
    for match in CITATION_RE.finditer(answer_text):
        index = int(match.group(1))
        if 1 <= index <= len(citations):
            referenced_indices.append(index)

    if not referenced_indices:
        return answer_text, [], []

    canonical_index_by_source: dict[tuple[str, str], int] = {}
    remapped_index_by_original: dict[int, int] = {}
    final_citations = []

    for original_index in referenced_indices:
        if original_index in remapped_index_by_original:
            continue
        citation = citations[original_index - 1]
        identity = citation_identity(citation)
        canonical_index = canonical_index_by_source.get(identity)
        if canonical_index is None:
            canonical_index = len(final_citations) + 1
            canonical_index_by_source[identity] = canonical_index
            final_citations.append(replace(citation, index=canonical_index))
        remapped_index_by_original[original_index] = canonical_index

    rewritten_answer = CITATION_RE.sub(
        lambda match: (
            f"[{remapped_index_by_original[int(match.group(1))]}]"
            if int(match.group(1)) in remapped_index_by_original
            else ""
        ),
        answer_text,
    )
    rewritten_answer = ADJACENT_DUPLICATE_CITATION_RE.sub(r"\1", rewritten_answer)
    rewritten_answer = _normalize_non_code_spacing(rewritten_answer).strip()

    cited_indices: list[int] = []
    seen_indices: set[int] = set()
    for match in CITATION_RE.finditer(rewritten_answer):
        index = int(match.group(1))
        if 1 <= index <= len(final_citations) and index not in seen_indices:
            cited_indices.append(index)
            seen_indices.add(index)

    return rewritten_answer, final_citations, cited_indices


def preserve_explicit_mixed_runtime_citations(
    query: str,
    *,
    selected_citations,
    final_citations,
) -> list:
    if not _is_explicit_mixed_runtime_query(query):
        return final_citations
    if not selected_citations:
        return final_citations

    private_selected = next(
        (
            citation
            for citation in selected_citations
            if _citation_truth_bucket(citation) == "private"
        ),
        None,
    )
    official_selected = next(
        (
            citation
            for citation in selected_citations
            if _citation_truth_bucket(citation) == "official"
        ),
        None,
    )
    if private_selected is None or official_selected is None:
        return final_citations

    preserved = [replace(citation, index=index + 1) for index, citation in enumerate(final_citations)]
    existing_identities = {citation_identity(citation) for citation in preserved}

    for candidate in (private_selected, official_selected):
        identity = citation_identity(candidate)
        if identity in existing_identities:
            continue
        preserved.append(replace(candidate, index=len(preserved) + 1))
        existing_identities.add(identity)
    return preserved


def _normalize_non_code_spacing(answer_text: str) -> str:
    segments: list[str] = []
    last_end = 0
    for match in CODE_FENCE_RE.finditer(answer_text or ""):
        segments.append(_normalize_spacing_segment(answer_text[last_end:match.start()]))
        segments.append(match.group(0))
        last_end = match.end()
    segments.append(_normalize_spacing_segment((answer_text or "")[last_end:]))
    return "".join(segments)


def _normalize_spacing_segment(segment: str) -> str:
    normalized = re.sub(r"\s+([,.;:])", r"\1", segment)
    normalized = re.sub(r"[ \t]{2,}", " ", normalized)
    normalized = re.sub(r"\n[ \t]+", "\n", normalized)
    return normalized


def inject_single_citation(answer_text: str, *, citation_index: int = 1) -> str:
    blocks = answer_text.split("\n\n")
    for index, block in enumerate(blocks):
        stripped = block.strip()
        if not stripped or stripped.startswith("```"):
            continue
        if CITATION_RE.search(stripped):
            return answer_text
        blocks[index] = f"{stripped} [{citation_index}]"
        return "\n\n".join(blocks).strip()
    return f"{answer_text.rstrip()} [{citation_index}]".strip()


def inject_citation_indices(answer_text: str, *, citation_indices: list[int] | tuple[int, ...]) -> str:
    normalized_indices = [int(index) for index in citation_indices if int(index) > 0]
    if not normalized_indices:
        return answer_text.strip()
    if len(normalized_indices) == 1:
        return inject_single_citation(answer_text, citation_index=normalized_indices[0])

    citation_suffix = " " + " ".join(f"[{index}]" for index in normalized_indices)
    blocks = answer_text.split("\n\n")
    for index, block in enumerate(blocks):
        stripped = block.strip()
        if not stripped or stripped.startswith("```"):
            continue
        if CITATION_RE.search(stripped):
            return answer_text
        blocks[index] = f"{stripped}{citation_suffix}"
        return "\n\n".join(blocks).strip()
    return f"{answer_text.rstrip()}{citation_suffix}".strip()


def summarize_selected_citations(citations, retrieval_hits) -> list[dict[str, str | float | int]]:
    hit_by_chunk_id = {hit.chunk_id: hit for hit in retrieval_hits}
    summaries: list[dict[str, str | float | int]] = []
    for citation in citations:
        hit = hit_by_chunk_id.get(citation.chunk_id)
        summary: dict[str, str | float | int] = {
            "index": citation.index,
            "book_slug": citation.book_slug,
            "section": citation.section,
        }
        if hit is not None:
            summary["fused_score"] = round(float(hit.fused_score), 4)
            for key in ("bm25_score", "bm25_rank", "vector_score", "vector_rank"):
                if key in hit.component_scores:
                    summary[key] = round(float(hit.component_scores[key]), 4)
        summaries.append(summary)
    return summaries

def select_fallback_citations(
    citations,
    *,
    limit: int = 3,
) -> list:
    selected = []
    seen_identities: set[tuple[str, str]] = set()
    for citation in citations:
        identity = citation_identity(citation)
        if identity in seen_identities:
            continue
        seen_identities.add(identity)
        selected.append(replace(citation, index=len(selected) + 1))
        if len(selected) >= limit:
            break
    return selected


def _is_explicit_mixed_runtime_query(query: str) -> bool:
    lowered = (query or "").lower()
    has_private_signal = any(
        token in lowered
        for token in (
            "customer pack",
            "customer-pack",
            "our document",
        )
    ) or any(token in (query or "") for token in ("고객 문서", "고객문서", "우리 문서", "업로드 문서", "업로드한 문서"))
    has_official_signal = any(
        token in lowered
        for token in (
            "official runtime",
            "official document",
            "official docs",
        )
    ) or any(token in (query or "") for token in ("공식 runtime", "공식 문서", "공식 근거"))
    return has_private_signal and has_official_signal


def _citation_truth_bucket(citation) -> str:
    source_collection = str(getattr(citation, "source_collection", "") or "").strip().lower()
    if source_collection == "uploaded":
        return "private"
    return "official"
