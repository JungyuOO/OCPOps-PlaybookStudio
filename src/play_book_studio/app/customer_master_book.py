from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from play_book_studio.app.customer_pack_read_boundary import (
    LOCAL_CUSTOMER_PACK_TENANT_ID,
    LOCAL_CUSTOMER_PACK_WORKSPACE_ID,
)
from play_book_studio.config.settings import load_settings
from play_book_studio.intake import CustomerPackDraftStore
from play_book_studio.intake.artifact_bundle import iter_customer_pack_book_payload_paths
from play_book_studio.intake.models import (
    CanonicalBookDraft,
    CustomerPackDraftRecord,
    DocSourceRequest,
)
from play_book_studio.intake.private_boundary import summarize_private_runtime_boundary
from play_book_studio.intake.service import evaluate_canonical_book_quality


CUSTOMER_MASTER_BOOK_VERSION = "customer_master_book_v1"
CUSTOMER_MASTER_ARTIFACT_VERSION = "customer_master_book_artifact_v1"
DEFAULT_MASTER_BOOK_SLUG = "customer-master-kmsc-ocp-operations-playbook"
DEFAULT_MASTER_BOOK_TITLE = "KOMSCO 지급결제플랫폼 OCP 운영 플레이북"

_SLUG_RE = re.compile(r"[^a-z0-9가-힣]+")
_TEST_TITLE_RE = re.compile(r"^\s*test\s*\d*\b", flags=re.IGNORECASE)
_CUSTOMER_DOC_CODE_RE = re.compile(r"\bKMSC-COCP-[A-Z]+-\d+(?=[_\s-]|$)[_\s-]*", flags=re.IGNORECASE)
_CUSTOMER_DOC_DATE_RE = re.compile(r"\b20\d{6}\b")


@dataclass(frozen=True, slots=True)
class MasterChapterSpec:
    chapter_id: str
    heading: str
    keywords: tuple[str, ...]
    source_title_hints: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CustomerMasterSourceBook:
    draft_id: str
    title: str
    source_uri: str
    source_fingerprint: str
    book_path: Path
    manifest_path: Path
    corpus_manifest_path: Path | None
    payload: dict[str, Any]
    manifest: dict[str, Any]
    corpus_manifest: dict[str, Any]
    updated_at: str


_CHAPTER_SPECS: tuple[MasterChapterSpec, ...] = (
    MasterChapterSpec(
        "overview",
        "사업/시스템 개요",
        ("개요", "소개", "목적", "범위", "사업", "지급결제", "완료보고"),
        ("완료보고",),
    ),
    MasterChapterSpec(
        "architecture",
        "목표 아키텍처와 OCP 구성",
        ("아키텍처", "아키텍쳐", "구성도", "네트워크", "스토리지", "클러스터", "ocp운영", "openshift"),
        ("아키텍처설계서", "아키텍쳐설계서", "ocp운영"),
    ),
    MasterChapterSpec(
        "cicd",
        "CI/CD 운영 구조",
        ("cicd", "ci/cd", "배포", "파이프라인", "tekton", "argocd", "gitlab", "quay", "itsm"),
        ("cicd",),
    ),
    MasterChapterSpec(
        "service_mesh",
        "서비스 메시 운영 구조",
        ("서비스메쉬", "서비스 메시", "mesh", "istio", "kiali", "gateway", "virtualservice"),
        ("서비스메쉬", "서비스 메시"),
    ),
    MasterChapterSpec(
        "test_strategy",
        "단위/통합/성능 테스트 전략",
        ("테스트 계획", "테스트계획", "단위테스트계획", "통합테스트 계획", "성능 테스트 계획", "시나리오", "범위"),
        ("계획서", "테스트계획"),
    ),
    MasterChapterSpec(
        "test_results",
        "테스트 결과와 품질 판정",
        ("테스트 결과", "결과서", "성능 테스트 결과", "결함", "조치", "통과", "품질"),
        ("결과서",),
    ),
    MasterChapterSpec(
        "operations",
        "운영 점검 체크리스트",
        ("운영", "점검", "확인", "검증", "모니터링", "체크", "완료"),
        ("운영", "완료보고"),
    ),
    MasterChapterSpec(
        "troubleshooting",
        "장애 대응과 확인 절차",
        ("장애", "오류", "복구", "실패", "fail", "error", "로그", "조치"),
        (),
    ),
    MasterChapterSpec(
        "transition",
        "운영 전환 및 완료 보고",
        ("완료보고", "완료", "전환", "인수", "종료", "보고"),
        ("완료보고",),
    ),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _slugify(value: str) -> str:
    normalized = _SLUG_RE.sub("-", str(value or "").strip().lower())
    return re.sub(r"-{2,}", "-", normalized).strip("-") or "section"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _is_test_source(record: CustomerPackDraftRecord | None, payload: dict[str, Any]) -> bool:
    title = str(payload.get("title") or getattr(record, "plan", None) and record.plan.title or "").strip()
    if _TEST_TITLE_RE.match(title):
        return True
    source_uri = str(payload.get("source_uri") or getattr(getattr(record, "request", None), "uri", "") or "").strip()
    return "\\test" in source_uri.lower() or "/test" in source_uri.lower()


def _is_customer_source_book(path: Path, payload: dict[str, Any], manifest: dict[str, Any]) -> bool:
    if "--" in path.stem:
        return False
    asset_kind = str(payload.get("asset_kind") or manifest.get("asset_kind") or "").strip()
    if asset_kind and asset_kind != "customer_pack_manual_book":
        return False
    if str(payload.get("composition_model") or "").strip() == CUSTOMER_MASTER_BOOK_VERSION:
        return False
    surface_kind = str(payload.get("surface_kind") or manifest.get("surface_kind") or "").strip()
    source_type = str(payload.get("source_type") or manifest.get("source_type") or "").strip().lower()
    return surface_kind == "slide_deck" and source_type in {"ppt", "pptx"}


def _source_publish_ready(manifest: dict[str, Any], corpus_manifest: dict[str, Any]) -> bool:
    if bool(manifest.get("publish_ready")) or bool(corpus_manifest.get("publish_ready")):
        return True
    grade_gate = dict(corpus_manifest.get("grade_gate") or manifest.get("grade_gate") or {})
    promotion_gate = dict(grade_gate.get("promotion_gate") or {})
    return bool(promotion_gate.get("publish_ready"))


def discover_customer_master_source_books(
    root_dir: str | Path,
    *,
    source_draft_ids: tuple[str, ...] | None = None,
    include_test_sources: bool = False,
) -> list[CustomerMasterSourceBook]:
    settings = load_settings(root_dir)
    store = CustomerPackDraftStore(root_dir)
    requested = {str(item).strip() for item in (source_draft_ids or ()) if str(item).strip()}
    by_fingerprint: dict[str, CustomerMasterSourceBook] = {}
    by_draft: dict[str, CustomerMasterSourceBook] = {}

    for book_path in iter_customer_pack_book_payload_paths(settings.customer_pack_books_dir):
        manifest_path = book_path.with_name(f"{book_path.stem}.manifest.json")
        if not manifest_path.exists():
            continue
        try:
            payload = _read_json(book_path)
            manifest = _read_json(manifest_path)
        except Exception:  # noqa: BLE001
            continue
        draft_id = str(payload.get("draft_id") or manifest.get("draft_id") or book_path.stem).strip() or book_path.stem
        if requested and draft_id not in requested:
            continue
        if not _is_customer_source_book(book_path, payload, manifest):
            continue
        record = store.get(draft_id)
        if record is None:
            continue
        if not include_test_sources and _is_test_source(record, payload):
            continue
        corpus_manifest_path = settings.customer_pack_corpus_dir / draft_id / "manifest.json"
        corpus_manifest = _read_json(corpus_manifest_path) if corpus_manifest_path.exists() else {}
        if not _source_publish_ready(manifest, corpus_manifest):
            continue
        title = str(payload.get("title") or record.plan.title or draft_id).strip() or draft_id
        source_uri = str(payload.get("source_uri") or record.request.uri or "").strip()
        source_fingerprint = str(getattr(record, "source_fingerprint", "") or "").strip()
        source = CustomerMasterSourceBook(
            draft_id=draft_id,
            title=title,
            source_uri=source_uri,
            source_fingerprint=source_fingerprint,
            book_path=book_path,
            manifest_path=manifest_path,
            corpus_manifest_path=corpus_manifest_path if corpus_manifest_path.exists() else None,
            payload=payload,
            manifest=manifest,
            corpus_manifest=corpus_manifest,
            updated_at=str(manifest.get("updated_at") or record.updated_at or ""),
        )
        dedupe_key = source_fingerprint or source_uri or draft_id
        existing = by_fingerprint.get(dedupe_key)
        if existing is None or (source.updated_at, source.draft_id) > (existing.updated_at, existing.draft_id):
            by_fingerprint[dedupe_key] = source
        by_draft[draft_id] = source

    if requested:
        return sorted(
            (source for draft_id, source in by_draft.items() if draft_id in requested),
            key=lambda item: _source_sort_key(item.title),
        )
    return sorted(by_fingerprint.values(), key=lambda item: _source_sort_key(item.title))


def _source_sort_key(title: str) -> tuple[int, str]:
    lowered = str(title or "").lower()
    if "완료보고" in lowered:
        return (80, lowered)
    if "결과" in lowered:
        return (70, lowered)
    if "계획" in lowered or "테스트" in lowered:
        return (60, lowered)
    if "서비스메쉬" in lowered or "서비스 메시" in lowered:
        return (40, lowered)
    if "cicd" in lowered or "ci/cd" in lowered:
        return (30, lowered)
    if "아키텍처" in lowered or "아키텍쳐" in lowered:
        return (20, lowered)
    return (50, lowered)


def _customer_document_probe(title: str) -> str:
    normalized = Path(str(title or "").replace("\\", "/")).name
    normalized = re.sub(r"\.[a-z0-9]+$", "", normalized, flags=re.IGNORECASE)
    normalized = _CUSTOMER_DOC_CODE_RE.sub("", normalized)
    normalized = normalized.replace("아키텍쳐", "아키텍처")
    normalized = normalized.replace("서비스메쉬", "서비스메시")
    normalized = re.sub(r"cicd", "CI/CD", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"[_-]+", " ", normalized)
    return re.sub(r"\s+", "", normalized).strip().lower()


def display_customer_document_title(title: str) -> str:
    raw = str(title or "").strip()
    probe = _customer_document_probe(raw)
    if not probe:
        return raw
    if "완료보고" in probe:
        return "운영 전환 완료 보고"
    if "서비스메시" in probe and "아키텍처" in probe:
        return "서비스 메시 아키텍처 설계서"
    if ("ci/cd" in probe or "cicd" in probe) and "아키텍처" in probe:
        return "CI/CD 아키텍처 설계서"
    if "ocp운영" in probe and "아키텍처" in probe:
        return "OCP 운영 아키텍처 설계서"
    if "서비스" in probe and "단위테스트" in probe and "계획" in probe:
        return "서비스 단위 테스트 계획"
    if "ocp" in probe and "단위테스트" in probe and "계획" in probe:
        return "OCP 단위 테스트 계획"
    if "서비스" in probe and "통합" in probe and "성능" in probe and "계획" in probe:
        return "서비스 통합/성능 테스트 계획"
    if "ocp" in probe and "통합테스트" in probe and "계획" in probe:
        return "OCP 통합 테스트 계획"
    if "서비스" in probe and "통합" in probe and "성능" in probe and "결과" in probe:
        return "서비스 통합/성능 테스트 결과"
    if "ocp" in probe and "통합테스트" in probe and "결과" in probe:
        return "OCP 통합 테스트 결과"
    if not (
        "KMSC-COCP-" in raw
        or _CUSTOMER_DOC_DATE_RE.search(raw)
        or "_" in raw
        or "FINAL" in raw.upper()
    ):
        return raw
    cleaned = Path(raw.replace("\\", "/")).name
    cleaned = re.sub(r"\.[a-z0-9]+$", "", cleaned, flags=re.IGNORECASE)
    cleaned = _CUSTOMER_DOC_CODE_RE.sub("", cleaned)
    cleaned = _CUSTOMER_DOC_DATE_RE.sub("", cleaned)
    cleaned = re.sub(r"\bFINAL\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("완료본", "")
    cleaned = cleaned.replace("아키텍쳐", "아키텍처")
    cleaned = cleaned.replace("서비스메쉬", "서비스 메시")
    cleaned = re.sub(r"cicd", "CI/CD", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("OCP운영", "OCP 운영")
    cleaned = cleaned.replace("단위테스트", "단위 테스트")
    cleaned = cleaned.replace("통합테스트", "통합 테스트")
    cleaned = cleaned.replace("계획서", "계획")
    cleaned = cleaned.replace("결과서", "결과")
    cleaned = re.sub(r"[_-]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip(" ._-") or raw


def _section_blob(source: CustomerMasterSourceBook, section: dict[str, Any]) -> str:
    return " ".join(
        part.lower()
        for part in (
            source.title,
            str(section.get("heading") or ""),
            str(section.get("section_path_label") or ""),
            str(section.get("text") or "")[:1200],
        )
        if part
    )


def _score_chapter(spec: MasterChapterSpec, source: CustomerMasterSourceBook, section: dict[str, Any]) -> int:
    blob = _section_blob(source, section)
    source_title = source.title.lower()
    score = sum(2 for keyword in spec.keywords if keyword.lower() in blob)
    score += sum(3 for keyword in spec.source_title_hints if keyword.lower() in source_title)
    if spec.chapter_id == "test_strategy" and "결과" in source_title:
        score -= 3
    if spec.chapter_id == "test_results" and "계획" in source_title:
        score -= 3
    if spec.chapter_id == "architecture" and ("cicd" in source_title or "서비스메쉬" in source_title):
        score -= 2
    return max(score, 0)


def _source_section_citation(
    source: CustomerMasterSourceBook,
    section: dict[str, Any],
) -> dict[str, Any]:
    anchor = str(section.get("anchor") or "").strip()
    viewer_path = str(section.get("viewer_path") or "").strip()
    if not viewer_path:
        viewer_path = f"/playbooks/customer-packs/{source.draft_id}/index.html"
        if anchor:
            viewer_path = f"{viewer_path}#{anchor}"
    return {
        "source_draft_id": source.draft_id,
        "source_title": source.title,
        "source_display_title": display_customer_document_title(source.title),
        "source_uri": source.source_uri,
        "source_fingerprint": source.source_fingerprint,
        "source_section_key": str(section.get("section_key") or anchor or section.get("ordinal") or "").strip(),
        "source_anchor": anchor,
        "source_heading": str(section.get("heading") or "").strip(),
        "source_viewer_path": viewer_path,
        "source_url": str(section.get("source_url") or source.source_uri or "").strip(),
        "source_unit_kind": str(section.get("source_unit_kind") or "slide").strip() or "slide",
        "source_unit_id": str(
            section.get("source_unit_id")
            or section.get("source_unit_index")
            or section.get("ordinal")
            or ""
        ).strip(),
    }


def _append_unique_citation(target: list[dict[str, Any]], citation: dict[str, Any], *, limit: int) -> None:
    key = (
        str(citation.get("source_draft_id") or ""),
        str(citation.get("source_section_key") or ""),
        str(citation.get("source_anchor") or ""),
    )
    for existing in target:
        existing_key = (
            str(existing.get("source_draft_id") or ""),
            str(existing.get("source_section_key") or ""),
            str(existing.get("source_anchor") or ""),
        )
        if existing_key == key:
            return
    if len(target) < limit:
        target.append(citation)


def _chapter_citations_for_sources(
    sources: list[CustomerMasterSourceBook],
    *,
    per_chapter_limit: int = 18,
) -> dict[str, list[dict[str, Any]]]:
    chapter_candidates: dict[str, list[tuple[int, int, int, dict[str, Any]]]] = {
        spec.chapter_id: [] for spec in _CHAPTER_SPECS
    }
    chapter_citations: dict[str, list[dict[str, Any]]] = {spec.chapter_id: [] for spec in _CHAPTER_SPECS}
    source_covered: set[str] = set()

    for source_index, source in enumerate(sources):
        sections = [dict(item) for item in (source.payload.get("sections") or []) if isinstance(item, dict)]
        for section_index, section in enumerate(sections):
            scored = [
                (_score_chapter(spec, source, section), spec.chapter_id)
                for spec in _CHAPTER_SPECS
            ]
            scored.sort(key=lambda item: (-item[0], item[1]))
            if not scored or scored[0][0] <= 0:
                continue
            chapter_id = scored[0][1]
            citation = _source_section_citation(source, section)
            chapter_candidates[chapter_id].append((scored[0][0], source_index, section_index, citation))
            source_covered.add(source.draft_id)

    for chapter_id, candidates in chapter_candidates.items():
        by_source: dict[str, list[tuple[int, int, int, dict[str, Any]]]] = {}
        for candidate in candidates:
            citation = candidate[3]
            source_id = str(citation.get("source_draft_id") or "").strip()
            if not source_id:
                continue
            by_source.setdefault(source_id, []).append(candidate)
        for source_candidates in by_source.values():
            source_candidates.sort(key=lambda item: (-item[0], item[2]))
        source_order = sorted(
            by_source,
            key=lambda source_id: min(item[1] for item in by_source[source_id]),
        )
        while len(chapter_citations[chapter_id]) < per_chapter_limit and source_order:
            added_in_round = False
            for source_id in source_order:
                if len(chapter_citations[chapter_id]) >= per_chapter_limit:
                    break
                source_candidates = by_source.get(source_id) or []
                if not source_candidates:
                    continue
                _score, _source_index, _section_index, citation = source_candidates.pop(0)
                _append_unique_citation(chapter_citations[chapter_id], citation, limit=per_chapter_limit)
                added_in_round = True
            source_order = [source_id for source_id in source_order if by_source.get(source_id)]
            if not added_in_round:
                break

    for source in sources:
        if source.draft_id in source_covered:
            continue
        sections = [dict(item) for item in (source.payload.get("sections") or []) if isinstance(item, dict)]
        if not sections:
            continue
        target_chapter = "overview"
        best_spec = max(
            _CHAPTER_SPECS,
            key=lambda spec: sum(1 for hint in spec.source_title_hints if hint.lower() in source.title.lower()),
        )
        if any(hint.lower() in source.title.lower() for hint in best_spec.source_title_hints):
            target_chapter = best_spec.chapter_id
        _append_unique_citation(
            chapter_citations[target_chapter],
            _source_section_citation(source, sections[0]),
            limit=per_chapter_limit,
        )

    return chapter_citations


def _table_cell(value: str) -> str:
    return " ".join(str(value or "").replace("|", "/").split()).strip()


def _source_evidence_table(citations: list[dict[str, Any]], *, limit: int = 12) -> str:
    rows = ["문서 | 슬라이드 | 근거 제목"]
    for citation in citations[:limit]:
        title = _table_cell(
            str(citation.get("source_display_title") or citation.get("source_title") or "")
        )
        unit = _table_cell(str(citation.get("source_unit_id") or ""))
        heading = _table_cell(str(citation.get("source_heading") or ""))
        rows.append(f"{title} | {unit or '-'} | {heading or '-'}")
    return "[TABLE header=\"true\"]\n{}\n[/TABLE]".format("\n".join(rows))


def _chapter_text(heading: str, citations: list[dict[str, Any]]) -> str:
    source_titles = []
    for citation in citations:
        title = str(citation.get("source_display_title") or citation.get("source_title") or "").strip()
        if title and title not in source_titles:
            source_titles.append(title)
    lines = [
        f"{heading} 장은 고객 원본 문서 {len(source_titles)}개에서 확인된 근거를 하나의 운영 플레이북 흐름으로 묶은 통합 장입니다.",
        "원본 PPT 파일명은 내부 provenance로 유지하고, 화면에는 고객 업무 맥락 기준 문서명을 표시합니다.",
        "",
        "대표 근거 슬라이드는 아래와 같습니다.",
        "",
        _source_evidence_table(citations),
    ]
    return "\n".join(line for line in lines if line is not None).strip()


def _appendix_section(
    *,
    ordinal: int,
    master_slug: str,
    sources: list[CustomerMasterSourceBook],
) -> dict[str, Any]:
    heading = "원본 문서와 슬라이드 근거"
    anchor = _slugify(heading)
    citations: list[dict[str, Any]] = []
    lines = [
        "이 부록은 통합 책이 참조한 원본 고객 문서와 슬라이드 보존 상태를 나열합니다.",
        "",
        "[TABLE header=\"true\"]",
        "문서 | Draft ID | Source Units | Rendered Slide Assets",
    ]
    for source in sources:
        sections = [dict(item) for item in (source.payload.get("sections") or []) if isinstance(item, dict)]
        first_section = sections[0] if sections else {}
        if first_section:
            citations.append(_source_section_citation(source, first_section))
        source_units = _safe_int(source.manifest.get("source_unit_count") or source.payload.get("source_unit_count"))
        rendered = _safe_int(source.manifest.get("rendered_slide_asset_count") or source.payload.get("slide_preview_count"))
        lines.append(
            f"{_table_cell(display_customer_document_title(source.title))} | {_table_cell(source.draft_id)} | {source_units} | {rendered}"
        )
    lines.append("[/TABLE]")
    return {
        "ordinal": ordinal,
        "section_key": f"{master_slug}:{anchor}",
        "heading": heading,
        "section_level": 1,
        "section_path": [heading],
        "section_path_label": heading,
        "anchor": anchor,
        "viewer_path": f"/playbooks/customer-packs/{master_slug}/index.html#{anchor}",
        "source_url": f"customer-master:{master_slug}",
        "text": "\n".join(lines).strip(),
        "block_kinds": ["paragraph", "citation_index"],
        "semantic_role": "reference",
        "source_citations": citations,
        "source_draft_ids": [source.draft_id for source in sources],
        "source_titles": [display_customer_document_title(source.title) for source in sources],
        "source_raw_titles": [source.title for source in sources],
    }


def build_customer_master_book_payload(
    sources: list[CustomerMasterSourceBook],
    *,
    master_slug: str = DEFAULT_MASTER_BOOK_SLUG,
    title: str = DEFAULT_MASTER_BOOK_TITLE,
) -> dict[str, Any]:
    chapter_citations = _chapter_citations_for_sources(sources)
    sections: list[dict[str, Any]] = []
    ordinal = 1
    for spec in _CHAPTER_SPECS:
        citations = chapter_citations.get(spec.chapter_id) or []
        if not citations:
            continue
        anchor = _slugify(spec.heading)
        source_draft_ids = []
        source_titles = []
        for citation in citations:
            draft_id = str(citation.get("source_draft_id") or "").strip()
            if draft_id and draft_id not in source_draft_ids:
                source_draft_ids.append(draft_id)
            source_title = str(citation.get("source_display_title") or citation.get("source_title") or "").strip()
            if source_title and source_title not in source_titles:
                source_titles.append(source_title)
        sections.append(
            {
                "ordinal": ordinal,
                "section_key": f"{master_slug}:{spec.chapter_id}",
                "heading": spec.heading,
                "section_level": 1,
                "section_path": [spec.heading],
                "section_path_label": spec.heading,
                "anchor": anchor,
                "viewer_path": f"/playbooks/customer-packs/{master_slug}/index.html#{anchor}",
                "source_url": f"customer-master:{master_slug}",
                "text": _chapter_text(spec.heading, citations),
                "block_kinds": ["paragraph", "source_citation"],
                "semantic_role": "procedure" if spec.chapter_id in {"operations", "troubleshooting"} else "concept",
                "source_citations": citations,
                "source_draft_ids": source_draft_ids,
                "source_titles": source_titles,
                "master_chapter_id": spec.chapter_id,
            }
        )
        ordinal += 1

    sections.append(
        _appendix_section(
            ordinal=ordinal,
            master_slug=master_slug,
            sources=sources,
        )
    )

    source_draft_ids = [source.draft_id for source in sources]
    return {
        "canonical_model": "canonical_book_v1",
        "composition_model": CUSTOMER_MASTER_BOOK_VERSION,
        "book_slug": master_slug,
        "asset_slug": master_slug,
        "asset_kind": "customer_master_playbook",
        "title": title,
        "source_type": "customer_master_book",
        "source_uri": f"customer-master:{master_slug}",
        "source_collection": "uploaded",
        "pack_id": "kmsc-ocp-customer-master",
        "pack_label": "KOMSCO Customer Master Pack",
        "inferred_product": "openshift",
        "inferred_version": "customer",
        "language_hint": "ko",
        "source_view_strategy": "composed_master_book_with_source_citations",
        "retrieval_derivation": "chunks_from_master_sections_and_source_citations",
        "surface_kind": "document",
        "source_unit_kind": "chapter",
        "source_unit_count": len(sections),
        "family_label": "Customer Master Playbook",
        "family_summary": (
            f"고객 PPT {len(sources)}개와 원본 슬라이드 "
            f"{sum(_safe_int(source.manifest.get('source_unit_count')) for source in sources)}장을 "
            "업무 맥락 기반 목차로 재구성한 통합 플레이북입니다."
        ),
        "approval_state": "approved",
        "publication_state": "active",
        "classification": "private",
        "tenant_id": LOCAL_CUSTOMER_PACK_TENANT_ID,
        "workspace_id": LOCAL_CUSTOMER_PACK_WORKSPACE_ID,
        "access_groups": [LOCAL_CUSTOMER_PACK_WORKSPACE_ID, LOCAL_CUSTOMER_PACK_TENANT_ID],
        "provider_egress_policy": "local_only",
        "redaction_state": "raw",
        "runtime_truth_label": "Customer Source-First Pack",
        "boundary_truth": "private_customer_pack_runtime",
        "boundary_badge": "Private Pack Runtime",
        "composition_scope": {
            "source_draft_ids": source_draft_ids,
            "source_titles": [display_customer_document_title(source.title) for source in sources],
            "source_raw_titles": [source.title for source in sources],
            "source_count": len(sources),
            "source_unit_count": sum(_safe_int(source.manifest.get("source_unit_count")) for source in sources),
            "rendered_slide_asset_count": sum(
                _safe_int(source.manifest.get("rendered_slide_asset_count"))
                for source in sources
            ),
            "dedupe_strategy": "latest_non_test_source_fingerprint",
            "source_truth_owner": "customer_pack_canonical_json_bundle",
        },
        "sections": sections,
        "notes": [
            "원본 PPT는 덱 단위 truth로 보존하고, master book은 업무 맥락 기반 목차와 citation layer를 제공한다.",
            "원본 파일명은 장 제목이 아니라 source citation/provenance에만 사용한다.",
        ],
    }


def _section_rows(payload: dict[str, Any], *, master_slug: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    title = str(payload.get("title") or master_slug).strip() or master_slug
    for section in payload.get("sections") or []:
        if not isinstance(section, dict):
            continue
        text = str(section.get("text") or "").strip()
        if not text:
            continue
        section_key = str(section.get("section_key") or section.get("anchor") or section.get("ordinal") or "").strip()
        rows.append(
            {
                "chunk_id": f"{master_slug}:{section_key}",
                "book_slug": master_slug,
                "chapter": title,
                "section": str(section.get("heading") or "").strip(),
                "section_id": section_key,
                "section_path": list(section.get("section_path") or []),
                "anchor": str(section.get("anchor") or "").strip(),
                "source_url": str(section.get("source_url") or payload.get("source_uri") or "").strip(),
                "viewer_path": str(section.get("viewer_path") or "").strip(),
                "text": text,
                "chunk_type": "reference",
                "source_id": f"customer_pack:{master_slug}",
                "source_lane": "customer_pack",
                "source_type": "customer_master_book",
                "source_collection": "uploaded",
                "product": "openshift",
                "version": "customer",
                "locale": "ko",
                "translation_status": "approved_ko",
                "review_status": "approved",
                "trust_score": 1.0,
                "semantic_role": str(section.get("semantic_role") or "reference").strip(),
                "block_kinds": list(section.get("block_kinds") or []),
                "truth_owner": "canonical_json_bundle",
                "canonical_book_slug": master_slug,
                "canonical_title": title,
                "asset_slug": master_slug,
                "asset_kind": "customer_master_playbook",
                "surface_kind": "document",
                "source_unit_kind": "chapter",
                "source_unit_id": section_key,
                "source_unit_anchor": str(section.get("anchor") or "").strip(),
                "origin_method": "composed",
                "ocr_status": "not_required",
                "runtime_truth_label": "Customer Source-First Pack",
                "boundary_truth": "private_customer_pack_runtime",
                "boundary_badge": "Private Pack Runtime",
                "lineage_section_key": section_key,
                "lineage_anchor": str(section.get("anchor") or "").strip(),
                "lineage_viewer_path": str(section.get("viewer_path") or "").strip(),
                "source_citations": list(section.get("source_citations") or []),
            }
        )
    return rows


def _citation_payload(payload: dict[str, Any], *, master_slug: str) -> dict[str, Any]:
    citations: list[dict[str, Any]] = []
    for section in payload.get("sections") or []:
        if not isinstance(section, dict):
            continue
        section_id = str(section.get("section_key") or section.get("anchor") or "").strip()
        citations.append(
            {
                "doc_id": master_slug,
                "section_id": section_id,
                "anchor_id": str(section.get("anchor") or "").strip(),
                "viewer_path": str(section.get("viewer_path") or "").strip(),
                "source_url": str(section.get("source_url") or payload.get("source_uri") or "").strip(),
                "section_heading": str(section.get("heading") or "").strip(),
                "source_citations": list(section.get("source_citations") or []),
            }
        )
    return {
        "artifact_version": "customer_master_book_citations_v1",
        "truth_owner": "canonical_json_bundle",
        "draft_id": master_slug,
        "asset_slug": master_slug,
        "book_slug": master_slug,
        "citations": citations,
    }


def _relations_payload(payload: dict[str, Any], *, master_slug: str) -> dict[str, Any]:
    entries = []
    for section in payload.get("sections") or []:
        if not isinstance(section, dict):
            continue
        entries.append(
            {
                "section_key": str(section.get("section_key") or "").strip(),
                "heading": str(section.get("heading") or "").strip(),
                "anchor": str(section.get("anchor") or "").strip(),
                "viewer_path": str(section.get("viewer_path") or "").strip(),
                "source_draft_ids": list(section.get("source_draft_ids") or []),
                "source_titles": list(section.get("source_titles") or []),
            }
        )
    return {
        "artifact_version": "customer_master_book_relations_v1",
        "truth_owner": "canonical_json_bundle",
        "draft_id": master_slug,
        "asset_slug": master_slug,
        "book_slug": master_slug,
        "section_relation_index": {
            "entries": entries,
            "by_book": {master_slug: entries},
        },
        "candidate_relations": {
            f"{master_slug}--source--{source_id}": {
                "relation_id": f"{master_slug}--source--{source_id}",
                "relation_type": "composes_from",
                "source_entity_slug": master_slug,
                "target_entity_slug": source_id,
            }
            for source_id in (payload.get("composition_scope") or {}).get("source_draft_ids", [])
        },
    }


def validate_customer_master_book(payload: dict[str, Any]) -> dict[str, Any]:
    scope = dict(payload.get("composition_scope") or {})
    expected_sources = {
        str(item).strip()
        for item in (scope.get("source_draft_ids") or [])
        if str(item).strip()
    }
    section_sources: set[str] = set()
    non_appendix_sources: set[str] = set()
    missing_citation_fields: list[dict[str, str]] = []
    for section in payload.get("sections") or []:
        if not isinstance(section, dict):
            continue
        is_appendix = str(section.get("heading") or "").strip() == "원본 문서와 슬라이드 근거"
        for citation in section.get("source_citations") or []:
            if not isinstance(citation, dict):
                continue
            source_draft_id = str(citation.get("source_draft_id") or "").strip()
            if source_draft_id:
                section_sources.add(source_draft_id)
                if not is_appendix:
                    non_appendix_sources.add(source_draft_id)
            for field_name in ("source_draft_id", "source_title", "source_viewer_path", "source_anchor"):
                if not str(citation.get(field_name) or "").strip():
                    missing_citation_fields.append(
                        {
                            "section": str(section.get("heading") or ""),
                            "field": field_name,
                        }
                    )
    source_coverage_ratio = len(section_sources & expected_sources) / max(len(expected_sources), 1)
    non_appendix_coverage_ratio = len(non_appendix_sources & expected_sources) / max(len(expected_sources), 1)
    headings = [str(section.get("heading") or "").strip() for section in payload.get("sections") or [] if isinstance(section, dict)]
    raw_filename_title = any(
        token in str(payload.get("title") or "")
        for token in ("_", ".ppt", ".pptx", "FINAL")
    )
    ok = (
        bool(expected_sources)
        and source_coverage_ratio == 1.0
        and not missing_citation_fields
        and not raw_filename_title
        and len(headings) >= 4
    )
    return {
        "ok": ok,
        "source_count": len(expected_sources),
        "covered_source_count": len(section_sources & expected_sources),
        "source_coverage_ratio": source_coverage_ratio,
        "covered_non_appendix_source_count": len(non_appendix_sources & expected_sources),
        "non_appendix_source_coverage_ratio": non_appendix_coverage_ratio,
        "section_count": len(headings),
        "missing_citation_fields": missing_citation_fields,
        "raw_filename_title": raw_filename_title,
        "headings": headings,
    }


def _master_record(
    *,
    root_dir: str | Path,
    master_slug: str,
    title: str,
    book_path: Path,
    corpus_manifest_path: Path,
    section_count: int,
    chunk_count: int,
) -> CustomerPackDraftRecord:
    store = CustomerPackDraftStore(root_dir)
    existing = store.get(master_slug)
    now = _utc_now()
    request = DocSourceRequest(
        source_type="md",
        uri=f"customer-master:{master_slug}",
        title=title,
        language_hint="ko",
    )
    plan = CanonicalBookDraft(
        book_slug=master_slug,
        title=title,
        source_type="md",
        source_uri=f"customer-master:{master_slug}",
        source_collection="uploaded",
        pack_id="kmsc-ocp-customer-master",
        pack_label="KOMSCO Customer Master Pack",
        inferred_product="openshift",
        inferred_version="customer",
        acquisition_uri=f"customer-master:{master_slug}",
        capture_strategy="customer_master_composition_v1",
        acquisition_step="compose_from_customer_pack_books",
        normalization_step="customer_master_book_composition",
        derivation_step="source_citation_preserving_master_book",
        notes=("synthetic master book record",),
        source_view_strategy="composed_master_book_with_source_citations",
        retrieval_derivation="chunks_from_master_sections_and_source_citations",
    )
    record = CustomerPackDraftRecord(
        draft_id=master_slug,
        status="normalized",
        created_at=existing.created_at if existing is not None else now,
        updated_at=now,
        request=request,
        plan=plan,
        capture_artifact_path=f"customer-master:{master_slug}",
        source_lane="customer_master_composition",
        parser_route="customer_master_book_composition_v1",
        parser_backend="customer_master_composer",
        parser_version=CUSTOMER_MASTER_BOOK_VERSION,
        extraction_confidence=1.0,
        tenant_id=LOCAL_CUSTOMER_PACK_TENANT_ID,
        workspace_id=LOCAL_CUSTOMER_PACK_WORKSPACE_ID,
        classification="private",
        access_groups=(LOCAL_CUSTOMER_PACK_WORKSPACE_ID, LOCAL_CUSTOMER_PACK_TENANT_ID),
        provider_egress_policy="local_only",
        approval_state="approved",
        publication_state="active",
        redaction_state="raw",
        canonical_book_path=str(book_path),
        normalized_section_count=section_count,
        private_corpus_manifest_path=str(corpus_manifest_path),
        private_corpus_status="ready",
        private_corpus_chunk_count=chunk_count,
        private_corpus_vector_status="skipped",
    )
    return store.save(record)


def write_customer_master_book(
    root_dir: str | Path,
    *,
    master_slug: str = DEFAULT_MASTER_BOOK_SLUG,
    title: str = DEFAULT_MASTER_BOOK_TITLE,
    source_draft_ids: tuple[str, ...] | None = None,
    include_test_sources: bool = False,
) -> tuple[Path, dict[str, Any]]:
    settings = load_settings(root_dir)
    sources = discover_customer_master_source_books(
        root_dir,
        source_draft_ids=source_draft_ids,
        include_test_sources=include_test_sources,
    )
    if not sources:
        raise ValueError("no publish-ready customer source books found for master composition")

    payload = build_customer_master_book_payload(sources, master_slug=master_slug, title=title)
    validation = validate_customer_master_book(payload)
    rows = _section_rows(payload, master_slug=master_slug)
    books_dir = settings.customer_pack_books_dir
    book_path = books_dir / f"{master_slug}.json"
    artifact_manifest_path = books_dir / f"{master_slug}.manifest.json"
    citations_path = books_dir / f"{master_slug}.citations.json"
    relations_path = books_dir / f"{master_slug}.relations.json"
    corpus_dir = settings.customer_pack_corpus_dir / master_slug
    corpus_manifest_path = corpus_dir / "manifest.json"
    chunks_path = corpus_dir / "chunks.jsonl"
    bm25_path = corpus_dir / "bm25_corpus.jsonl"

    preliminary_manifest = {
        "artifact_version": "customer_private_corpus_v1",
        "truth_owner": "canonical_json_bundle",
        "draft_id": master_slug,
        "tenant_id": LOCAL_CUSTOMER_PACK_TENANT_ID,
        "workspace_id": LOCAL_CUSTOMER_PACK_WORKSPACE_ID,
        "pack_id": "kmsc-ocp-customer-master",
        "pack_version": master_slug,
        "classification": "private",
        "access_groups": [LOCAL_CUSTOMER_PACK_WORKSPACE_ID, LOCAL_CUSTOMER_PACK_TENANT_ID],
        "provider_egress_policy": "local_only",
        "approval_state": "approved",
        "publication_state": "active",
        "redaction_state": "raw",
        "source_lane": "customer_master_composition",
        "source_collection": "uploaded",
        "boundary_truth": "private_customer_pack_runtime",
        "runtime_truth_label": "Customer Source-First Pack",
        "boundary_badge": "Private Pack Runtime",
        "surface_kind": "document",
        "source_unit_kind": "chapter",
        "origin_method": "composed",
        "ocr_status": "not_required",
        "canonical_book_slug": master_slug,
        "canonical_title": title,
        "asset_slugs": [master_slug],
        "book_slugs": [master_slug],
        "playable_asset_count": 1,
        "derived_asset_count": 0,
        "book_count": 1,
        "section_count": len(payload.get("sections") or []),
        "materialization_status": "ready",
        "materialization_error": "",
        "chunk_count": len(rows),
        "anchor_lineage_count": sum(1 for row in rows if str(row.get("anchor") or "").strip()),
        "bm25_ready": bool(rows),
        "vector_status": "skipped",
        "vector_chunk_count": 0,
        "vector_error": "",
        "manifest_path": str(corpus_manifest_path),
        "chunks_path": str(chunks_path),
        "bm25_path": str(bm25_path),
        "updated_at": _utc_now(),
    }
    quality = evaluate_canonical_book_quality(payload, corpus_manifest=preliminary_manifest)
    grade_gate = dict(quality.get("grade_gate") or {})
    promotion_gate = dict(grade_gate.get("promotion_gate") or {})
    citation_gate = dict(grade_gate.get("citation_gate") or {})
    retrieval_gate = dict(grade_gate.get("retrieval_gate") or {})
    corpus_manifest = {
        **preliminary_manifest,
        **quality,
        "read_ready": bool(promotion_gate.get("read_ready")),
        "publish_ready": bool(promotion_gate.get("publish_ready")),
        "citation_landing_status": str(citation_gate.get("status") or "missing"),
        "retrieval_ready": bool(retrieval_gate.get("ready")),
        "master_book_validation": validation,
        "source_draft_ids": list((payload.get("composition_scope") or {}).get("source_draft_ids") or []),
    }
    boundary_summary = summarize_private_runtime_boundary(corpus_manifest)
    corpus_manifest["runtime_eligible"] = bool(boundary_summary.get("runtime_eligible"))
    corpus_manifest["boundary_fail_reasons"] = list(boundary_summary.get("fail_reasons") or [])

    payload = {
        **payload,
        **quality,
        "artifact_manifest_path": str(artifact_manifest_path),
        "private_corpus_manifest_path": str(corpus_manifest_path),
        "target_viewer_path": f"/playbooks/customer-packs/{master_slug}/index.html",
        "master_book_validation": validation,
    }
    artifact_manifest = {
        "artifact_version": CUSTOMER_MASTER_ARTIFACT_VERSION,
        "truth_owner": "canonical_json_bundle",
        "source_truth_owner": "customer_pack_canonical_json_bundle",
        "draft_id": master_slug,
        "asset_slug": master_slug,
        "asset_kind": "customer_master_playbook",
        "book_slug": master_slug,
        "title": title,
        "source_type": "customer_master_book",
        "source_collection": "uploaded",
        "source_lane": "customer_master_composition",
        "classification": "private",
        "approval_state": "approved",
        "publication_state": "active",
        "runtime_eligible": bool(corpus_manifest["runtime_eligible"]),
        "read_ready": bool(corpus_manifest["read_ready"]),
        "publish_ready": bool(corpus_manifest["publish_ready"]),
        "retrieval_ready": bool(corpus_manifest["retrieval_ready"]),
        "citation_landing_status": str(corpus_manifest["citation_landing_status"]),
        "shared_grade": str(corpus_manifest["shared_grade"]),
        "grade_gate": corpus_manifest["grade_gate"],
        "book_path": str(book_path),
        "manifest_path": str(artifact_manifest_path),
        "citations_path": str(citations_path),
        "relations_path": str(relations_path),
        "corpus_manifest_path": str(corpus_manifest_path),
        "section_count": len(payload.get("sections") or []),
        "chunk_count": len(rows),
        "composition_scope": payload.get("composition_scope") or {},
        "master_book_validation": validation,
        "updated_at": corpus_manifest["updated_at"],
    }

    _write_json(book_path, payload)
    _write_json(artifact_manifest_path, artifact_manifest)
    _write_json(citations_path, _citation_payload(payload, master_slug=master_slug))
    _write_json(relations_path, _relations_payload(payload, master_slug=master_slug))
    _write_json(corpus_manifest_path, corpus_manifest)
    _write_jsonl(chunks_path, rows)
    _write_jsonl(bm25_path, rows)
    _master_record(
        root_dir=root_dir,
        master_slug=master_slug,
        title=title,
        book_path=book_path,
        corpus_manifest_path=corpus_manifest_path,
        section_count=len(payload.get("sections") or []),
        chunk_count=len(rows),
    )

    report = {
        "status": "ready" if validation["ok"] and corpus_manifest["publish_ready"] else "review",
        "book_path": str(book_path),
        "artifact_manifest_path": str(artifact_manifest_path),
        "corpus_manifest_path": str(corpus_manifest_path),
        "master_slug": master_slug,
        "title": title,
        "source_count": len(sources),
        "source_draft_ids": [source.draft_id for source in sources],
        "section_count": len(payload.get("sections") or []),
        "chunk_count": len(rows),
        "shared_grade": str(corpus_manifest["shared_grade"]),
        "publish_ready": bool(corpus_manifest["publish_ready"]),
        "runtime_eligible": bool(corpus_manifest["runtime_eligible"]),
        "validation": validation,
    }
    return book_path, report


__all__ = [
    "CUSTOMER_MASTER_BOOK_VERSION",
    "DEFAULT_MASTER_BOOK_SLUG",
    "DEFAULT_MASTER_BOOK_TITLE",
    "build_customer_master_book_payload",
    "discover_customer_master_source_books",
    "validate_customer_master_book",
    "write_customer_master_book",
]
