from play_book_studio.canonical.html import _blocks_from_text
from play_book_studio.canonical.models import CodeBlock


def _code_blocks(text: str) -> list[CodeBlock]:
    return [block for block in _blocks_from_text(text) if isinstance(block, CodeBlock)]


def test_html_code_block_keeps_command_and_removes_callout_and_output() -> None:
    blocks = _code_blocks(
        """
        [CODE language="text"]
        oc describe pvc <pvc_name> 1
        이전 단계에서 생성한 PVC의 이름입니다
        Name: pvc-test
        Status: Bound
        [/CODE]
        """
    )

    assert len(blocks) == 1
    assert blocks[0].code == "oc describe pvc <pvc_name>"
    assert blocks[0].copy_text == "oc describe pvc <pvc_name>"


def test_html_code_block_removes_attached_callout_after_placeholder() -> None:
    blocks = _code_blocks(
        """
        [CODE language="text"]
        oc describe pvc <pvc_name>1
        Name: pvc-test
        [/CODE]
        """
    )

    assert len(blocks) == 1
    assert blocks[0].code == "oc describe pvc <pvc_name>"


def test_html_code_block_keeps_multiple_command_lines_before_output() -> None:
    blocks = _code_blocks(
        """
        [CODE language="text"]
        $ oc get pvc -n demo
        $ oc describe pvc data -n demo
        NAME STATUS
        data Bound
        [/CODE]
        """
    )

    assert len(blocks) == 1
    assert blocks[0].code == "oc get pvc -n demo\noc describe pvc data -n demo"
