from __future__ import annotations

from play_book_studio.answering.answerer import _grounding_caveat_note


def test_grounding_caveat_note_is_non_empty_warning_text():
    note = _grounding_caveat_note("insufficient command grounding coverage")
    assert note
    assert "근거" in note
