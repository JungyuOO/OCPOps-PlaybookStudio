from __future__ import annotations

from play_book_studio.app.viewer_blocks_rich import _render_code_block_html


def test_code_block_copy_avoids_duplicate_data_payload_for_default_copy_text() -> None:
    code = "spec:\n  schedule: 0 0 * * *\n  suspend: false"

    rendered = _render_code_block_html(code, language="yaml")

    assert 'class="copy-button icon-button"' in rendered
    assert "data-copy=" not in rendered
    assert 'class="code-token code-key">spec:</span>' in rendered


def test_code_block_copy_keeps_custom_copy_text_payload_when_needed() -> None:
    rendered = _render_code_block_html("$ oc get pod\npod/example", language="shell", copy_text="oc get pod")

    assert "data-copy=" in rendered
    assert "oc get pod" in rendered
