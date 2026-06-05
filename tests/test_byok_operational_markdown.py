from __future__ import annotations

import json
from pathlib import Path

from play_book_studio.byok.operational_markdown import (
    build_byok_export,
    evaluate_byok_markdown,
    generate_operational_markdown,
)


SOURCE_TEXT = """
# KOSCOM PVC Pending Troubleshooting

PVC가 Pending 상태이면 StorageClass와 provisioner 상태를 확인한다.

oc describe pvc data -n koscom-app
oc get sc
oc get pods -A | grep -i provisioner
"""


def test_generate_operational_markdown_creates_lightspeed_byok_shape() -> None:
    markdown = generate_operational_markdown(
        SOURCE_TEXT,
        title="KOSCOM PVC Pending Troubleshooting",
        internal_url="internal://koscom/ocp/pvc-pending",
        customer="koscom",
        topic="storage",
        keywords=["pvc", "pending", "storageclass"],
    )

    assert markdown.startswith("---")
    assert 'title: "KOSCOM PVC Pending Troubleshooting"' in markdown
    assert 'url: "internal://koscom/ocp/pvc-pending"' in markdown
    assert "# KOSCOM PVC Pending Troubleshooting" in markdown
    assert "## 상황" in markdown
    assert "## 증상" in markdown
    assert "## 확인 순서" in markdown
    assert "## 판단 기준" in markdown
    assert "## 조치 방향" in markdown
    assert "## 관련 명령" in markdown
    assert "```bash\noc describe pvc data -n koscom-app" in markdown


def test_evaluate_byok_markdown_requires_operational_quality() -> None:
    markdown = generate_operational_markdown(
        SOURCE_TEXT,
        title="KOSCOM PVC Pending Troubleshooting",
        internal_url="internal://koscom/ocp/pvc-pending",
        customer="koscom",
        topic="storage",
    )

    gate = evaluate_byok_markdown(markdown)

    assert gate.passed is True
    assert gate.score == 100
    assert gate.warnings == []


def test_build_byok_export_writes_manifest_build_request_and_patch_preview(tmp_path: Path) -> None:
    result = build_byok_export(
        root_dir=tmp_path,
        document_id="doc-1",
        source_text=SOURCE_TEXT,
        title="KOSCOM PVC Pending Troubleshooting",
        customer="koscom",
        topic="storage",
        image_repository="registry.example.test/pbs/byok",
    )

    markdown_path = tmp_path / result.markdown_path
    manifest_path = tmp_path / result.manifest_path
    build_request_path = tmp_path / result.build_request_path
    patch_preview_path = tmp_path / result.olsconfig_patch_preview_path

    assert markdown_path.is_file()
    assert manifest_path.is_file()
    assert build_request_path.is_file()
    assert patch_preview_path.is_file()
    assert result.quality_gate.passed is True

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    document = manifest["documents"][0]
    assert document["document_id"] == "doc-1"
    assert document["markdown_path"] == result.markdown_path
    assert document["target_knowledge_image"] == f"registry.example.test/pbs/byok:{result.image_tag}"
    assert document["quality_gate"]["passed"] is True

    build_request = json.loads(build_request_path.read_text(encoding="utf-8"))
    assert build_request["mode"] == "dry-run"
    assert build_request["image_repository"] == "registry.example.test/pbs/byok"
    assert build_request["image_tag"] == result.image_tag
    assert f"registry.example.test/pbs/byok:{result.image_tag}" in patch_preview_path.read_text(encoding="utf-8")
