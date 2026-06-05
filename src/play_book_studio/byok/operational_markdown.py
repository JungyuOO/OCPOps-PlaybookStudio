from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REQUIRED_OPERATIONAL_SECTIONS = (
    "상황",
    "증상",
    "확인 순서",
    "판단 기준",
    "조치 방향",
    "관련 명령",
)
COMMAND_RE = re.compile(r"^\s*(?:\$?\s*)?(oc|kubectl)\s+.+", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class BYOKQualityGate:
    passed: bool
    score: int
    checks: dict[str, bool]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BYOKExportResult:
    document_id: str
    markdown_path: str
    manifest_path: str
    build_request_path: str
    olsconfig_patch_preview_path: str
    quality_gate: BYOKQualityGate
    content_hash: str
    image_repository: str
    image_tag: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["quality_gate"] = self.quality_gate.to_dict()
        return payload


def _now_tag() -> str:
    return datetime.now(UTC).strftime("%Y%m%d%H%M%S")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9가-힣]+", "-", str(value or "").strip().lower())
    slug = slug.strip("-")
    return slug or "document"


def _extract_title(source_text: str, fallback: str) -> str:
    for line in str(source_text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or fallback
    return fallback


def _extract_commands(source_text: str) -> list[str]:
    commands: list[str] = []
    seen: set[str] = set()
    for line in str(source_text or "").splitlines():
        stripped = line.strip()
        if COMMAND_RE.match(stripped):
            command = stripped.removeprefix("$").strip()
            if command not in seen:
                seen.add(command)
                commands.append(command)
    return commands


def _front_matter(metadata: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in metadata.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            lines.extend(f"  - {item}" for item in value)
        else:
            escaped = str(value).replace('"', '\\"')
            lines.append(f'{key}: "{escaped}"')
    lines.append("---")
    return "\n".join(lines)


def _source_excerpt(source_text: str, *, max_chars: int = 900) -> str:
    collapsed = re.sub(r"\n{3,}", "\n\n", str(source_text or "").strip())
    return collapsed[:max_chars].strip()


def generate_operational_markdown(
    source_text: str,
    *,
    title: str = "",
    internal_url: str = "",
    customer: str = "",
    product: str = "openshift",
    version: str = "4.x",
    topic: str = "operations",
    source_type: str = "troubleshooting",
    keywords: list[str] | None = None,
) -> str:
    resolved_title = title.strip() or _extract_title(source_text, "PBS Uploaded Operational Document")
    resolved_url = internal_url.strip() or f"internal://pbs/library/{_slugify(resolved_title)}"
    commands = _extract_commands(source_text)
    keyword_values = keywords or sorted(
        {
            topic,
            source_type,
            "openshift",
            "ocp",
            *[command.split()[1] for command in commands if len(command.split()) > 1],
        }
    )
    metadata = {
        "title": resolved_title,
        "url": resolved_url,
        "source_type": source_type,
        "customer": customer or "default",
        "product": product,
        "version": version,
        "topic": topic,
        "keywords": keyword_values,
    }
    command_block = "\n".join(commands) if commands else "oc get events -n <namespace> --sort-by=.lastTimestamp"
    excerpt = _source_excerpt(source_text)
    return "\n\n".join(
        [
            _front_matter(metadata),
            f"# {resolved_title}",
            "## 상황\n\n업로드된 고객사 문서를 OpenShift 운영 절차로 재구성한 Lightspeed BYO Knowledge 문서입니다.",
            "## 증상\n\n- 사용자가 질문할 수 있는 증상, 리소스 이름, 오류 문자열을 원문에서 확인한다.\n- 관련 리소스의 상태와 event를 함께 확인한다.",
            f"## 확인 순서\n\n1. 관련 리소스와 namespace를 확인한다.\n\n```bash\n{command_block}\n```",
            "2. 최근 event와 상태 변화를 확인한다.\n\n```bash\noc get events -n <namespace> --sort-by=.lastTimestamp\n```",
            "## 판단 기준\n\n원문에 나온 증상과 현재 클러스터 event, 리소스 status, CLI 출력이 같은 방향을 가리키면 해당 runbook을 우선 적용한다.",
            "## 조치 방향\n\n- apply 또는 patch 전에는 diff와 dry-run 결과를 확인한다.\n- 실패한 명령의 stdout, stderr, exit code를 PBS 이벤트 타임라인에 남긴다.\n- 조치 후 관련 Pod, Deployment, Event 상태를 다시 확인한다.",
            f"## 관련 명령\n\n```bash\n{command_block}\n```",
            f"## 원문 요약\n\n{excerpt or '원문 텍스트가 비어 있습니다.'}",
        ]
    )


def evaluate_byok_markdown(markdown: str) -> BYOKQualityGate:
    checks = {
        "front_matter": markdown.strip().startswith("---"),
        "h1": bool(re.search(r"^#\s+\S", markdown, flags=re.MULTILINE)),
        "required_sections": all(f"## {section}" in markdown for section in REQUIRED_OPERATIONAL_SECTIONS),
        "bash_fence": "```bash" in markdown,
        "internal_url": "url: \"internal://" in markdown,
        "query_terms": any(term in markdown.lower() for term in ("ocp", "openshift", "pod", "deployment", "pvc", "event")),
        "decision_rule": "## 판단 기준" in markdown and len(markdown.split("## 판단 기준", 1)[1].strip()) > 40,
    }
    score = round(sum(1 for passed in checks.values() if passed) / len(checks) * 100)
    warnings = [name for name, passed in checks.items() if not passed]
    return BYOKQualityGate(passed=score >= 85 and not warnings, score=score, checks=checks, warnings=warnings)


def build_byok_export(
    *,
    root_dir: Path,
    document_id: str,
    source_text: str,
    title: str,
    customer: str = "default",
    topic: str = "operations",
    image_repository: str = "",
) -> BYOKExportResult:
    markdown = generate_operational_markdown(
        source_text,
        title=title,
        internal_url=f"internal://{_slugify(customer)}/ocp/{_slugify(title)}",
        customer=customer,
        topic=topic,
    )
    quality_gate = evaluate_byok_markdown(markdown)
    content_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    image_repo = image_repository or "registry.example.com/pbs/pbs-knowledge"
    image_tag = f"byok-{_slugify(customer)}-{content_hash[:12]}"
    byok_root = root_dir / "storage" / "byok"
    generated_path = byok_root / "generated" / _slugify(customer) / _slugify(topic) / f"{_slugify(title)}.md"
    manifest_path = byok_root / "manifests" / "byok-export-manifest.json"
    build_request_path = byok_root / "manifests" / "byok-build-request.json"
    patch_preview_path = byok_root / "manifests" / "olsconfig-patch-preview.yaml"
    generated_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    generated_path.write_text(markdown, encoding="utf-8")
    manifest = {
        "schema_version": "pbs_byok_export_manifest_v1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "documents": [
            {
                "document_id": document_id,
                "markdown_path": str(generated_path.relative_to(root_dir)).replace("\\", "/"),
                "title": title,
                "internal_url": f"internal://{_slugify(customer)}/ocp/{_slugify(title)}",
                "customer": customer,
                "product": "openshift",
                "version": "4.x",
                "topic": topic,
                "source_type": "troubleshooting",
                "quality_gate": quality_gate.to_dict(),
                "content_hash": content_hash,
                "target_knowledge_image": f"{image_repo}:{image_tag}",
                "olsconfig_patch_preview_path": str(patch_preview_path.relative_to(root_dir)).replace("\\", "/"),
            }
        ],
    }
    build_request = {
        "schema_version": "pbs_byok_build_request_v1",
        "mode": "dry-run",
        "corpus_root": str((byok_root / "generated").relative_to(root_dir)).replace("\\", "/"),
        "image_repository": image_repo,
        "image_tag": image_tag,
        "source_manifest": str(manifest_path.relative_to(root_dir)).replace("\\", "/"),
    }
    patch_preview = "\n".join(
        [
            "apiVersion: ols.openshift.io/v1alpha1",
            "kind: OLSConfig",
            "metadata:",
            "  name: cluster",
            "spec:",
            "  ols:",
            "    rag:",
            "      - image: " + f"{image_repo}:{image_tag}",
        ]
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    build_request_path.write_text(json.dumps(build_request, ensure_ascii=False, indent=2), encoding="utf-8")
    patch_preview_path.write_text(patch_preview + "\n", encoding="utf-8")
    return BYOKExportResult(
        document_id=document_id,
        markdown_path=str(generated_path.relative_to(root_dir)).replace("\\", "/"),
        manifest_path=str(manifest_path.relative_to(root_dir)).replace("\\", "/"),
        build_request_path=str(build_request_path.relative_to(root_dir)).replace("\\", "/"),
        olsconfig_patch_preview_path=str(patch_preview_path.relative_to(root_dir)).replace("\\", "/"),
        quality_gate=quality_gate,
        content_hash=content_hash,
        image_repository=image_repo,
        image_tag=image_tag,
    )


__all__ = [
    "BYOKExportResult",
    "BYOKQualityGate",
    "build_byok_export",
    "evaluate_byok_markdown",
    "generate_operational_markdown",
]
