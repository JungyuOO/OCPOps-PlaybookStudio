from __future__ import annotations

from play_book_studio.ingestion.code_block_repair import repair_unfenced_code_blocks


def test_repairs_unfenced_deployment_yaml():
    markdown = """# Deployment

kind: Deployment
metadata:
  name: my-app
spec:
  replicas: 1

설명 문장입니다.
"""

    result = repair_unfenced_code_blocks(markdown)

    assert result.changed is True
    assert result.changed_block_count == 1
    assert "```yaml\nkind: Deployment\nmetadata:" in result.repaired_markdown
    assert "spec:\n  replicas: 1\n```" in result.repaired_markdown


def test_repairs_kubernetes_yaml_scalar_lists():
    markdown = """# RBAC

kind: Role
metadata:
  name: pod-reader
rules:
- apiGroups: [""]
  resources:
  - pods
  verbs:
  - get
  - list
"""

    result = repair_unfenced_code_blocks(markdown)

    assert result.changed is True
    assert "  resources:\n  - pods\n  verbs:\n  - get\n  - list\n```" in result.repaired_markdown


def test_repairs_oc_and_kubectl_commands_as_bash():
    markdown = """# Commands

oc get pods -n openshift-image-registry
kubectl apply -f deployment.yaml

다음 단계로 넘어갑니다.
"""

    result = repair_unfenced_code_blocks(markdown)

    assert result.changed is True
    assert result.changed_block_count == 1
    assert "```bash\noc get pods" in result.repaired_markdown
    assert "kubectl apply -f deployment.yaml\n```" in result.repaired_markdown


def test_absorbs_wrapped_command_continuation():
    markdown = """# Commands

$ oc import-image my-python-app:latest --from=quay.io/my-re
po/python-app:v1 --confirm

다음 단계입니다.
"""

    result = repair_unfenced_code_blocks(markdown)

    assert result.changed is True
    assert "$ oc import-image my-python-app:latest --from=quay.io/my-re\npo/python-app:v1 --confirm" in result.repaired_markdown
    assert result.repaired_markdown.count("```bash") == 1


def test_absorbs_wrapped_continuation_after_existing_bash_fence():
    markdown = """# Commands

```bash
$ oc import-image my-python-app:latest --from=quay.io/my-re
```
po/python-app:v1 --confirm
"""

    result = repair_unfenced_code_blocks(markdown)

    assert result.changed is True
    assert "po/python-app:v1 --confirm\n```" in result.repaired_markdown


def test_does_not_absorb_prose_after_existing_curl_fence():
    markdown = """# Command

```bash
curl https://example.com/api
```
Result: 요청이 정상 처리됩니다.
"""

    result = repair_unfenced_code_blocks(markdown)

    assert result.changed is False
    assert "```\nResult:" in result.repaired_markdown


def test_does_not_double_fence_existing_code():
    markdown = """# Deployment

```yaml
kind: Deployment
metadata:
  name: my-app
```
"""

    result = repair_unfenced_code_blocks(markdown)

    assert result.changed is False
    assert result.repaired_markdown.count("```yaml") == 1


def test_tracks_long_fence_without_toggling_on_inner_short_fence():
    markdown = """# Fences

````markdown
```yaml
kind: Deployment
metadata:
  name: my-app
```
````
"""

    result = repair_unfenced_code_blocks(markdown)

    assert result.changed is False
    assert result.repaired_markdown.count("```yaml") == 1


def test_does_not_treat_short_colon_prose_as_yaml():
    markdown = """# Overview

주의: 이 문서는 테스트 설명입니다.
목표: 운영자가 ImageStream을 이해합니다.

| 항목 | 값 |
| --- | --- |
| kind: Deployment | 설명 |
"""

    result = repair_unfenced_code_blocks(markdown)

    assert result.changed is False
    assert "```yaml" not in result.repaired_markdown


def test_does_not_treat_capitalized_command_words_as_bash_prose():
    markdown = """# Prose

Export controls are handled by the security team.
Docker images are stored in the registry.
"""

    result = repair_unfenced_code_blocks(markdown)

    assert result.changed is False
    assert "```bash" not in result.repaired_markdown
