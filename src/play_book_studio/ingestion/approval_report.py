# source catalog를 승인 가능한 runtime manifest와 approval 리포트로 바꾸는 helper다.
from __future__ import annotations

from collections import Counter
from pathlib import Path
import json

from .audit_rules import (
    CONTENT_STATUS_SORT_ORDER,
    LANGUAGE_FALLBACK_RE,
    body_language_guess,
    classify_content_status,
    hangul_ratio,
    is_english_like_title,
    resolve_final_content_status,
)
from .collector import entry_with_collected_metadata
from .corpus_policy import (
    LANE_MANUAL_REVIEW_FIRST,
    LANE_TRANSLATION_FIRST,
    classify_gap_lane,
)
from .data_quality import playbook_reader_grade_failures
from .manifest import read_manifest, runtime_catalog_entries, write_manifest
from .models import (
    CITATION_ELIGIBLE_STATUSES,
    CONTENT_STATUS_APPROVED_KO,
    CONTENT_STATUS_BLOCKED,
    CONTENT_STATUS_EN_ONLY,
    CONTENT_STATUS_MIXED,
    CONTENT_STATUS_TRANSLATED_KO_DRAFT,
    SourceManifestEntry,
)
from .translation_lane import (
    TRANSLATION_STAGE_APPROVED,
    build_translation_metadata,
)
from .validation import read_jsonl


def _bundle_root_candidates(settings) -> tuple[Path, ...]:
    candidates: list[Path] = []
    bronze_dir = getattr(settings, "bronze_dir", None)
    if bronze_dir is not None:
        candidates.append(Path(bronze_dir) / "source_bundles")
    raw_html_dir = getattr(settings, "raw_html_dir", None)
    if raw_html_dir is not None:
        candidates.append(Path(raw_html_dir).parent / "source_bundles")
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return tuple(unique)


def _bundle_status_by_slug(settings) -> dict[str, dict[str, object]]:
    statuses: dict[str, dict[str, object]] = {}
    for root in _bundle_root_candidates(settings):
        if not root.exists():
            continue
        for bundle_dir in sorted(path for path in root.iterdir() if path.is_dir()):
            dossier_path = bundle_dir / "dossier.json"
            if not dossier_path.exists():
                continue
            dossier = json.loads(dossier_path.read_text(encoding="utf-8"))
            current_status = dict(dossier.get("current_status", {}))
            if not current_status:
                continue
            statuses[bundle_dir.name] = current_status
    return statuses


def build_source_approval_report(settings) -> dict[str, object]:
    manifest = _runtime_manifest_with_translation_overlay(settings)
    normalized_docs = read_jsonl(settings.normalized_docs_path)
    chunks = read_jsonl(settings.chunks_path)
    bundle_statuses = _bundle_status_by_slug(settings)
    reader_grade_failures = playbook_reader_grade_failures(settings)

    sections_by_book: dict[str, list[dict]] = {}
    for row in normalized_docs:
        sections_by_book.setdefault(str(row["book_slug"]), []).append(row)

    chunks_by_book: dict[str, list[dict]] = {}
    for row in chunks:
        chunks_by_book.setdefault(str(row["book_slug"]), []).append(row)

    per_book: list[dict[str, object]] = []
    counts: Counter[str] = Counter()

    for entry in manifest:
        runtime_entry = entry_with_collected_metadata(settings, entry)
        section_rows = sections_by_book.get(runtime_entry.book_slug, [])
        chunk_rows = chunks_by_book.get(runtime_entry.book_slug, [])
        html_path = settings.raw_html_dir / f"{runtime_entry.book_slug}.html"
        raw_html = html_path.read_text(encoding="utf-8") if html_path.exists() else ""
        fallback_detected = bool(LANGUAGE_FALLBACK_RE.search(raw_html))
        hangul_section_ratio = hangul_ratio([str(row.get("text", "")) for row in section_rows])
        hangul_chunk_ratio = hangul_ratio([str(row.get("text", "")) for row in chunk_rows])
        title_english_like = is_english_like_title(runtime_entry.title)
        runtime_fallback_detected = runtime_entry.fallback_detected or fallback_detected
        auto_status, auto_reason = classify_content_status(
            section_count=len(section_rows),
            chunk_count=len(chunk_rows),
            hangul_section_ratio=hangul_section_ratio,
            hangul_chunk_ratio=hangul_chunk_ratio,
            title_english_like=title_english_like,
            fallback_detected=runtime_fallback_detected,
        )
        bundle_status = bundle_statuses.get(runtime_entry.book_slug, {})
        bundle_content_status = str(bundle_status.get("content_status", "")).strip()
        allow_manual_synthesis_override = True
        if bundle_content_status in {
            CONTENT_STATUS_TRANSLATED_KO_DRAFT,
            CONTENT_STATUS_MIXED,
            CONTENT_STATUS_EN_ONLY,
            CONTENT_STATUS_BLOCKED,
        }:
            auto_status = bundle_content_status
            auto_reason = f"bronze bundle dossier marks {bundle_content_status}"
            allow_manual_synthesis_override = False
        content_status, citation_eligible, citation_block_reason, approval_status = (
            resolve_final_content_status(
                runtime_entry,
                auto_status=auto_status,
                auto_reason=auto_reason,
                allow_manual_synthesis_override=allow_manual_synthesis_override,
            )
        )
        approval_notes = runtime_entry.approval_notes
        reader_grade_failure = reader_grade_failures.get(runtime_entry.book_slug)
        if reader_grade_failure is not None and content_status == CONTENT_STATUS_APPROVED_KO:
            content_status = CONTENT_STATUS_BLOCKED
            citation_eligible = False
            citation_block_reason = "manualbook reader-grade audit failed"
            approval_status = "needs_review"
            failure_bits: list[str] = []
            if not bool(reader_grade_failure.get("semantic_role_coverage_ok", True)):
                failure_bits.append(
                    f"unknown_section_share={reader_grade_failure.get('unknown_section_share', 0.0)}"
                )
            if not bool(reader_grade_failure.get("heading_language_ok", True)):
                failure_bits.append(
                    f"english_heading_ratio={reader_grade_failure.get('english_heading_ratio', 0.0)}"
                )
            suffix = (
                "manualbook reader-grade audit failed"
                if not failure_bits
                else "manualbook reader-grade audit failed: " + ", ".join(failure_bits)
            )
            approval_notes = f"{approval_notes}; {suffix}".strip("; ").strip()
        body_language = body_language_guess(
            hangul_chunk_ratio=hangul_chunk_ratio,
            fallback_detected=runtime_fallback_detected,
        )
        viewer_strategy = "internal_text"
        gap_lane, gap_priority, gap_action = classify_gap_lane(
            book_slug=runtime_entry.book_slug,
            high_value=runtime_entry.high_value,
            content_status=content_status,
            fallback_detected=runtime_fallback_detected,
        )
        translation_lane = build_translation_metadata(
            runtime_entry,
            content_status=content_status,
            citation_eligible=citation_eligible,
            corpus_dir=getattr(settings, "corpus_dir", None),
        )
        source_lane = _runtime_source_lane(runtime_entry, content_status)
        review_status = _runtime_review_status(runtime_entry, approval_status)
        if reader_grade_failure is not None and content_status == CONTENT_STATUS_BLOCKED:
            review_status = "needs_review"

        record = {
            "product_slug": runtime_entry.product_slug,
            "ocp_version": runtime_entry.ocp_version,
            "docs_language": runtime_entry.docs_language,
            "source_kind": runtime_entry.source_kind,
            "book_slug": runtime_entry.book_slug,
            "title": runtime_entry.title,
            "vendor_title": runtime_entry.vendor_title or runtime_entry.title,
            "high_value": runtime_entry.high_value,
            "section_count": len(section_rows),
            "chunk_count": len(chunk_rows),
            "hangul_section_ratio": hangul_section_ratio,
            "hangul_chunk_ratio": hangul_chunk_ratio,
            "title_english_like": title_english_like,
            "fallback_detected": runtime_fallback_detected,
            "body_language_guess": body_language,
            "content_status": content_status,
            "citation_eligible": citation_eligible,
            "citation_block_reason": citation_block_reason,
            "viewer_strategy": viewer_strategy,
            "approval_status": approval_status,
            "approval_notes": approval_notes,
            "source_fingerprint": runtime_entry.source_fingerprint,
            "index_url": runtime_entry.index_url,
            "source_url": runtime_entry.source_url,
            "resolved_source_url": runtime_entry.resolved_source_url,
            "resolved_language": runtime_entry.resolved_language,
            "source_state": runtime_entry.source_state,
            "source_state_reason": runtime_entry.source_state_reason,
            "catalog_source_label": runtime_entry.catalog_source_label,
            "viewer_path": runtime_entry.viewer_path,
            "source_id": _resolved_source_id(runtime_entry),
            "source_lane": source_lane,
            "source_type": runtime_entry.source_type,
            "source_collection": runtime_entry.source_collection or "core",
            "legal_notice_url": runtime_entry.legal_notice_url,
            "original_title": runtime_entry.original_title or runtime_entry.vendor_title or runtime_entry.title,
            "license_or_terms": runtime_entry.license_or_terms,
            "review_status": review_status,
            "trust_score": runtime_entry.trust_score,
            "verifiability": runtime_entry.verifiability,
            "updated_at": runtime_entry.updated_at,
            "translation_source_language": runtime_entry.translation_source_language,
            "translation_target_language": runtime_entry.translation_target_language,
            "translation_source_url": runtime_entry.translation_source_url,
            "translation_source_fingerprint": runtime_entry.translation_source_fingerprint,
            "translation_stage": runtime_entry.translation_stage,
            "gap_lane": gap_lane,
            "gap_priority": gap_priority,
            "gap_action": gap_action,
            "translation_lane": translation_lane,
            "manualbook_reader_grade_failed": reader_grade_failure is not None,
            "manualbook_reader_grade": reader_grade_failure or {},
        }
        counts[content_status] += 1
        per_book.append(record)

    per_book.sort(
        key=lambda item: (
            CONTENT_STATUS_SORT_ORDER.get(str(item["content_status"]), 9),
            -int(bool(item["high_value"])),
            str(item["book_slug"]),
        )
    )

    high_value_issues = [
        item for item in per_book if item["high_value"] and item["content_status"] != CONTENT_STATUS_APPROVED_KO
    ]
    gap_lane_counts = Counter(str(item["gap_lane"]) for item in high_value_issues)

    return {
        "summary": {
            "book_count": len(per_book),
            "approved_ko_count": counts[CONTENT_STATUS_APPROVED_KO],
            "translated_ko_draft_count": counts[CONTENT_STATUS_TRANSLATED_KO_DRAFT],
            "mixed_count": counts[CONTENT_STATUS_MIXED],
            "en_only_count": counts[CONTENT_STATUS_EN_ONLY],
            "blocked_count": counts[CONTENT_STATUS_BLOCKED],
            "high_value_issue_count": len(high_value_issues),
        },
        "policy": {
            "product_scope": "ocp_playbook_studio",
            "primary_source": "openshift-docs repo AsciiDoc first with docs.redhat HTML fallback",
            "change_feed_candidate": "github.com/openshift/openshift-docs",
            "citation_default_statuses": list(CITATION_ELIGIBLE_STATUSES),
            "translation_lane_statuses": [CONTENT_STATUS_TRANSLATED_KO_DRAFT],
        },
        "gap_summary": {
            "translation_first_count": gap_lane_counts[LANE_TRANSLATION_FIRST],
            "manual_review_first_count": gap_lane_counts[LANE_MANUAL_REVIEW_FIRST],
            "other_gap_count": len(high_value_issues)
            - gap_lane_counts[LANE_TRANSLATION_FIRST]
            - gap_lane_counts[LANE_MANUAL_REVIEW_FIRST],
        },
        "high_value_issues": high_value_issues,
        "books": per_book,
    }


def _entry_identity(entry: SourceManifestEntry) -> tuple[str, str, str, str]:
    return (
        entry.ocp_version,
        entry.docs_language,
        entry.source_kind,
        entry.book_slug,
    )


def _resolved_source_id(entry: SourceManifestEntry) -> str:
    explicit = (entry.source_id or "").strip()
    if explicit:
        return explicit
    return f"{entry.product_slug}:{entry.ocp_version}:{entry.docs_language}:{entry.book_slug}"


def _runtime_source_lane(entry: SourceManifestEntry, content_status: str) -> str:
    explicit = (entry.source_lane or "").strip()
    if explicit:
        return explicit
    if entry.source_type in {
        "official_issue",
        "official_pr",
        "community_issue",
        "community_blog",
        "internal_runbook",
        "manual_synthesis",
    }:
        return "applied_playbook"
    if content_status in {CONTENT_STATUS_EN_ONLY, CONTENT_STATUS_MIXED, CONTENT_STATUS_TRANSLATED_KO_DRAFT}:
        return "official_en_fallback"
    return "official_ko"


def _runtime_review_status(entry: SourceManifestEntry, approval_status: str) -> str:
    current = (entry.review_status or "").strip()
    if current == "rejected":
        return current
    if approval_status == "needs_review":
        return "needs_review"
    if approval_status == "approved" and current in {"", "unreviewed", "needs_review"}:
        return "approved"
    if current in {"", "unreviewed"}:
        return approval_status
    return current


def _runtime_manifest_with_translation_overlay(settings) -> list[SourceManifestEntry]:
    manifest = runtime_catalog_entries(read_manifest(settings.source_catalog_path), settings)
    overlay_map: dict[tuple[str, str, str, str], SourceManifestEntry] = {}
    translation_manifest_path = getattr(settings, "translation_draft_manifest_path", None)
    if translation_manifest_path is not None and Path(translation_manifest_path).exists():
        for entry in read_manifest(Path(translation_manifest_path)):
            overlay_map[_entry_identity(entry)] = entry

    approved_manifest_path = getattr(settings, "source_manifest_path", None)
    if approved_manifest_path is not None and Path(approved_manifest_path).exists():
        for entry in read_manifest(Path(approved_manifest_path)):
            overlay_map[_entry_identity(entry)] = entry
    for entry in _approved_manual_synthesis_entries_from_playbooks(settings):
        overlay_map.setdefault(_entry_identity(entry), entry)

    if not overlay_map:
        return manifest

    merged: list[SourceManifestEntry] = []
    seen = set()
    for entry in manifest:
        key = _entry_identity(entry)
        merged.append(overlay_map.get(key, entry))
        seen.add(key)
    for entry in overlay_map.values():
        key = _entry_identity(entry)
        if key not in seen:
            merged.append(entry)
    return merged


def _approved_manual_synthesis_entries_from_playbooks(settings) -> list[SourceManifestEntry]:
    playbook_documents_path = getattr(settings, "playbook_documents_path", None)
    if playbook_documents_path is None:
        return []
    path = Path(playbook_documents_path)
    if not path.exists():
        return []
    entries: list[SourceManifestEntry] = []
    for row in read_jsonl(path):
        source_metadata = dict(row.get("source_metadata", {}))
        if str(source_metadata.get("source_type") or "").strip() != "manual_synthesis":
            continue
        if str(row.get("translation_status") or "").strip() != CONTENT_STATUS_APPROVED_KO:
            continue
        if str(row.get("review_status") or "").strip() != "approved":
            continue
        slug = str(row.get("book_slug") or "").strip()
        if not slug:
            continue
        anchor_map = dict(row.get("anchor_map") or {})
        viewer_path = ""
        if anchor_map:
            viewer_path = str(next(iter(anchor_map.values()), "")).split("#", 1)[0]
        if not viewer_path:
            viewer_path = str(
                getattr(settings, "viewer_path_template", "/docs/ocp/{version}/{lang}/{slug}/index.html")
            ).format(
                version=str(row.get("version") or getattr(settings, "ocp_version", "4.20")),
                lang=str(row.get("locale") or getattr(settings, "docs_language", "ko")),
                slug=slug,
            )
        source_uri = str(row.get("source_uri") or "")
        translation_source_uri = str(row.get("translation_source_uri") or "")
        entries.append(
            SourceManifestEntry(
                product_slug="openshift_container_platform",
                ocp_version=str(row.get("version") or getattr(settings, "ocp_version", "4.20")),
                docs_language=str(row.get("locale") or getattr(settings, "docs_language", "ko")),
                source_kind="html-single",
                book_slug=slug,
                title=str(row.get("title") or slug),
                index_url=source_uri,
                source_url=source_uri,
                resolved_source_url=source_uri,
                resolved_language=str(row.get("locale") or getattr(settings, "docs_language", "ko")),
                source_state="published_native",
                source_state_reason="preserved_manual_synthesis_from_gold_manualbook",
                catalog_source_label="curated gold manual synthesis",
                viewer_path=viewer_path,
                high_value=True,
                vendor_title=str(source_metadata.get("original_title") or row.get("title") or slug),
                content_status=CONTENT_STATUS_APPROVED_KO,
                citation_eligible=True,
                citation_block_reason="",
                viewer_strategy="internal_text",
                body_language_guess="ko",
                hangul_section_ratio=1.0,
                hangul_chunk_ratio=1.0,
                fallback_detected=False,
                source_fingerprint=str(row.get("translation_source_fingerprint") or source_uri),
                approval_status="approved",
                approval_notes="preserved approved manual_synthesis entry from gold manualbook",
                source_id=str(source_metadata.get("source_id") or f"manual_synthesis:{slug}"),
                source_lane=str(source_metadata.get("source_lane") or "applied_playbook"),
                source_type="manual_synthesis",
                source_collection=str(source_metadata.get("source_collection") or "core"),
                legal_notice_url=str(
                    row.get("legal_notice_url")
                    or source_metadata.get("legal_notice_url")
                    or ""
                ),
                original_title=str(source_metadata.get("original_title") or row.get("title") or slug),
                license_or_terms=str(source_metadata.get("license_or_terms") or ""),
                review_status="approved",
                trust_score=float(source_metadata.get("trust_score") or 1.0),
                verifiability=str(source_metadata.get("verifiability") or "anchor_backed"),
                updated_at=str(source_metadata.get("updated_at") or ""),
                translation_source_language=str(row.get("translation_source_language") or "en"),
                translation_target_language=str(row.get("locale") or getattr(settings, "docs_language", "ko")),
                translation_source_url=translation_source_uri,
                translation_source_fingerprint=str(row.get("translation_source_fingerprint") or ""),
                translation_stage=str(row.get("translation_stage") or CONTENT_STATUS_APPROVED_KO),
            )
        )
    return entries


def build_translation_lane_report(settings) -> dict[str, object]:
    approval_report = build_source_approval_report(settings)
    books = list(approval_report["books"])
    stage_counts: Counter[str] = Counter(
        str(item.get("translation_lane", {}).get("stage", "unknown")) for item in books
    )
    active_queue = [
        item
        for item in books
        if str(item.get("translation_lane", {}).get("stage", "")) != TRANSLATION_STAGE_APPROVED
    ]
    return {
        "summary": {
            "book_count": len(books),
            "approved_ko_count": stage_counts[TRANSLATION_STAGE_APPROVED],
            "translated_ko_draft_count": stage_counts[CONTENT_STATUS_TRANSLATED_KO_DRAFT],
            "translation_required_count": stage_counts[CONTENT_STATUS_EN_ONLY],
            "mixed_review_count": stage_counts["mixed_review"],
            "blocked_count": stage_counts[CONTENT_STATUS_BLOCKED],
            "active_queue_count": len(active_queue),
        },
        "policy": {
            "lane_flow": [
                CONTENT_STATUS_EN_ONLY,
                CONTENT_STATUS_TRANSLATED_KO_DRAFT,
                CONTENT_STATUS_APPROVED_KO,
            ],
            "runtime_gate_statuses": list(CITATION_ELIGIBLE_STATUSES),
            "translation_default_target_language": getattr(settings, "docs_language", "ko"),
        },
        "active_queue": active_queue,
        "books": books,
    }


def build_corpus_gap_report(settings) -> dict[str, object]:
    approval_report = build_source_approval_report(settings)
    high_value_issues = list(approval_report["high_value_issues"])
    ordered_issues = sorted(
        high_value_issues,
        key=lambda item: (
            int(item["gap_priority"]),
            str(item["book_slug"]),
        ),
    )

    translation_first = [item for item in ordered_issues if item["gap_lane"] == LANE_TRANSLATION_FIRST]
    manual_review_first = [item for item in ordered_issues if item["gap_lane"] == LANE_MANUAL_REVIEW_FIRST]
    remaining = [
        item
        for item in ordered_issues
        if item["gap_lane"] not in {LANE_TRANSLATION_FIRST, LANE_MANUAL_REVIEW_FIRST}
    ]

    return {
        "summary": {
            "high_value_issue_count": len(ordered_issues),
            "translation_first_count": len(translation_first),
            "manual_review_first_count": len(manual_review_first),
            "remaining_gap_count": len(remaining),
        },
        "translation_first": translation_first,
        "manual_review_first": manual_review_first,
        "remaining_gaps": remaining,
    }


def build_approved_manifest(
    settings,
    *,
    allowed_statuses: tuple[str, ...] = (CONTENT_STATUS_APPROVED_KO,),
) -> list[SourceManifestEntry]:
    approval_report = build_source_approval_report(settings)
    books = approval_report["books"]
    entries: list[SourceManifestEntry] = []

    for item in books:
        if item["content_status"] not in allowed_statuses:
            continue
        entries.append(
            SourceManifestEntry(
                product_slug=str(item.get("product_slug", "openshift_container_platform")),
                ocp_version=str(item.get("ocp_version", getattr(settings, "ocp_version", "4.20"))),
                docs_language=str(item.get("docs_language", getattr(settings, "docs_language", "ko"))),
                source_kind=str(item.get("source_kind", "html-single")),
                book_slug=str(item["book_slug"]),
                title=str(item["title"]),
                index_url=str(item.get("index_url", "")),
                source_url=str(item["source_url"]),
                resolved_source_url=str(item.get("resolved_source_url", item["source_url"])),
                resolved_language=str(item.get("resolved_language", item.get("docs_language", getattr(settings, "docs_language", "ko")))),
                source_state=str(item.get("source_state", "published_native")),
                source_state_reason=str(item.get("source_state_reason", "")),
                catalog_source_label=str(item.get("catalog_source_label", "docs.redhat.com published OCP html-single catalog")),
                viewer_path=str(item["viewer_path"]),
                high_value=bool(item["high_value"]),
                vendor_title=str(item["vendor_title"]),
                content_status=str(item["content_status"]),
                citation_eligible=bool(item["citation_eligible"]),
                citation_block_reason=str(item["citation_block_reason"]),
                viewer_strategy=str(item["viewer_strategy"]),
                body_language_guess=str(item["body_language_guess"]),
                hangul_section_ratio=float(item["hangul_section_ratio"]),
                hangul_chunk_ratio=float(item["hangul_chunk_ratio"]),
                fallback_detected=bool(item["fallback_detected"]),
                source_fingerprint=str(item["source_fingerprint"]),
                approval_status=str(item["approval_status"]),
                approval_notes=str(item["approval_notes"]),
                source_id=str(item.get("source_id", "")),
                source_lane=str(item.get("source_lane", "")),
                source_type=str(item.get("source_type", "official_doc")),
                source_collection=str(item.get("source_collection", "core")),
                legal_notice_url=str(item.get("legal_notice_url", "")),
                original_title=str(item.get("original_title", "")),
                license_or_terms=str(item.get("license_or_terms", "")),
                review_status=str(item.get("review_status", "unreviewed")),
                trust_score=float(item.get("trust_score", 1.0)),
                verifiability=str(item.get("verifiability", "anchor_backed")),
                updated_at=str(item.get("updated_at", "")),
                translation_source_language=str(item.get("translation_source_language", "")),
                translation_target_language=str(item.get("translation_target_language", getattr(settings, "docs_language", "ko"))),
                translation_source_url=str(item.get("translation_source_url", "")),
                translation_source_fingerprint=str(item.get("translation_source_fingerprint", "")),
                translation_stage=str(item.get("translation_stage", "")),
            )
        )
    approved_by_slug = {entry.book_slug: entry for entry in entries}
    reader_grade_failure_slugs = set(playbook_reader_grade_failures(settings))
    bundle_statuses = _bundle_status_by_slug(settings)
    for entry in _approved_manual_synthesis_entries_from_playbooks(settings):
        if entry.book_slug in reader_grade_failure_slugs:
            continue
        bundle_content_status = str(
            dict(bundle_statuses.get(entry.book_slug, {})).get("content_status", "")
        ).strip()
        if bundle_content_status and bundle_content_status != CONTENT_STATUS_APPROVED_KO:
            continue
        approved_by_slug.setdefault(entry.book_slug, entry)
    return sorted(approved_by_slug.values(), key=lambda entry: entry.book_slug)


def write_approved_manifest(
    path: Path,
    entries: list[SourceManifestEntry],
) -> None:
    write_manifest(path, entries)
