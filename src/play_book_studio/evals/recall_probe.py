"""Stage-1 hybrid recall measurement helpers.

The probe evaluates retrieval evidence before answer generation, so it can
catch misses that book-level hit metrics hide.
"""
from __future__ import annotations

from play_book_studio.retrieval.models import RetrievalHit


def hit_matches_case(hit: RetrievalHit, case: dict) -> bool:
    """Return True when a retrieval hit satisfies a case expectation."""
    expect_chunk_ids = {str(chunk_id) for chunk_id in case.get("expect_chunk_ids", []) if str(chunk_id)}
    if expect_chunk_ids and hit.chunk_id in expect_chunk_ids:
        return True

    expect_book = str(case.get("expect_book", "")).strip()
    section_needle = str(case.get("expect_section_contains", "")).strip()
    if expect_book:
        return hit.book_slug == expect_book and (not section_needle or section_needle in hit.section)

    command_needle = str(case.get("expect_command", "")).strip()
    if command_needle:
        if any(command_needle in command for command in hit.cli_commands):
            return True
        if command_needle in hit.text:
            return True

    if section_needle:
        return section_needle in hit.section

    return False


def rank_in_hits(hits: list[RetrievalHit], case: dict) -> int | None:
    """Return the 1-based rank of the first matching hit, or None."""
    for index, hit in enumerate(hits, start=1):
        if hit_matches_case(hit, case):
            return index
    return None
