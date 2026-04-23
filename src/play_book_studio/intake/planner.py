from __future__ import annotations

# 업로드 문서를 canonical study asset으로 설계하는 planner 진입점.

import re
from pathlib import PurePosixPath
from urllib.parse import urlparse

from play_book_studio.ingestion.metadata_extraction import extract_section_metadata
from play_book_studio.ingestion.models import NormalizedSection

from .capture.pdf import resolve_pdf_capture
from .capture.web import resolve_web_capture_url
from .models import (
    CanonicalBook,
    CanonicalBookDraft,
    CanonicalSection,
    DocSourceRequest,
    IntakeFormatSupportEntry,
    IntakeOcrMetadata,
    IntakeSupportMatrix,
    SupportStatus,
)

_OVERVIEW_HINTS = ("개요", "소개", "overview", "introduction", "about")
_PROCEDURE_HINTS = (
    "절차",
    "설치",
    "구성",
    "설정",
    "배포",
    "업데이트",
    "백업",
    "복구",
    "점검",
    "실행",
    "검증",
    "확인",
    "troubleshoot",
    "install",
    "configur",
    "deploy",
    "update",
    "backup",
    "restore",
    "usage",
)
_REFERENCE_HINTS = ("api", "reference", "참조", "spec", "status", "매개변수", "parameter")
_CONCEPT_HINTS = ("개념", "이해", "아키텍처", "architecture", "concept", "operator", "node")
_TROUBLESHOOTING_HINTS = ("문제 해결", "장애", "오류", "실패", "복구", "error", "fail", "crashloop", "backoff")


def _slugify(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[^a-z0-9가-힣]+", "-", lowered)
    lowered = re.sub(r"-{2,}", "-", lowered).strip("-")
    return lowered or "untitled-book"


def _infer_title(request: DocSourceRequest) -> str:
    if request.title.strip():
        return request.title.strip()

    if request.source_type in {"pdf", "md", "asciidoc", "txt", "docx", "pptx", "xlsx", "hwp", "hwpx", "image"}:
        path = PurePosixPath(request.uri.replace("\\", "/"))
        return path.stem or "Uploaded source"

    parsed = urlparse(request.uri)
    if parsed.path.strip("/"):
        return PurePosixPath(parsed.path).name or parsed.netloc or "Web source"
    return parsed.netloc or "Web source"


def _infer_product(*values: str) -> str:
    haystack = " ".join(value.strip().lower() for value in values if value).strip()
    if not haystack:
        return "unknown"
    if (
        "openshift" in haystack
        or "openshift_container_platform" in haystack
        or re.search(r"\bocp\b", haystack)
    ):
        return "openshift"
    if "kubernetes" in haystack or re.search(r"\bk8s\b", haystack):
        return "kubernetes"
    return "unknown"


def _infer_version(*values: str) -> str:
    haystack = " ".join(value.strip() for value in values if value).strip()
    if not haystack:
        return "unknown"
    match = re.search(r"\b(\d+\.\d+)\b", haystack)
    if match:
        return match.group(1)
    return "unknown"


def _pack_label_for_uploaded(product: str, version: str) -> str:
    if product == "openshift" and version != "unknown":
        return f"OpenShift {version} Custom Pack"
    if product == "openshift":
        return "OpenShift Custom Pack"
    return "User Custom Pack"


def _pack_id_for_uploaded(product: str, version: str) -> str:
    product_token = product if product != "unknown" else "custom"
    version_token = version.replace(".", "-") if version != "unknown" else "uploaded"
    return f"{product_token}-{version_token}-custom"


def _support_entry(
    *,
    format_id: str,
    route_label: str,
    source_type: str,
    support_status: SupportStatus,
    lane_kind: str,
    capture_strategy: str,
    normalization_strategy: str,
    review_rule: str,
    ocr: IntakeOcrMetadata | None = None,
    accepted_extensions: tuple[str, ...] = (),
    accepted_mime_types: tuple[str, ...] = (),
    notes: tuple[str, ...] = (),
    fallback_lanes: tuple[str, ...] = (),
) -> IntakeFormatSupportEntry:
    return IntakeFormatSupportEntry(
        format_id=format_id,
        route_label=route_label,
        source_type=source_type,
        support_status=support_status,
        lane_kind=lane_kind,
        capture_strategy=capture_strategy,
        normalization_strategy=normalization_strategy,
        review_rule=review_rule,
        ocr=ocr or IntakeOcrMetadata(enabled=False, required=False, runtime="n/a"),
        accepted_extensions=accepted_extensions,
        accepted_mime_types=accepted_mime_types,
        notes=notes,
        fallback_lanes=fallback_lanes,
    )


def build_customer_pack_support_matrix() -> IntakeSupportMatrix:
    return IntakeSupportMatrix(
        matrix_version="customer_pack_format_support_matrix_v1",
        status_legend={
            "supported": "현재 제품 경로에서 업로드 -> capture -> normalize -> playbook 생성까지 live 로 검증된 형식",
            "staged": "제품 경로는 존재하지만 OCR/quality review gate 때문에 보수적으로 취급하는 형식",
            "rejected": "현재 intake 에서 받지 않거나 canonical playbook 경로로 올리지 않는 형식",
        },
        entries=(
            _support_entry(
                format_id="web_html",
                route_label="Web HTML",
                source_type="web",
                support_status="supported",
                lane_kind="native",
                capture_strategy="docs_redhat_html_single_v1 / direct_html_fetch_v1",
                normalization_strategy="html_capture_to_canonical_sections_v1",
                review_rule="HTML/Markdown/Text capture가 비어 있으면 reject 하고, 임의 요약으로 대체하지 않는다.",
                accepted_extensions=(".html", ".htm"),
                accepted_mime_types=("text/html", "application/xhtml+xml"),
                notes=("웹 소스는 canonical sections 로 정규화한 뒤 retrieval chunk 로 분리한다.",),
            ),
            _support_entry(
                format_id="pdf_text",
                route_label="Text PDF",
                source_type="pdf",
                support_status="supported",
                lane_kind="native",
                capture_strategy="pdf_text_extract_v1",
                normalization_strategy="pdf_source_first_rows_to_canonical_sections_v1",
                review_rule="텍스트 기반 PDF 는 native text/docling/pdf-row triage 를 우선 쓰고, native lane 이 비면 MarkItDown fallback 으로만 보강한다.",
                ocr=IntakeOcrMetadata(
                    enabled=True,
                    required=False,
                    runtime="docling text -> docling OCR -> page-row fallback -> optional MarkItDown fallback",
                    fallback_order=("docling", "docling_ocr", "page_rows", "markitdown_fallback"),
                    quality_gate="merged-korean / low-quality text detection",
                    review_rule="텍스트가 충분히 복원되지 않으면 manual review 를 거친다.",
                    notes=("scan PDF 가 아니더라도 OCR fallback 과 row fallback 이 준비돼 있다.",),
                ),
                accepted_extensions=(".pdf",),
                accepted_mime_types=("application/pdf",),
                notes=("텍스트 PDF 는 source-first triage 를 우선 사용하고 MarkItDown 은 fallback 으로만 사용한다.",),
                fallback_lanes=("rescue", "bridge"),
            ),
            _support_entry(
                format_id="pdf_scan_ocr",
                route_label="Scan PDF with OCR",
                source_type="pdf",
                support_status="staged",
                lane_kind="rescue",
                capture_strategy="pdf_scan_ocr_v1",
                normalization_strategy="docling_ocr_to_canonical_sections_v1",
                review_rule="스캔 PDF 는 OCR runtime 과 quality gate 가 필수이며, OCR 결과가 비어 있거나 품질이 낮으면 review needed 로 보낸다.",
                ocr=IntakeOcrMetadata(
                    enabled=True,
                    required=True,
                    runtime="docling OCR + rendered OCR",
                    fallback_order=("docling_ocr", "rendered_ocr"),
                    quality_gate="no-text / merged-korean detection",
                    review_rule="OCR 결과를 사람이 다시 확인해야 하는 경우가 있다.",
                    notes=("스캔 PDF 는 OCR 없이는 canonical sections 로 못 올린다.",),
                ),
                accepted_extensions=(".pdf",),
                accepted_mime_types=("application/pdf",),
                notes=("스캔 PDF 는 OCR 경로로만 canonical book 으로 승격된다.",),
                fallback_lanes=("bridge",),
            ),
            _support_entry(
                format_id="md",
                route_label="Markdown",
                source_type="md",
                support_status="supported",
                lane_kind="native",
                capture_strategy="markdown_text_capture_v1",
                normalization_strategy="text_markdown_to_canonical_sections_v1",
                review_rule="heading, code, table 이 깨지지 않았는지 확인하고, 비어 있는 문서면 reject 한다.",
                accepted_extensions=(".md", ".markdown"),
                accepted_mime_types=("text/markdown", "text/plain"),
                notes=("Markdown 은 명시적 heading hierarchy 를 보존한다.",),
            ),
            _support_entry(
                format_id="asciidoc",
                route_label="AsciiDoc",
                source_type="asciidoc",
                support_status="supported",
                lane_kind="native",
                capture_strategy="asciidoc_text_capture_v1",
                normalization_strategy="text_asciidoc_to_canonical_sections_v1",
                review_rule="heading, code block, table block 이 정상적으로 보존되는지 확인한다.",
                accepted_extensions=(".adoc", ".asciidoc"),
                accepted_mime_types=("text/asciidoc", "text/plain"),
                notes=("AsciiDoc 은 실행 절차와 코드 블록을 canonical book 에 그대로 남긴다.",),
            ),
            _support_entry(
                format_id="txt",
                route_label="Text",
                source_type="txt",
                support_status="supported",
                lane_kind="native",
                capture_strategy="plain_text_capture_v1",
                normalization_strategy="text_plain_to_canonical_sections_v1",
                review_rule="plain text 가 UTF-8 이 아니거나 heading 이 없으면 reject 또는 재업로드가 필요하다.",
                accepted_extensions=(".txt",),
                accepted_mime_types=("text/plain",),
                notes=("plain text 는 numeric heading 도 section anchor 로 승격한다.",),
            ),
            _support_entry(
                format_id="docx",
                route_label="Word",
                source_type="docx",
                support_status="supported",
                lane_kind="native",
                capture_strategy="docx_structured_capture_v1",
                normalization_strategy="docx_native_structured_to_canonical_sections_v1",
                review_rule="DOCX native lane 에서 heading, table, executable step 이 구조적으로 남는지 확인하고, native lane 이 비면 MarkItDown fallback 으로만 보강한다.",
                accepted_extensions=(".docx",),
                accepted_mime_types=("application/vnd.openxmlformats-officedocument.wordprocessingml.document",),
                notes=("Word 문서는 source-first native extraction 을 우선 사용하고 MarkItDown 은 fallback/debug lane 으로만 둔다.",),
                fallback_lanes=("bridge",),
            ),
            _support_entry(
                format_id="pptx",
                route_label="PowerPoint",
                source_type="pptx",
                support_status="supported",
                lane_kind="native",
                capture_strategy="pptx_slide_capture_v1",
                normalization_strategy="pptx_native_slide_to_canonical_sections_v1",
                review_rule="PPTX native lane 에서 슬라이드 제목, 본문, 표 구조가 남는지 확인하고, native lane 이 비면 MarkItDown fallback 으로만 보강한다.",
                accepted_extensions=(".pptx",),
                accepted_mime_types=("application/vnd.openxmlformats-officedocument.presentationml.presentation",),
                notes=("PowerPoint 는 source-first native slide extraction 을 우선 사용하고 MarkItDown 은 fallback/debug lane 으로만 둔다.",),
                fallback_lanes=("bridge",),
            ),
            _support_entry(
                format_id="xlsx",
                route_label="Excel",
                source_type="xlsx",
                support_status="supported",
                lane_kind="native",
                capture_strategy="xlsx_sheet_capture_v1",
                normalization_strategy="xlsx_native_sheet_to_canonical_sections_v1",
                review_rule="XLSX native lane 에서 sheet/table headings 와 command cells 가 남는지 확인하고, native lane 이 비면 MarkItDown fallback 으로만 보강한다.",
                accepted_extensions=(".xlsx",),
                accepted_mime_types=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",),
                notes=("Excel 은 source-first native sheet extraction 을 우선 사용하고 MarkItDown 은 fallback/debug lane 으로만 둔다.",),
                fallback_lanes=("bridge",),
            ),
            _support_entry(
                format_id="hwp",
                route_label="Hancom HWP",
                source_type="hwp",
                support_status="staged",
                lane_kind="native",
                capture_strategy="hwp_binary_capture_v1",
                normalization_strategy="unhwp_structured_extract_v1",
                review_rule="unhwp structured extraction 을 우선 사용하고, embedded scan/bitmap block 은 후속 hybrid OCR lane 으로 넘긴다.",
                accepted_extensions=(".hwp",),
                accepted_mime_types=("application/x-hwp", "application/haansofthwp"),
                notes=(
                    "HWP 는 unhwp 기반 structured extraction 을 우선 사용한다.",
                    "현재 단계에서는 fixture validation 전이므로 staged 로 유지한다.",
                ),
                fallback_lanes=("bridge", "rescue"),
            ),
            _support_entry(
                format_id="hwpx",
                route_label="Hancom HWPX",
                source_type="hwpx",
                support_status="staged",
                lane_kind="native",
                capture_strategy="hwpx_zip_capture_v1",
                normalization_strategy="unhwp_structured_extract_v1",
                review_rule="unhwp structured extraction 을 우선 사용하고, embedded scan/bitmap block 은 후속 hybrid OCR lane 으로 넘긴다.",
                accepted_extensions=(".hwpx",),
                accepted_mime_types=("application/x-hwpx", "application/zip"),
                notes=(
                    "HWPX 는 unhwp 기반 structured extraction 을 우선 사용한다.",
                    "현재 단계에서는 fixture validation 전이므로 staged 로 유지한다.",
                ),
                fallback_lanes=("bridge", "rescue"),
            ),
            _support_entry(
                format_id="image_ocr",
                route_label="Image OCR",
                source_type="image",
                support_status="staged",
                lane_kind="rescue",
                capture_strategy="image_ocr_capture_v1",
                normalization_strategy="image_ocr_to_canonical_sections_v1",
                review_rule="이미지는 OCR 결과의 신뢰도에 따라 manual review 가 필요할 수 있다.",
                ocr=IntakeOcrMetadata(
                    enabled=True,
                    required=True,
                    runtime="docling image OCR",
                    fallback_order=("docling_ocr",),
                    quality_gate="low-confidence image OCR",
                    review_rule="이미지 OCR 은 review-needed 로 내려갈 수 있다.",
                    notes=("이미지 OCR 은 scan PDF 만큼 보수적으로 취급한다.",),
                ),
                accepted_extensions=(".png", ".jpg", ".jpeg", ".webp"),
                accepted_mime_types=("image/png", "image/jpeg", "image/webp"),
                notes=("이미지 OCR 은 화면 캡처/스캔된 안내문을 북으로 승격한다.",),
            ),
            _support_entry(
                format_id="csv",
                route_label="CSV",
                source_type="csv",
                support_status="rejected",
                lane_kind="blocked",
                capture_strategy="not_supported_v1",
                normalization_strategy="not_supported_v1",
                review_rule="현재 customer-pack intake 는 CSV 를 canonical playbook source 로 받지 않는다.",
                notes=("CSV 는 structured table source 로 자동 승격하지 않는다.",),
            ),
            _support_entry(
                format_id="zip",
                route_label="ZIP Archive",
                source_type="zip",
                support_status="rejected",
                lane_kind="blocked",
                capture_strategy="not_supported_v1",
                normalization_strategy="not_supported_v1",
                review_rule="압축 아카이브는 직접 업로드 지원 대상이 아니다.",
                notes=("압축 파일은 먼저 개별 source 로 풀어서 올려야 한다.",),
            ),
            _support_entry(
                format_id="json",
                route_label="JSON",
                source_type="json",
                support_status="rejected",
                lane_kind="blocked",
                capture_strategy="not_supported_v1",
                normalization_strategy="not_supported_v1",
                review_rule="JSON 은 현재 customer-pack intake 지원 포맷이 아니다.",
                notes=("JSON dump 는 사람이 읽을 수 있는 source 로 다시 변환해야 한다.",),
            ),
        ),
    )


def _resolve_text_capture(request: DocSourceRequest) -> tuple[str, str, str, tuple[str, ...]]:
    capture_strategy = {
        "md": "markdown_text_capture_v1",
        "asciidoc": "asciidoc_text_capture_v1",
        "txt": "plain_text_capture_v1",
    }[request.source_type]
    source_label = {
        "md": "Markdown",
        "asciidoc": "AsciiDoc",
        "txt": "Text",
    }[request.source_type]
    return (
        request.uri,
        capture_strategy,
        f"Capture the uploaded {source_label} source and preserve heading hierarchy, ordered steps, and fenced commands before canonical normalization.",
        (
            f"{source_label} sources should preserve explicit heading structure and command blocks where present.",
            "The normalized book view should stay separate from downstream retrieval chunks.",
        ),
    )


def _resolve_binary_capture(request: DocSourceRequest) -> tuple[str, str, str, tuple[str, ...]]:
    capture_strategy = {
        "docx": "docx_structured_capture_v1",
        "pptx": "pptx_slide_capture_v1",
        "xlsx": "xlsx_sheet_capture_v1",
        "hwp": "hwp_binary_capture_v1",
        "hwpx": "hwpx_zip_capture_v1",
        "image": "image_ocr_capture_v1",
    }[request.source_type]
    source_label = {
        "docx": "Word",
        "pptx": "PowerPoint",
        "xlsx": "Excel",
        "hwp": "Hancom HWP",
        "hwpx": "Hancom HWPX",
        "image": "Image",
    }[request.source_type]
    return (
        request.uri,
        capture_strategy,
        f"Capture the uploaded {source_label} source and preserve structural markers, tables, and executable steps before canonical normalization.",
        (
            f"{source_label} sources should preserve headings, tables, and operational commands where possible.",
            "The normalized book view should stay separate from downstream retrieval chunks.",
        ),
    )


def _detect_block_kinds(text: str) -> tuple[str, ...]:
    kinds: list[str] = []
    normalized = text or ""
    if normalized.strip():
        kinds.append("paragraph")
    if "[CODE]" in normalized and "[/CODE]" in normalized:
        kinds.append("code")
    if "[TABLE" in normalized and "[/TABLE]" in normalized:
        kinds.append("table")
    return tuple(kinds)


def _ordered_unique_strings(items: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        normalized = str(item).strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(normalized)
    return tuple(ordered)


def _row_metadata(
    *,
    book_slug: str,
    title: str,
    heading: str,
    section_level: int,
    section_path: tuple[str, ...],
    anchor: str,
    source_url: str,
    viewer_path: str,
    text: str,
) -> dict[str, tuple[str, ...]]:
    metadata = extract_section_metadata(
        NormalizedSection(
            book_slug=book_slug,
            book_title=title,
            heading=heading,
            section_level=section_level,
            section_path=list(section_path),
            anchor=anchor,
            source_url=source_url,
            viewer_path=viewer_path,
            text=text,
        )
    )
    return {
        "cli_commands": metadata.cli_commands,
        "error_strings": metadata.error_strings,
        "k8s_objects": metadata.k8s_objects,
        "operator_names": metadata.operator_names,
        "verification_hints": metadata.verification_hints,
    }


def _infer_semantic_role(
    *,
    book_slug: str,
    title: str,
    heading: str,
    section_path: tuple[str, ...],
    text: str,
    block_kinds: tuple[str, ...],
    cli_commands: tuple[str, ...],
    error_strings: tuple[str, ...],
) -> str:
    combined = " ".join([*section_path, heading, text]).lower()
    lowered_title = title.lower()
    if error_strings or any(token in combined for token in _TROUBLESHOOTING_HINTS):
        return "troubleshooting"
    if cli_commands or "code" in block_kinds or "procedure" in block_kinds:
        return "procedure"
    if any(token in combined for token in _OVERVIEW_HINTS):
        if book_slug.endswith("_overview") or "개요" in lowered_title or "overview" in lowered_title:
            return "concept"
        return "overview"
    if any(token in combined for token in _PROCEDURE_HINTS):
        return "procedure"
    if any(token in combined for token in _REFERENCE_HINTS) or ("table" in block_kinds and not cli_commands):
        return "reference"
    if any(token in combined for token in _CONCEPT_HINTS):
        return "concept"
    if book_slug.endswith("_overview") or "개요" in lowered_title or "overview" in lowered_title:
        return "concept"
    return "unknown"


def _section_path_label(section_path: tuple[str, ...], heading: str) -> str:
    if section_path:
        return " > ".join(part for part in section_path if part)
    return heading


def _section_key(book_slug: str, anchor: str, ordinal: int) -> str:
    if anchor.strip():
        return f"{book_slug}:{anchor.strip()}"
    return f"{book_slug}:section-{ordinal}"


class CustomerPackPlanner:
    def support_matrix(self) -> IntakeSupportMatrix:
        return build_customer_pack_support_matrix()

    def plan(self, request: DocSourceRequest) -> CanonicalBookDraft:
        title = _infer_title(request)
        slug = _slugify(title)
        inferred_product = _infer_product(request.title, request.uri, title)
        inferred_version = _infer_version(request.title, request.uri, title)
        source_collection = "uploaded"
        pack_id = _pack_id_for_uploaded(inferred_product, inferred_version)
        pack_label = _pack_label_for_uploaded(inferred_product, inferred_version)

        if request.source_type == "web":
            acquisition_uri, capture_strategy = resolve_web_capture_url(request.uri)
            acquisition_step = "Resolve the source URL and prefer an html-single snapshot before parsing."
            notes = (
                "Web sources should preserve original chapter/page mapping where possible.",
                "The normalized book view should stay separate from downstream retrieval chunks.",
            )
        elif request.source_type == "pdf":
            acquisition_uri, capture_strategy = resolve_pdf_capture(request.uri)
            acquisition_step = "Extract text and structural markers from PDF pages before section normalization."
            notes = (
                "PDF sources need a lightweight structure recovery pass before chunk derivation.",
                "Page numbers can remain as auxiliary metadata until section anchors become reliable.",
            )
        elif request.source_type in {"md", "asciidoc", "txt"}:
            acquisition_uri, capture_strategy, acquisition_step, notes = _resolve_text_capture(request)
        else:
            acquisition_uri, capture_strategy, acquisition_step, notes = _resolve_binary_capture(request)

        return CanonicalBookDraft(
            book_slug=slug,
            title=title,
            source_type=request.source_type,
            source_uri=request.uri,
            source_collection=source_collection,
            pack_id=pack_id,
            pack_label=pack_label,
            inferred_product=inferred_product,
            inferred_version=inferred_version,
            acquisition_uri=acquisition_uri,
            capture_strategy=capture_strategy,
            acquisition_step=acquisition_step,
            normalization_step="Build canonical sections that preserve headings, anchors, code blocks, and tables.",
            derivation_step="Derive a source-view document first, then retrieval chunks and embeddings as downstream artifacts.",
            notes=notes,
        )

    def build_canonical_book(
        self,
        rows: list[dict[str, object]],
        *,
        request: DocSourceRequest | None = None,
    ) -> CanonicalBook:
        if not rows:
            raise ValueError("rows must not be empty")

        first = rows[0]
        request = request or DocSourceRequest(
            source_type="web",
            uri=str(first.get("source_url") or ""),
            title=str(first.get("book_title") or first.get("book_slug") or ""),
            language_hint="ko",
        )
        draft = self.plan(request)
        book_slug = str(first.get("book_slug") or draft.book_slug)
        title = str(first.get("book_title") or draft.title)
        source_uri = str(first.get("source_url") or request.uri)

        sections: list[CanonicalSection] = []
        for ordinal, row in enumerate(rows, start=1):
            heading = str(row.get("heading") or "").strip() or f"Section {ordinal}"
            anchor = str(row.get("anchor") or "").strip()
            section_path = tuple(
                str(item).strip()
                for item in (row.get("section_path") or [])
                if str(item).strip()
            )
            section_text = str(row.get("text") or "").strip()
            source_url = str(row.get("source_url") or source_uri).strip()
            viewer_path = str(row.get("viewer_path") or "").strip()
            section_level = int(row.get("section_level") or 0)
            extracted_metadata = _row_metadata(
                book_slug=book_slug,
                title=title,
                heading=heading,
                section_level=section_level,
                section_path=section_path,
                anchor=anchor,
                source_url=source_url,
                viewer_path=viewer_path,
                text=section_text,
            )
            cli_commands = _ordered_unique_strings(
                [
                    *[str(item) for item in extracted_metadata["cli_commands"]],
                    *[str(item) for item in (row.get("cli_commands") or [])],
                ]
            )
            error_strings = _ordered_unique_strings(
                [
                    *[str(item) for item in extracted_metadata["error_strings"]],
                    *[str(item) for item in (row.get("error_strings") or [])],
                ]
            )
            k8s_objects = _ordered_unique_strings(
                [
                    *[str(item) for item in extracted_metadata["k8s_objects"]],
                    *[str(item) for item in (row.get("k8s_objects") or [])],
                ]
            )
            operator_names = _ordered_unique_strings(
                [
                    *[str(item) for item in extracted_metadata["operator_names"]],
                    *[str(item) for item in (row.get("operator_names") or [])],
                ]
            )
            verification_hints = _ordered_unique_strings(
                [
                    *[str(item) for item in extracted_metadata["verification_hints"]],
                    *[str(item) for item in (row.get("verification_hints") or [])],
                ]
            )
            block_kinds = _ordered_unique_strings(
                [
                    *list(_detect_block_kinds(section_text)),
                    *[str(item) for item in (row.get("block_kinds") or [])],
                    *(["code"] if cli_commands else []),
                ]
            )
            semantic_role = str(row.get("semantic_role") or "").strip() or _infer_semantic_role(
                book_slug=book_slug,
                title=title,
                heading=heading,
                section_path=section_path,
                text=section_text,
                block_kinds=block_kinds,
                cli_commands=cli_commands,
                error_strings=error_strings,
            )
            sections.append(
                CanonicalSection(
                    ordinal=ordinal,
                    section_key=_section_key(book_slug, anchor, ordinal),
                    heading=heading,
                    section_level=section_level,
                    section_path=section_path,
                    section_path_label=_section_path_label(section_path, heading),
                    anchor=anchor,
                    viewer_path=viewer_path,
                    source_url=source_url,
                    text=section_text,
                    block_kinds=block_kinds,
                    semantic_role=semantic_role,
                    cli_commands=cli_commands,
                    error_strings=error_strings,
                    k8s_objects=k8s_objects,
                    operator_names=operator_names,
                    verification_hints=verification_hints,
                )
            )

        return CanonicalBook(
            canonical_model=draft.canonical_model,
            book_slug=book_slug,
            title=title,
            source_type=request.source_type,
            source_uri=source_uri,
            source_collection=draft.source_collection,
            pack_id=draft.pack_id,
            pack_label=draft.pack_label,
            inferred_product=draft.inferred_product,
            inferred_version=draft.inferred_version,
            language_hint=request.language_hint,
            source_view_strategy="normalized_sections_v1",
            retrieval_derivation=draft.retrieval_derivation,
            sections=tuple(sections),
            notes=draft.notes,
        )


__all__ = ["CustomerPackPlanner"]
