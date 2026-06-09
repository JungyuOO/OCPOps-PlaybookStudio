from __future__ import annotations

from play_book_studio.http.viewer_blocks_rich import _render_code_block_html


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


def test_code_block_collapse_control_only_appears_for_long_code() -> None:
    medium_code = "\n".join(f"line {index}" for index in range(1, 20))
    long_code = "\n".join(f"line {index}" for index in range(1, 21))

    medium_rendered = _render_code_block_html(medium_code, language="text")
    long_rendered = _render_code_block_html(long_code, language="text")

    assert "collapse-button" not in medium_rendered
    assert 'class="code-block is-collapsible is-collapsed overflow-toggle"' in long_rendered
    assert 'aria-expanded="false"' in long_rendered
    assert "전체 보기 (20줄)" in long_rendered
    assert "접기 (20줄)" in long_rendered


def test_yaml_code_block_renders_korean_business_summary_as_prose() -> None:
    rendered = _render_code_block_html(
        "\n".join(
            [
                "고객사/서비스 개요고객사: 한빛리테일(Hanbit Retail)",
                "대상 시스템: 한빛페이 결제 API, 주문 이벤트 처리기, 백오피스 알림 서비스운영 목적: OpenShift 4.20 기반으로 결제 API 배포, PipelineRun 자동 생성, Route/Ingress 노출, PVC 상태와 Warning 이벤트를 일상 점검한다.",
            ]
        ),
        language="yaml",
    )

    assert 'class="code-block' not in rendered
    assert "<p>고객사/서비스 개요</p>" in rendered
    assert "<p>고객사: 한빛리테일(Hanbit Retail)</p>" in rendered
    assert "운영 목적: OpenShift 4.20" in rendered
