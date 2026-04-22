"""repo/AsciiDoc source를 canonical AST로 직접 조립한다."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from play_book_studio.config.packs import resolve_ocp_core_pack
from play_book_studio.ingestion.models import (
    CONTENT_STATUS_EN_ONLY,
    SOURCE_STATE_EN_ONLY,
    SourceManifestEntry,
)
from play_book_studio.ingestion.official_rebuild import (
    ASCIIDOC_ATTR_RE,
    ASCIIDOC_COMMENT_RE,
    ASCIIDOC_DIRECTIVE_RE,
    ASCIIDOC_HEADING_RE,
    ASCIIDOC_IMAGE_RE,
    _parse_source_language,
    _render_table,
    expand_asciidoc,
)
from play_book_studio.ingestion.translation_lane import build_translation_metadata

from .html import (
    _blocks_from_text,
    _infer_semantic_role,
    _postprocess_blocks,
    _resolved_source_id,
    _resolved_source_lane,
    _translation_status,
    _trim_leading_noise_blocks,
    _unique_anchor,
)
from .models import AstProvenance, CanonicalDocumentAst, CanonicalSectionAst


ASCIIDOC_ANCHOR_RE = re.compile(r"^\s*\[\[(?P<anchor>[^\]]+)\]\]\s*$")
ASCIIDOC_BLOCK_ID_RE = re.compile(r"^\s*\[#(?P<anchor>[^\],]+)(?:,[^\]]*)?\]\s*$")
ASCIIDOC_ADMONITION_RE = re.compile(r"^\[(?P<kind>NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*$", re.IGNORECASE)
ASCIIDOC_BLOCK_ATTR_RE = re.compile(r"^\[(?:[^\]]+)\]\s*$")
WHITESPACE_RE = re.compile(r"\s+")
UNRESOLVED_ATTR_ONLY_RE = re.compile(r"^\{[A-Za-z0-9_-]+\}$")


def _repo_source_url(entry: SourceManifestEntry) -> str:
    source_repo = str(entry.source_repo or "").strip().rstrip("/")
    source_branch = str(entry.source_branch or "").strip()
    source_relative_path = str(entry.source_relative_path or "").strip().lstrip("/")
    if source_repo and source_branch and source_relative_path:
        return f"{source_repo}/blob/{source_branch}/{source_relative_path}"
    return (
        str(entry.source_url or "").strip()
        or str(entry.resolved_source_url or "").strip()
        or source_relative_path
    )


def _normalize_anchor(text: str, fallback: str = "section") -> str:
    normalized = re.sub(r"[^\w\s-]", "", str(text or "").strip(), flags=re.UNICODE).strip().lower()
    normalized = re.sub(r"[\s_]+", "-", normalized)
    return normalized or fallback


def _normalize_text(text: str) -> str:
    lines = [line.rstrip() for line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").splitlines()]
    output: list[str] = []
    previous_blank = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if previous_blank:
                continue
            output.append("")
            previous_blank = True
            continue
        if stripped.startswith("+"):
            continue
        output.append(line)
        previous_blank = False
    return "\n".join(output).strip()


def _resolved_heading_text(raw_heading: str, *, fallback: str) -> str:
    cleaned = WHITESPACE_RE.sub(" ", str(raw_heading or "").strip()).strip()
    if UNRESOLVED_ATTR_ONLY_RE.fullmatch(cleaned):
        return str(fallback or "").strip() or cleaned
    return cleaned


def _admonition_text(kind: str, body_lines: list[str]) -> str:
    label_map = {
        "note": "Note",
        "tip": "Tip",
        "important": "Important",
        "warning": "Warning",
        "caution": "Caution",
    }
    label = label_map.get(kind.lower(), "Note")
    body = _normalize_text("\n".join(body_lines))
    if not body:
        return ""
    return f"{label}: {body}"


def _body_to_marked_text(body_lines: list[str]) -> str:
    output: list[str] = []
    pending_source_language: str | None = None
    index = 0
    while index < len(body_lines):
        raw_line = body_lines[index]
        stripped = raw_line.strip()

        admonition_match = ASCIIDOC_ADMONITION_RE.match(stripped)
        if admonition_match and index + 1 < len(body_lines) and body_lines[index + 1].strip() == "====":
            end = index + 2
            admonition_lines: list[str] = []
            while end < len(body_lines) and body_lines[end].strip() != "====":
                admonition_lines.append(body_lines[end])
                end += 1
            output.append(_admonition_text(str(admonition_match.group("kind") or ""), admonition_lines))
            output.append("")
            index = end + 1 if end < len(body_lines) else end
            continue

        parsed_language = _parse_source_language(raw_line)
        if parsed_language is not None:
            pending_source_language = parsed_language
            index += 1
            continue

        if stripped == "----" and pending_source_language is not None:
            code_lines: list[str] = []
            index += 1
            while index < len(body_lines) and body_lines[index].strip() != "----":
                code_lines.append(body_lines[index].rstrip())
                index += 1
            code = "\n".join(code_lines).strip("\n")
            if code.strip():
                output.extend(
                    [
                        f'[CODE language="{pending_source_language}"]',
                        code,
                        "[/CODE]",
                        "",
                    ]
                )
            pending_source_language = None
            index += 1
            continue

        pending_source_language = None

        if stripped == "|===":
            table_lines: list[str] = []
            index += 1
            while index < len(body_lines) and body_lines[index].strip() != "|===":
                table_lines.append(body_lines[index])
                index += 1
            rendered = _render_table(table_lines)
            if rendered:
                output.extend(["[TABLE]", *rendered, "[/TABLE]", ""])
            index += 1
            continue

        if (
            ASCIIDOC_ATTR_RE.match(stripped)
            or ASCIIDOC_DIRECTIVE_RE.match(stripped)
            or ASCIIDOC_IMAGE_RE.match(stripped)
            or ASCIIDOC_COMMENT_RE.match(stripped)
        ):
            index += 1
            continue

        if ASCIIDOC_BLOCK_ATTR_RE.match(stripped):
            index += 1
            continue

        output.append(raw_line.rstrip())
        index += 1

    return _normalize_text("\n".join(output))


def _flush_section(
    sections: list[dict[str, Any]],
    *,
    heading: str,
    anchor: str,
    level: int,
    path_by_level: dict[int, str],
    body_lines: list[str],
) -> None:
    body = _body_to_marked_text(body_lines)
    if not body:
        return
    section_path = tuple(value for key, value in sorted(path_by_level.items()) if key >= 2 and value)
    sections.append(
        {
            "heading": heading,
            "anchor": anchor,
            "section_level": level,
            "section_path": list(section_path or (heading,)),
            "text": body,
        }
    )


def parse_asciidoc_sections(*, text: str, fallback_title: str) -> tuple[str, list[dict[str, Any]]]:
    doc_title = str(fallback_title or "").strip() or "Untitled"
    sections: list[dict[str, Any]] = []
    path_by_level: dict[int, str] = {}
    current_heading = ""
    current_anchor = ""
    current_level = 2
    current_lines: list[str] = []
    preamble_lines: list[str] = []
    pending_anchor = ""
    seen_document_title = False

    for raw_line in str(text or "").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            if current_heading:
                current_lines.append("")
            else:
                preamble_lines.append("")
            continue

        anchor_match = ASCIIDOC_ANCHOR_RE.match(stripped) or ASCIIDOC_BLOCK_ID_RE.match(stripped)
        if anchor_match is not None:
            pending_anchor = _normalize_anchor(str(anchor_match.group("anchor") or "section"))
            continue

        heading_match = ASCIIDOC_HEADING_RE.match(stripped)
        if heading_match is not None:
            level = len(str(heading_match.group("marks") or ""))
            heading = _resolved_heading_text(
                str(heading_match.group("title") or ""),
                fallback=doc_title if seen_document_title else fallback_title,
            )
            if level == 1 and not seen_document_title:
                doc_title = heading or doc_title
                path_by_level = {1: doc_title}
                seen_document_title = True
                pending_anchor = ""
                continue
            if current_heading:
                _flush_section(
                    sections,
                    heading=current_heading,
                    anchor=current_anchor,
                    level=current_level,
                    path_by_level=path_by_level,
                    body_lines=current_lines,
                )
                current_lines = []
            path_by_level[level] = heading
            for deeper_level in list(path_by_level):
                if deeper_level > level:
                    del path_by_level[deeper_level]
            current_heading = heading
            current_anchor = pending_anchor or _normalize_anchor(heading)
            current_level = max(2, level)
            pending_anchor = ""
            continue

        if current_heading:
            current_lines.append(raw_line.rstrip())
        else:
            preamble_lines.append(raw_line.rstrip())

    if current_heading:
        _flush_section(
            sections,
            heading=current_heading,
            anchor=current_anchor,
            level=current_level,
            path_by_level=path_by_level,
            body_lines=current_lines,
        )

    preamble = _body_to_marked_text(preamble_lines)
    if preamble:
        sections.insert(
            0,
            {
                "heading": doc_title,
                "anchor": "overview",
                "section_level": 2,
                "section_path": [doc_title],
                "text": preamble,
            },
        )

    if not sections:
        sections.append(
            {
                "heading": doc_title,
                "anchor": "overview",
                "section_level": 2,
                "section_path": [doc_title],
                "text": "",
            }
        )

    return doc_title, sections


def build_source_repo_document_ast(
    *,
    entry: SourceManifestEntry,
    source_paths: list[Path],
    fallback_title: str,
) -> CanonicalDocumentAst:
    expanded_parts: list[str] = []
    for source_path in source_paths:
        expanded = expand_asciidoc(source_path)
        if expanded.strip():
            expanded_parts.append(expanded.strip())
    expanded_text = "\n\n".join(expanded_parts).strip()
    book_title, parsed_sections = parse_asciidoc_sections(text=expanded_text, fallback_title=fallback_title)
    pack = resolve_ocp_core_pack(
        version=entry.ocp_version or "4.20",
        language=entry.docs_language or "ko",
    )
    source_url = _repo_source_url(entry)
    sections: list[CanonicalSectionAst] = []
    seen_anchors: dict[str, int] = {}
    for ordinal, section in enumerate(parsed_sections, start=1):
        heading = str(section.get("heading") or "").strip() or book_title
        anchor = _unique_anchor(str(section.get("anchor") or "").strip(), seen_anchors)
        text = str(section.get("text") or "").strip()
        path = tuple(
            str(part).strip()
            for part in (section.get("section_path") or [])
            if str(part).strip()
        )
        blocks = _postprocess_blocks(_trim_leading_noise_blocks(_blocks_from_text(text)))
        semantic_role = _infer_semantic_role(
            book_slug=entry.book_slug,
            book_title=book_title,
            heading=heading,
            path=path,
            blocks=blocks,
        )
        sections.append(
            CanonicalSectionAst(
                section_id=f"{entry.book_slug}:{anchor}",
                ordinal=ordinal,
                heading=heading,
                level=int(section.get("section_level") or 2),
                path=path or (heading,),
                anchor=anchor,
                source_url=source_url,
                viewer_path=f"{entry.viewer_path}#{anchor}",
                semantic_role=semantic_role,
                blocks=blocks,
            )
        )

    translation = build_translation_metadata(entry, content_status=entry.content_status)
    review_status = (entry.review_status or entry.approval_status or "unreviewed").strip() or "unreviewed"
    approval_state = (entry.approval_state or review_status).strip() or "unreviewed"
    if approval_state == "needs_review":
        approval_state = "review_required"
    publication_state = (entry.publication_state or "").strip() or "candidate"
    provenance_notes = ("source_repo_first",)

    return CanonicalDocumentAst(
        doc_id=f"{entry.book_slug}:{entry.ocp_version}:{entry.docs_language}:source_repo",
        book_slug=entry.book_slug,
        title=book_title,
        source_type="repo",
        source_url=source_url,
        viewer_base_path=entry.viewer_path,
        source_language=entry.resolved_language or "en",
        display_language=entry.docs_language or "ko",
        translation_status=_translation_status(entry),
        pack_id=pack.pack_id,
        pack_label=pack.pack_label,
        inferred_product=pack.product_key,
        inferred_version=pack.version,
        sections=tuple(sections),
        notes=provenance_notes,
        provenance=AstProvenance(
            source_id=_resolved_source_id(entry),
            source_lane=(entry.source_lane or "official_source_first").strip() or "official_source_first",
            source_type=(entry.source_type or "official_doc").strip() or "official_doc",
            source_collection=(entry.source_collection or "core").strip() or "core",
            product=pack.product_key,
            version=pack.version,
            locale=entry.docs_language or "ko",
            original_title=entry.original_title or entry.title or book_title,
            legal_notice_url=entry.legal_notice_url,
            license_or_terms=entry.license_or_terms,
            review_status=review_status,
            trust_score=float(entry.trust_score or 1.0),
            verifiability=(entry.verifiability or "repo_anchor_backed").strip() or "repo_anchor_backed",
            updated_at=entry.updated_at,
            capture_uri=source_url,
            source_fingerprint=entry.source_fingerprint,
            parser_name="canonical_source_repo_v1",
            parser_version="1.0",
            source_state=(entry.source_state or SOURCE_STATE_EN_ONLY).strip() or SOURCE_STATE_EN_ONLY,
            content_status=(entry.content_status or CONTENT_STATUS_EN_ONLY).strip() or CONTENT_STATUS_EN_ONLY,
            translation_stage=str(translation["stage"]),
            translation_source_language=str(translation["source_language"]),
            translation_target_language=str(translation["target_language"]),
            translation_source_url=str(translation["source_url"]),
            translation_source_fingerprint=str(translation["source_fingerprint"]),
            parsed_artifact_id=f"parsed:{_resolved_source_id(entry)}",
            tenant_id=(entry.tenant_id or "public").strip() or "public",
            workspace_id=(entry.workspace_id or "core").strip() or "core",
            pack_id=(entry.pack_id or pack.pack_id).strip() or pack.pack_id,
            pack_version=(entry.pack_version or pack.version).strip() or pack.version,
            bundle_scope=(entry.bundle_scope or "official").strip() or "official",
            classification=(entry.classification or "public").strip() or "public",
            access_groups=tuple(group for group in entry.access_groups if str(group).strip()) or ("public",),
            provider_egress_policy=(entry.provider_egress_policy or "unspecified").strip() or "unspecified",
            approval_state=approval_state,
            publication_state=publication_state,
            redaction_state=(entry.redaction_state or "not_required").strip() or "not_required",
            citation_eligible=bool(entry.citation_eligible),
            citation_block_reason=entry.citation_block_reason,
            primary_input_kind=(entry.primary_input_kind or "source_repo").strip() or "source_repo",
            source_repo=(entry.source_repo or "").strip(),
            source_branch=(entry.source_branch or "").strip(),
            source_binding_kind=(entry.source_binding_kind or "").strip(),
            source_relative_path=(entry.source_relative_path or "").strip(),
            source_relative_paths=tuple(
                str(item).strip() for item in entry.source_relative_paths if str(item).strip()
            ),
            source_mirror_root=(entry.source_mirror_root or "").strip(),
            fallback_input_kind=(entry.fallback_input_kind or "").strip(),
            fallback_source_url=(entry.fallback_source_url or "").strip(),
            fallback_viewer_path=(entry.fallback_viewer_path or "").strip(),
            notes=provenance_notes,
        ),
    )


__all__ = [
    "build_source_repo_document_ast",
    "parse_asciidoc_sections",
]
