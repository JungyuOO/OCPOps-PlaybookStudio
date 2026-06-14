from __future__ import annotations

from play_book_studio.config.corpus_policy import chunk_profile_for_section


def test_chunk_profile_for_section_keeps_command_chunks_smaller_than_default() -> None:
    chunk_size, overlap = chunk_profile_for_section(
        "installing_on_any_platform",
        semantic_role="procedure",
        has_cli_commands=True,
        default_chunk_size=160,
        default_chunk_overlap=32,
    )

    assert chunk_size == 256
    assert overlap == 32


def test_chunk_profile_for_section_preserves_concept_context() -> None:
    chunk_size, overlap = chunk_profile_for_section(
        "architecture",
        semantic_role="concept",
        default_chunk_size=160,
        default_chunk_overlap=32,
    )

    assert chunk_size == 320
    assert overlap == 32
