from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from play_book_studio.config.settings import Settings
from play_book_studio.ingestion.approval_report import build_source_approval_report
from play_book_studio.ingestion.manifest import read_manifest, runtime_catalog_entries, write_manifest
from play_book_studio.ingestion.models import CONTENT_STATUS_TRANSLATED_KO_DRAFT, SourceManifestEntry
from play_book_studio.ingestion.translation_draft_generation import generate_translation_drafts


HEADING_NUMBER_PREFIX_RE = re.compile(
    r"^\s*(?:chapter\s+\d+\.?\s*|\d+\s*장\.?\s*|(?:\d+|[A-Za-z])(?:\.\d+)*\.?\s+)",
    re.IGNORECASE,
)
LABEL_ONLY_RE = re.compile(r"^(중요|참고|팁|주의|경고|선행 조건|사전 요구 사항|사전 조건|절차|예상 출력)$")


@dataclass(slots=True)
class ReaderGradeOutput:
    slug: str
    title: str
    output_path: Path
    section_count: int


def _draft_entry(entry: SourceManifestEntry, approval_book: dict[str, Any]) -> SourceManifestEntry:
    source_language = (
        entry.translation_source_language
        or entry.resolved_language
        or entry.docs_language
        or "ko"
    ).strip() or "ko"
    payload = entry.to_dict()
    payload.update(
        {
            "resolved_source_url": str(
                approval_book.get("resolved_source_url") or entry.resolved_source_url or entry.source_url
            ),
            "fallback_detected": bool(approval_book.get("fallback_detected", entry.fallback_detected)),
            "body_language_guess": str(approval_book.get("body_language_guess") or entry.body_language_guess),
            "translation_source_language": (
                "en"
                if str(approval_book.get("body_language_guess") or entry.body_language_guess) in {"en_only", "mixed"}
                else source_language
            ),
            "content_status": CONTENT_STATUS_TRANSLATED_KO_DRAFT,
            "citation_eligible": False,
            "citation_block_reason": "translated Korean draft requires review before citation",
            "approval_status": "needs_review",
            "approval_notes": "machine translation draft scheduled for reader-grade generation",
            "resolved_language": source_language,
            "translation_target_language": "ko",
            "translation_source_url": entry.resolved_source_url or entry.source_url,
            "translation_source_fingerprint": entry.source_fingerprint,
            "translation_stage": CONTENT_STATUS_TRANSLATED_KO_DRAFT,
        }
    )
    return SourceManifestEntry(**payload)


def ensure_translation_manifest(settings: Settings, slugs: list[str]) -> Path:
    approval_report = build_source_approval_report(settings)
    books_by_slug = {str(item["book_slug"]): item for item in approval_report["books"]}
    catalog_entries = runtime_catalog_entries(read_manifest(settings.source_catalog_path), settings)
    catalog_by_slug = {entry.book_slug: entry for entry in catalog_entries}
    selected: list[SourceManifestEntry] = []
    for slug in slugs:
        entry = catalog_by_slug[slug]
        selected.append(_draft_entry(entry, books_by_slug.get(slug, {})))
    write_manifest(settings.translation_draft_manifest_path, selected)
    return settings.translation_draft_manifest_path


def _clean_heading(text: str) -> str:
    raw = " ".join(str(text or "").split()).strip()
    cleaned = HEADING_NUMBER_PREFIX_RE.sub("", raw).strip()
    return cleaned or raw


def _section_body(section: dict[str, Any], *, max_blocks: int = 12) -> str:
    blocks = [dict(block) for block in (section.get("blocks") or []) if isinstance(block, dict)]
    rendered: list[str] = []
    pending_label = ""
    for block in blocks[:max_blocks]:
        kind = str(block.get("kind") or "").strip()
        if kind == "paragraph":
            text = str(block.get("text") or "").strip()
            if not text:
                continue
            if LABEL_ONLY_RE.match(text):
                pending_label = text
                continue
            if pending_label:
                rendered.append(f"> **{pending_label}**\n> {text}")
                pending_label = ""
            else:
                rendered.append(text)
            continue
        if kind == "code":
            code = str(block.get("code") or "").rstrip()
            if not code:
                continue
            language = str(block.get("language") or "text").strip() or "text"
            if pending_label:
                rendered.append(f"### {pending_label}")
                pending_label = ""
            rendered.append(f"```{language}\n{code}\n```")
            continue
        if kind == "prerequisite":
            items = [str(item).strip() for item in (block.get("items") or []) if str(item).strip()]
            if items:
                if pending_label:
                    rendered.append(f"### {pending_label}")
                    pending_label = ""
                rendered.append("\n".join(f"- {item}" for item in items))
            continue
        if kind == "procedure":
            lines: list[str] = []
            for index, step in enumerate(block.get("steps") or [], start=1):
                text = str(step.get("text") or "").strip()
                if text:
                    lines.append(f"{index}. {text}")
                for substep in (step.get("substeps") or []):
                    normalized = str(substep).strip()
                    if normalized:
                        lines.append(f"   - {normalized}")
            if lines:
                if pending_label:
                    rendered.append(f"### {pending_label}")
                    pending_label = ""
                rendered.append("\n".join(lines))
            continue
        if kind == "note":
            title = str(block.get("title") or pending_label or "참고").strip() or "참고"
            text = str(block.get("text") or "").strip()
            if text:
                rendered.append(f"> **{title}**\n> {text}")
            pending_label = ""
            continue
        if kind == "table":
            headers = [str(item).strip() for item in (block.get("headers") or [])]
            rows = [[str(cell).strip() for cell in row] for row in (block.get("rows") or [])]
            if headers:
                rendered.append("| " + " | ".join(headers) + " |")
                rendered.append("| " + " | ".join("---" for _ in headers) + " |")
            for row in rows:
                rendered.append("| " + " | ".join(row) + " |")
            pending_label = ""
    return "\n\n".join(part for part in rendered if part).strip()


def _find_section(sections: list[dict[str, Any]], predicate) -> dict[str, Any]:
    for section in sections:
        if predicate(_clean_heading(str(section.get("heading") or ""))):
            return section
    return {}


def _render_backup_and_restore(sections: list[dict[str, Any]]) -> tuple[str, int]:
    selected = {
        "overview": _find_section(sections, lambda h: h == "컨트롤 플레인 백업 및 복원 작업"),
        "backup_overview": _find_section(sections, lambda h: h == "etcd 백업"),
        "backup_steps": _find_section(sections, lambda h: h == "etcd 데이터 백업"),
        "dr_overview": _find_section(sections, lambda h: h == "재해 복구 개요"),
        "restore_overview": _find_section(sections, lambda h: h == "이전 클러스터 상태로 복원하기"),
        "manual_restore": _find_section(sections, lambda h: h == "etcd 백업에서 수동으로 클러스터 복원"),
        "failure_signals": _find_section(sections, lambda h: h == "지속 가능한 저장 상태 복원에 대한 문제 및 우회 방법"),
    }
    text = f"""# Backup and Restore

## Overview

이 문서는 OpenShift control plane 작업 전에 필요한 etcd 백업 절차와, 백업본에서 클러스터를 수동으로 복구하는 핵심 절차를 정리한다.

{_section_body(selected["overview"], max_blocks=4)}

## Before You Begin

{_section_body(selected["backup_overview"], max_blocks=6)}

## Back Up etcd Data

{_section_body(selected["backup_steps"], max_blocks=16)}

## Restore Cluster State

{_section_body(selected["restore_overview"], max_blocks=10)}

## Manual Restore from etcd Backup

{_section_body(selected["manual_restore"], max_blocks=24)}

## Failure Signals

{_section_body(selected["failure_signals"], max_blocks=10)}

## Source Trace

- 원문 slug: `backup_and_restore`
- 기준 축: `etcd backup / manual restore / failure signals`
"""
    return text.strip() + "\n", sum(1 for value in selected.values() if value)


def _render_installing_any_platform(sections: list[dict[str, Any]]) -> tuple[str, int]:
    selected = {
        "overview": _find_section(sections, lambda h: h == "어떤 플랫폼에서도 클러스터 설치하기"),
        "prereq": _find_section(sections, lambda h: h == "사전 요구 사항"),
        "prepare": _find_section(sections, lambda h: h == "사용자 제공 인프라 준비"),
        "install_config": _find_section(sections, lambda h: h == "설치 구성 파일을 수동으로 생성"),
        "manifests": _find_section(sections, lambda h: h == "Kubernetes 매니페스트 및 Ignition 설정 파일 생성"),
        "bootstrap": _find_section(sections, lambda h: h == "RHCOS 설치 및 OpenShift Container Platform 부트스트랩 프로세스 시작"),
        "wait": _find_section(sections, lambda h: h == "부트스트랩 프로세스 완료 대기"),
    }
    text = f"""# Install on Any Platform

## Overview

이 문서는 사용자 제공 인프라 환경에서 OpenShift Container Platform 설치 자산을 준비하고, 부트스트랩이 완료될 때까지 확인해야 하는 핵심 절차를 정리한다.

{_section_body(selected["overview"], max_blocks=4)}

## Before You Begin

{_section_body(selected["prereq"], max_blocks=6)}

## Prepare the Infrastructure

{_section_body(selected["prepare"], max_blocks=6)}

## Create install-config.yaml

{_section_body(selected["install_config"], max_blocks=10)}

## Generate Manifests and Ignition Files

{_section_body(selected["manifests"], max_blocks=12)}

## Start Bootstrap

{_section_body(selected["bootstrap"], max_blocks=10)}

## Verify Installation Readiness

{_section_body(selected["wait"], max_blocks=10)}

## Source Trace

- 원문 slug: `installing_on_any_platform`
- 기준 축: `install-config / manifests / ignition / bootstrap / verify`
"""
    return text.strip() + "\n", sum(1 for value in selected.values() if value)


def _renderer_for_slug(slug: str):
    if slug == "backup_and_restore":
        return _render_backup_and_restore
    if slug == "installing_on_any_platform":
        return _render_installing_any_platform
    raise ValueError(f"unsupported reader-grade slug: {slug}")


def reader_grade_output_dir(settings: Settings) -> Path:
    return settings.root_dir / "data" / "reader_grade_books"


def build_reader_grade_books(
    settings: Settings,
    *,
    slugs: list[str],
    force_regenerate: bool = True,
) -> list[ReaderGradeOutput]:
    ensure_translation_manifest(settings, slugs)
    generate_translation_drafts(settings, slugs=slugs, force_regenerate=force_regenerate)
    out_dir = reader_grade_output_dir(settings)
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[ReaderGradeOutput] = []
    for slug in slugs:
        playbook_path = settings.silver_ko_dir / "translation_drafts" / "playbooks" / f"{slug}.json"
        payload = json.loads(playbook_path.read_text(encoding="utf-8"))
        renderer = _renderer_for_slug(slug)
        markdown, used_sections = renderer(list(payload.get("sections") or []))
        output_path = out_dir / f"{slug}.md"
        output_path.write_text(markdown, encoding="utf-8")
        outputs.append(
            ReaderGradeOutput(
                slug=slug,
                title=str(payload.get("title") or slug),
                output_path=output_path,
                section_count=used_sections,
            )
        )
    return outputs

