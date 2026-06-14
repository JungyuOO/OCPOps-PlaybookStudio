from __future__ import annotations

from play_book_studio.ingestion.internal_markup import render_internal_markup_for_retrieval


def test_render_internal_markup_for_retrieval_converts_code_tags_to_markdown() -> None:
    rendered = render_internal_markup_for_retrieval(
        'Before\n[CODE language="shell-session" caption="확인 명령"]\n$ oc get ns\n[/CODE]\nAfter'
    )

    assert "[CODE" not in rendered
    assert "[/CODE]" not in rendered
    assert "확인 명령" in rendered
    assert "```shell" in rendered
    assert "$ oc get ns" in rendered


def test_render_internal_markup_for_retrieval_removes_table_tags_but_keeps_content() -> None:
    rendered = render_internal_markup_for_retrieval(
        '[TABLE caption="필드"]\n이름 | 설명\nnamespace | 프로젝트\n[/TABLE]'
    )

    assert "[TABLE" not in rendered
    assert "[/TABLE]" not in rendered
    assert "필드" in rendered
    assert "namespace | 프로젝트" in rendered
