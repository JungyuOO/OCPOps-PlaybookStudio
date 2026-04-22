from __future__ import annotations

from pathlib import Path
from typing import Any

from play_book_studio.config.validation import read_jsonl

from .metadata_extraction import extract_section_metadata
from .models import NormalizedSection


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _code_marker(block: dict[str, Any]) -> str:
    code = str(block.get("code") or "").strip()
    if not code:
        return ""
    language = str(block.get("language") or "shell").strip() or "shell"
    caption = str(block.get("caption") or "").strip()
    attrs: list[str] = [f'language="{language}"']
    if caption:
        attrs.append(f'caption="{caption}"')
    return "[CODE {attrs}]\n{code}\n[/CODE]".format(
        attrs=" ".join(attrs),
        code=code,
    )


def _table_marker(block: dict[str, Any]) -> str:
    headers = [str(item).strip() for item in (block.get("headers") or []) if str(item).strip()]
    rows = [
        [str(cell).strip() for cell in row if str(cell).strip()]
        for row in (block.get("rows") or [])
        if isinstance(row, list)
    ]
    lines: list[str] = []
    if headers:
        lines.append(" | ".join(headers))
    for row in rows:
        if row:
            lines.append(" | ".join(row))
    table_text = "\n".join(line for line in lines if line.strip()).strip()
    if not table_text:
        return ""
    caption = str(block.get("caption") or "").strip()
    attrs = f' caption="{caption}"' if caption else ""
    return "[TABLE{attrs}]\n{table}\n[/TABLE]".format(attrs=attrs, table=table_text)


def _block_text(block: dict[str, Any]) -> str:
    kind = str(block.get("kind") or "").strip().lower()
    if kind == "paragraph":
        return str(block.get("text") or "").strip()
    if kind == "prerequisite":
        return "\n".join(
            f"- {item.strip()}"
            for item in (str(value) for value in (block.get("items") or []))
            if item.strip()
        )
    if kind == "procedure":
        lines: list[str] = []
        for step in block.get("steps") or []:
            if not isinstance(step, dict):
                continue
            text = str(step.get("text") or "").strip()
            if not text:
                continue
            ordinal = step.get("ordinal")
            prefix = f"{ordinal}. " if ordinal not in (None, "") else ""
            lines.append(f"{prefix}{text}".strip())
            for substep in step.get("substeps") or []:
                substep_text = str(substep).strip()
                if substep_text:
                    lines.append(f"- {substep_text}")
        return "\n".join(lines)
    if kind == "code":
        return _code_marker(block)
    if kind == "table":
        return _table_marker(block)
    if kind == "note":
        title = str(block.get("title") or "").strip()
        text = str(block.get("text") or "").strip()
        if title and text:
            return f"{title}\n{text}"
        return title or text
    if kind == "anchor":
        return ""
    parts: list[str] = []
    for key in ("title", "text", "caption", "code"):
        value = str(block.get(key) or "").strip()
        if value:
            parts.append(value)
    return "\n".join(parts).strip()


def _section_text(section: dict[str, Any]) -> str:
    fragments = [
        _block_text(block)
        for block in (section.get("blocks") or [])
        if isinstance(block, dict)
    ]
    return "\n\n".join(fragment for fragment in fragments if fragment).strip()


def load_approved_playbook_payload(
    settings,
    book_slug: str,
    *,
    source_type: str | None = None,
) -> dict[str, Any] | None:
    path = Path(settings.playbook_documents_path)
    if not path.exists():
        return None
    for row in read_jsonl(path):
        slug = str(row.get("book_slug") or "").strip()
        if slug != book_slug:
            continue
        if str(row.get("translation_status") or row.get("translation_stage") or "").strip() != "approved_ko":
            continue
        if str(row.get("review_status") or "").strip() != "approved":
            continue
        source_metadata = row.get("source_metadata") if isinstance(row.get("source_metadata"), dict) else {}
        row_source_type = str(source_metadata.get("source_type") or row.get("source_type") or "").strip()
        if source_type is not None and row_source_type != source_type:
            continue
        return dict(row)
    return None


def project_playbook_payload_sections(row: dict[str, Any]) -> list[NormalizedSection]:
    source_metadata = row.get("source_metadata") if isinstance(row.get("source_metadata"), dict) else {}
    access_groups = tuple(
        str(group).strip()
        for group in (source_metadata.get("access_groups") or [])
        if str(group).strip()
    )
    sections: list[NormalizedSection] = []
    for section in row.get("sections") or []:
        if not isinstance(section, dict):
            continue
        text = _section_text(section)
        if not text:
            continue
        heading = str(section.get("heading") or "").strip() or str(row.get("title") or "").strip()
        section_path = [
            str(item).strip()
            for item in (section.get("section_path") or section.get("path") or [heading])
            if str(item).strip()
        ]
        block_kinds = tuple(
            str(block.get("kind") or "").strip()
            for block in (section.get("blocks") or [])
            if isinstance(block, dict) and str(block.get("kind") or "").strip()
        )
        source_url = (
            str(row.get("source_uri") or "").strip()
            or str(source_metadata.get("original_url") or "").strip()
        )
        base_section = NormalizedSection(
            book_slug=str(row.get("book_slug") or "").strip(),
            book_title=str(row.get("title") or "").strip() or str(row.get("book_slug") or "").strip(),
            heading=heading,
            section_level=int(section.get("level") or 2),
            section_path=section_path,
            anchor=str(section.get("anchor") or "").strip(),
            source_url=source_url,
            viewer_path=str(section.get("viewer_path") or "").strip(),
            text=text,
            section_id=str(section.get("section_id") or "").strip(),
            semantic_role=str(section.get("semantic_role") or "reference").strip() or "reference",
            block_kinds=block_kinds,
            source_language=str(row.get("source_language") or "ko").strip() or "ko",
            display_language=str(row.get("language_hint") or row.get("locale") or "ko").strip() or "ko",
            translation_status=str(row.get("translation_status") or "approved_ko").strip() or "approved_ko",
            translation_stage=str(row.get("translation_stage") or row.get("translation_status") or "approved_ko").strip() or "approved_ko",
            translation_source_language=str(row.get("translation_source_language") or source_metadata.get("translation_source_language") or "").strip(),
            translation_source_url=str(row.get("translation_source_uri") or source_metadata.get("translation_source_url") or "").strip(),
            translation_source_fingerprint=str(row.get("translation_source_fingerprint") or source_metadata.get("translation_source_fingerprint") or "").strip(),
            source_id=str(source_metadata.get("source_id") or "").strip(),
            source_lane=str(source_metadata.get("source_lane") or row.get("source_lane") or "applied_playbook").strip() or "applied_playbook",
            source_type=str(source_metadata.get("source_type") or row.get("source_type") or "manual_synthesis").strip() or "manual_synthesis",
            source_collection=str(source_metadata.get("source_collection") or "core").strip() or "core",
            product=str(source_metadata.get("product") or "openshift").strip() or "openshift",
            version=str(row.get("version") or source_metadata.get("version") or "4.20").strip() or "4.20",
            locale=str(row.get("locale") or source_metadata.get("locale") or "ko").strip() or "ko",
            original_title=str(source_metadata.get("original_title") or row.get("title") or "").strip(),
            legal_notice_url=str(row.get("legal_notice_url") or source_metadata.get("legal_notice_url") or "").strip(),
            license_or_terms=str(source_metadata.get("license_or_terms") or "").strip(),
            review_status=str(row.get("review_status") or source_metadata.get("review_status") or "approved").strip() or "approved",
            trust_score=float(source_metadata.get("trust_score") or row.get("quality_score") or 1.0),
            verifiability=str(source_metadata.get("verifiability") or "anchor_backed").strip() or "anchor_backed",
            updated_at=str(source_metadata.get("updated_at") or row.get("updated_at") or "").strip(),
            parsed_artifact_id=str(source_metadata.get("parsed_artifact_id") or "").strip(),
            tenant_id=str(source_metadata.get("tenant_id") or "public").strip() or "public",
            workspace_id=str(source_metadata.get("workspace_id") or "core").strip() or "core",
            parent_pack_id=str(source_metadata.get("pack_id") or row.get("pack_id") or "").strip(),
            pack_version=str(source_metadata.get("pack_version") or row.get("inferred_version") or row.get("version") or "").strip(),
            bundle_scope=str(source_metadata.get("bundle_scope") or "official").strip() or "official",
            classification=str(source_metadata.get("classification") or "public").strip() or "public",
            access_groups=access_groups or ("public",),
            provider_egress_policy=str(source_metadata.get("provider_egress_policy") or "unspecified").strip() or "unspecified",
            approval_state=str(source_metadata.get("approval_state") or "").strip(),
            publication_state=str(source_metadata.get("publication_state") or "").strip(),
            redaction_state=str(source_metadata.get("redaction_state") or "not_required").strip() or "not_required",
        )
        metadata = extract_section_metadata(base_section)
        sections.append(
            NormalizedSection(
                book_slug=base_section.book_slug,
                book_title=base_section.book_title,
                heading=base_section.heading,
                section_level=base_section.section_level,
                section_path=base_section.section_path,
                anchor=base_section.anchor,
                source_url=base_section.source_url,
                viewer_path=base_section.viewer_path,
                text=base_section.text,
                section_id=base_section.section_id,
                semantic_role=base_section.semantic_role,
                block_kinds=base_section.block_kinds,
                source_language=base_section.source_language,
                display_language=base_section.display_language,
                translation_status=base_section.translation_status,
                translation_stage=base_section.translation_stage,
                translation_source_language=base_section.translation_source_language,
                translation_source_url=base_section.translation_source_url,
                translation_source_fingerprint=base_section.translation_source_fingerprint,
                source_id=base_section.source_id,
                source_lane=base_section.source_lane,
                source_type=base_section.source_type,
                source_collection=base_section.source_collection,
                product=base_section.product,
                version=base_section.version,
                locale=base_section.locale,
                original_title=base_section.original_title,
                legal_notice_url=base_section.legal_notice_url,
                license_or_terms=base_section.license_or_terms,
                review_status=base_section.review_status,
                trust_score=base_section.trust_score,
                verifiability=base_section.verifiability,
                updated_at=base_section.updated_at,
                parsed_artifact_id=base_section.parsed_artifact_id,
                tenant_id=base_section.tenant_id,
                workspace_id=base_section.workspace_id,
                parent_pack_id=base_section.parent_pack_id,
                pack_version=base_section.pack_version,
                bundle_scope=base_section.bundle_scope,
                classification=base_section.classification,
                access_groups=base_section.access_groups,
                provider_egress_policy=base_section.provider_egress_policy,
                approval_state=base_section.approval_state,
                publication_state=base_section.publication_state,
                redaction_state=base_section.redaction_state,
                cli_commands=metadata.cli_commands,
                error_strings=metadata.error_strings,
                k8s_objects=metadata.k8s_objects,
                operator_names=metadata.operator_names,
                verification_hints=metadata.verification_hints,
            )
        )
    return sections
