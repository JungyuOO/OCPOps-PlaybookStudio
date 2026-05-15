from __future__ import annotations

from play_book_studio.ingestion.page_stub_repair import repair_page_stub_headings


def test_page_stub_repair_removes_converter_page_headings_but_keeps_comments_and_content() -> None:
    markdown = "# RBAC\n\n<!-- page: 6 -->\n## Page 6\n\n본문\n\n<!-- page: 7 -->\n## Page 7\n\n![page](asset://a)"

    result = repair_page_stub_headings(markdown)

    assert result.changed is True
    assert result.changed_block_count == 2
    assert "<!-- page: 6 -->" in result.repaired_markdown
    assert "본문" in result.repaired_markdown
    assert "asset://a" in result.repaired_markdown
    assert "## Page 6" not in result.repaired_markdown
    assert result.diff_summary[0].page_number == 6


def test_page_stub_repair_does_not_remove_real_page_named_sections() -> None:
    markdown = "# Guide\n\n## Page cache tuning\n\n실제 섹션"

    result = repair_page_stub_headings(markdown)

    assert result.changed is False
    assert result.repaired_markdown == markdown
