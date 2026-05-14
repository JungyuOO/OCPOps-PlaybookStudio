from __future__ import annotations

from play_book_studio.ingestion.pdf_text_repair import repair_pdf_text_artifacts


def test_removes_page_markers_and_short_footers() -> None:
    markdown = """# SCC

설명 본문입니다.

SCC
2

<!-- page: 3 -->

다음 본문입니다.
"""

    result = repair_pdf_text_artifacts(markdown)

    assert result.changed is True
    assert "SCC\n2" not in result.repaired_markdown
    assert "<!-- page: 3 -->" not in result.repaired_markdown
    assert "설명 본문입니다." in result.repaired_markdown
    assert "다음 본문입니다." in result.repaired_markdown


def test_joins_fragments_split_by_pdf_page_boundary() -> None:
    markdown = """```bash
$ oc adm policy add-scc-to-user anyuid -z my-sa -n my-proje
```

SCC
2

<!-- page: 3 -->

ct

```bash
$ oc adm policy add-scc-to-user privileged -z logging-sa -n
```

SCC
3

logging-project
"""

    result = repair_pdf_text_artifacts(markdown)

    assert result.changed is True
    assert "$ oc adm policy add-scc-to-user anyuid -z my-sa -n my-project" in result.repaired_markdown
    assert "$ oc adm policy add-scc-to-user privileged -z logging-sa -n logging-project" in result.repaired_markdown
    assert "\nct\n" not in result.repaired_markdown
    assert "SCC\n3" not in result.repaired_markdown


def test_joins_short_korean_pdf_fragments_inside_yaml_fence() -> None:
    markdown = """```yaml
allowHostDirVolumePlugin: false  # hostPath 볼륨 사용 금
```

SCC
4

지

```yaml
serviceAccountName: app-sa  # SA 지
```

정
"""

    result = repair_pdf_text_artifacts(markdown)

    assert result.changed is True
    assert "사용 금지" in result.repaired_markdown
    assert "SA 지정" in result.repaired_markdown


def test_joins_yaml_comment_fragments_split_by_pdf_wrapping() -> None:
    markdown = """allowHostIPC: false               # 호스트  IPC 네임스페이스  공
유  금지
allowPrivilegedContainer: false   # 특권  컨테이너 (Privileged)
금지
readOnlyRootFilesystem: false     # 루트  파일시스템  읽기  전용
강제  여부
runAsUser:                        # 유저  ID 실행  정책
  type: MustRunAsRange            # 허용된  범위  내의  UID 만  사
용  가능
users: []                         # 이  SCC 를  직접  사용할  유저
( 보안상  비워둠 )
"""

    result = repair_pdf_text_artifacts(markdown)

    assert result.changed is True
    assert "네임스페이스  공유  금지" in result.repaired_markdown
    assert "(Privileged) 금지" in result.repaired_markdown
    assert "전용 강제  여부" in result.repaired_markdown
    assert "UID 만  사용  가능" in result.repaired_markdown
    assert "유저 ( 보안상  비워둠 )" in result.repaired_markdown


def test_does_not_join_numbered_section_heading_as_fragment() -> None:
    markdown = """privileged: 모든 권한 허용
2. RBAC vs SCC 차이점
"""

    result = repair_pdf_text_artifacts(markdown)

    assert result.changed is False
    assert "허용\n2. RBAC" in result.repaired_markdown


def test_joins_fragment_across_preserved_page_heading() -> None:
    markdown = """$ oc adm policy add-scc-to-user anyuid -z my-sa -n my-proje

SCC
2

## Page 3

ct
"""

    result = repair_pdf_text_artifacts(markdown)

    assert "$ oc adm policy add-scc-to-user anyuid -z my-sa -n my-project" in result.repaired_markdown
    assert "## Page 3" in result.repaired_markdown
    assert "\nct\n" not in result.repaired_markdown
