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


def test_normalizes_pdf_prose_spacing_without_touching_code_syntax() -> None:
    markdown = """구분 RBAC Role-Based Access
Control) SCC Security Context Constraints)
SCC 는  OpenShift 에서  Pod 의  보안  컨텍스트를  제어합니다.
User IDUID 범위를 지정합니다.
restricted: 가장  엄격한  제한  ( 기본값 ).
# 특정  프로젝트의  서비스  계정 (my-sa) 에  anyuid SCC 권한  추가

```yaml
readOnlyRootFilesystem: false     # 루트  파일시스템  읽기  전용
```
"""

    result = repair_pdf_text_artifacts(markdown)

    assert result.changed is True
    assert "RBAC (Role-Based Access Control)" in result.repaired_markdown
    assert "SCC (Security Context Constraints)" in result.repaired_markdown
    assert "SCC 는 OpenShift 에서 Pod 의 보안 컨텍스트를 제어합니다." in result.repaired_markdown
    assert "User ID(UID) 범위를 지정합니다." in result.repaired_markdown
    assert "restricted: 가장 엄격한 제한 (기본값)." in result.repaired_markdown
    assert "# 특정 프로젝트의 서비스 계정 (my-sa) 에 anyuid SCC 권한 추가" in result.repaired_markdown
    assert "readOnlyRootFilesystem: false     # 루트 파일시스템 읽기 전용" in result.repaired_markdown
    quoted_hash_result = repair_pdf_text_artifacts(
        '```yaml\nurl: "https://example.com/a#  section"\nannotation: "a#  b"\n```\n'
    )
    assert "url: \"https://example.com/a#  section\"" in quoted_hash_result.repaired_markdown
    assert "annotation: \"a#  b\"" in quoted_hash_result.repaired_markdown


def test_joins_parenthetical_terms_and_short_question_fragments() -> None:
    markdown = """RBAC (Role-Based Access
Control)
SCC (Security Context
Constraints)
"이 Pod가 루트 권한으로 실행될 수 있는
가?"
"""

    result = repair_pdf_text_artifacts(markdown)

    assert result.changed is True
    assert "RBAC (Role-Based Access Control)" in result.repaired_markdown
    assert "SCC (Security Context Constraints)" in result.repaired_markdown
    assert "실행될 수 있는가?" in result.repaired_markdown
