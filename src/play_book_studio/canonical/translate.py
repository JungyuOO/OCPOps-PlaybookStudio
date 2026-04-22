"""영문 fallback 문서를 한국어 draft AST로 바꾼다."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from play_book_studio.answering.llm import LLMClient
from play_book_studio.config.settings import Settings

from .ocp_ko_terminology import (
    normalize_ocp_ko_terminology,
    ocp_ko_terminology_prompt,
)
from .models import (
    AnchorBlock,
    AstBlock,
    CanonicalDocumentAst,
    CanonicalSectionAst,
    CodeBlock,
    NoteBlock,
    ParagraphBlock,
    PrerequisiteBlock,
    ProcedureBlock,
    ProcedureStep,
    TableBlock,
)


UNIT_BATCH_SIZE = 18
UNIT_BATCH_CHAR_LIMIT = 2600
MAX_SINGLE_TEXT_CHARS = 1200
TRANSLATION_BATCH_CONCURRENCY = 4
OCP_KO_TERMINOLOGY_PROMPT = ocp_ko_terminology_prompt()


@dataclass(slots=True, frozen=True)
class _TextUnit:
    unit_id: str
    text: str


def _translation_cache_dir(settings: Settings | object) -> Path | None:
    silver_ko_dir = getattr(settings, "silver_ko_dir", None)
    if silver_ko_dir is None:
        return None
    return Path(silver_ko_dir) / "translation_drafts" / "translation_cache"


def _translation_source_fingerprint(document: CanonicalDocumentAst) -> str:
    return (
        document.provenance.translation_source_fingerprint
        or document.provenance.source_fingerprint
        or document.book_slug
        or document.doc_id
    )


def _translation_cache_path(
    document: CanonicalDocumentAst,
    settings: Settings | object,
) -> Path | None:
    fingerprint = _translation_source_fingerprint(document)
    slug = (document.book_slug or document.doc_id or "document").strip() or "document"
    cache_dir = _translation_cache_dir(settings)
    if cache_dir is None:
        return None
    return cache_dir / f"{slug}.{fingerprint[:12]}.json"


def _load_translation_cache(
    document: CanonicalDocumentAst,
    settings: Settings | object,
) -> dict[str, str]:
    path = _translation_cache_path(document, settings)
    if path is None:
        return {}
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    expected_fingerprint = _translation_source_fingerprint(document)
    if str(payload.get("source_fingerprint") or "") != expected_fingerprint:
        return {}
    items = payload.get("items") or {}
    if not isinstance(items, dict):
        return {}
    return {
        str(unit_id).strip(): str(text).strip()
        for unit_id, text in items.items()
        if str(unit_id).strip() and str(text).strip()
    }


def _write_translation_cache(
    document: CanonicalDocumentAst,
    settings: Settings | object,
    translations: dict[str, str],
    *,
    progress: dict[str, Any] | None = None,
) -> None:
    path = _translation_cache_path(document, settings)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "book_slug": document.book_slug,
        "doc_id": document.doc_id,
        "source_fingerprint": _translation_source_fingerprint(document),
        "translation_source_url": (
            document.provenance.translation_source_url or document.source_url
        ),
        "item_count": len(translations),
        "items": translations,
    }
    if progress is not None:
        payload["progress"] = progress
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _strip_json_fence(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def _parse_json_payload(text: str) -> Any:
    cleaned = _strip_json_fence(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        obj_start = cleaned.find("{")
        obj_end = cleaned.rfind("}")
        if obj_start >= 0 and obj_end >= obj_start:
            return json.loads(cleaned[obj_start : obj_end + 1])
        arr_start = cleaned.find("[")
        arr_end = cleaned.rfind("]")
        if arr_start >= 0 and arr_end >= arr_start:
            return json.loads(cleaned[arr_start : arr_end + 1])
        raise


def _iter_text_units(document: CanonicalDocumentAst) -> list[_TextUnit]:
    units: list[_TextUnit] = []

    def add(unit_id: str, text: str) -> None:
        normalized = (text or "").strip()
        if normalized:
            units.append(_TextUnit(unit_id=unit_id, text=normalized))

    add("doc.title", document.title)
    for section_index, section in enumerate(document.sections):
        section_prefix = f"s{section_index}"
        add(f"{section_prefix}.heading", section.heading)
        for path_index, path_item in enumerate(section.path):
            add(f"{section_prefix}.path.{path_index}", path_item)
        for block_index, block in enumerate(section.blocks):
            block_prefix = f"{section_prefix}.b{block_index}"
            if isinstance(block, ParagraphBlock):
                add(f"{block_prefix}.paragraph", block.text)
                continue
            if isinstance(block, PrerequisiteBlock):
                for item_index, item in enumerate(block.items):
                    add(f"{block_prefix}.prerequisite.{item_index}", item)
                continue
            if isinstance(block, ProcedureBlock):
                for step_index, step in enumerate(block.steps):
                    add(f"{block_prefix}.procedure.{step_index}.text", step.text)
                    for substep_index, substep in enumerate(step.substeps):
                        add(f"{block_prefix}.procedure.{step_index}.substep.{substep_index}", substep)
                continue
            if isinstance(block, CodeBlock):
                add(f"{block_prefix}.code.caption", block.caption)
                continue
            if isinstance(block, NoteBlock):
                add(f"{block_prefix}.note.title", block.title)
                add(f"{block_prefix}.note.text", block.text)
                continue
            if isinstance(block, TableBlock):
                add(f"{block_prefix}.table.caption", block.caption)
                for header_index, header in enumerate(block.headers):
                    add(f"{block_prefix}.table.header.{header_index}", header)
                for row_index, row in enumerate(block.rows):
                    for cell_index, cell in enumerate(row):
                        add(f"{block_prefix}.table.cell.{row_index}.{cell_index}", cell)
                continue
            if isinstance(block, AnchorBlock):
                add(f"{block_prefix}.anchor.label", block.label)
    return units


def _chunk_units(units: list[_TextUnit]) -> list[list[_TextUnit]]:
    batches: list[list[_TextUnit]] = []
    current: list[_TextUnit] = []
    current_chars = 0
    for unit in units:
        unit_chars = min(len(unit.text), MAX_SINGLE_TEXT_CHARS)
        if current and (
            len(current) >= UNIT_BATCH_SIZE
            or current_chars + unit_chars > UNIT_BATCH_CHAR_LIMIT
        ):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(unit)
        current_chars += unit_chars
    if current:
        batches.append(current)
    return batches


def _parse_translated_items(payload: Any) -> dict[str, str]:
    if isinstance(payload, dict):
        items = payload.get("items")
        if items is None and "id" in payload and "text" in payload:
            items = [payload]
    elif isinstance(payload, list):
        items = payload
    else:
        raise ValueError("Unexpected translation payload shape")

    if not isinstance(items, list):
        raise ValueError("Translation payload must contain an item list")

    translated: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        unit_id = str(item.get("id") or "").strip()
        text = normalize_ocp_ko_terminology(str(item.get("text") or "").strip())
        if unit_id:
            translated[unit_id] = text
    return translated


def _translate_unit_batch(client: LLMClient, batch: list[_TextUnit]) -> dict[str, str]:
    payload = {
        "items": [
            {
                "id": unit.unit_id,
                "text": unit.text[:MAX_SINGLE_TEXT_CHARS],
            }
            for unit in batch
        ]
    }
    messages = [
        {
            "role": "system",
            "content": (
                "Translate OpenShift documentation leaf text from English to Korean.\n"
                "Return JSON only.\n"
                "Output schema: {\"items\":[{\"id\":\"...\",\"text\":\"...\"}]}\n"
                "Rules:\n"
                "- Preserve every id exactly.\n"
                "- Keep item count identical.\n"
                "- Translate only user-facing prose.\n"
                "- Keep product names, CLI commands, file paths, URLs, YAML/JSON keys, env vars, API names, and inline code literals unchanged when natural.\n"
                f"{OCP_KO_TERMINOLOGY_PROMPT}\n"
                "- Do not add explanations.\n"
                "- Do not wrap the answer in markdown fences."
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    response_text = client.generate(messages)
    try:
        return _parse_translated_items(_parse_json_payload(response_text))
    except (json.JSONDecodeError, ValueError):
        repair_messages = [
            {
                "role": "system",
                "content": (
                    "Repair the malformed translation JSON below.\n"
                    "Return valid JSON only with schema {\"items\":[{\"id\":\"...\",\"text\":\"...\"}]}\n"
                    "Keep ids and translated text unchanged.\n"
                    "Do not explain anything."
                ),
            },
            {"role": "user", "content": response_text},
        ]
        return _parse_translated_items(_parse_json_payload(client.generate(repair_messages)))


def _translate_single_unit(client: LLMClient, unit: _TextUnit) -> str:
    payload = {"id": unit.unit_id, "text": unit.text[:MAX_SINGLE_TEXT_CHARS]}
    messages = [
        {
            "role": "system",
            "content": (
                "Translate one OpenShift documentation text snippet from English to Korean.\n"
                "Return JSON only with the same keys: {\"id\":\"...\",\"text\":\"...\"}\n"
                "Keep commands, file paths, API names, env vars, URLs, and inline code literals unchanged when natural.\n"
                f"{OCP_KO_TERMINOLOGY_PROMPT}"
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    data = _parse_translated_items(_parse_json_payload(client.generate(messages)))
    return data.get(unit.unit_id, "").strip() or unit.text


def _translate_batch_with_fallback(
    settings: Settings,
    batch: list[_TextUnit],
) -> dict[str, str]:
    client = LLMClient(settings)
    try:
        batch_result = _translate_unit_batch(client, batch)
        expected_ids = {unit.unit_id for unit in batch}
        if set(batch_result) != expected_ids:
            raise ValueError("Translated unit ids do not match batch ids")
        return batch_result
    except Exception:  # noqa: BLE001
        return {
            unit.unit_id: _translate_single_unit(client, unit)
            for unit in batch
        }


def _translate_units(
    client: LLMClient,
    units: list[_TextUnit],
    *,
    existing: dict[str, str] | None = None,
    persist_callback=None,
    settings: Settings | None = None,
) -> dict[str, str]:
    translated: dict[str, str] = dict(existing or {})
    pending_units = [
        unit for unit in units if not translated.get(unit.unit_id, "").strip()
    ]
    batches = _chunk_units(pending_units)
    total_batches = len(batches)
    total_units = len(units)
    completed_units = len(translated)

    def persist(
        *,
        status: str,
        completed_batch_count: int,
        current_batch_index: int | None,
        batch_size: int,
    ) -> None:
        if persist_callback is None:
            return
        persist_callback(
            translated,
            {
                "status": status,
                "completed_unit_count": completed_units,
                "total_unit_count": total_units,
                "pending_unit_count": max(total_units - completed_units, 0),
                "completed_batch_count": completed_batch_count,
                "total_batch_count": total_batches,
                "current_batch_index": current_batch_index,
                "current_batch_size": batch_size,
            },
        )

    if batches:
        persist(
            status="running",
            completed_batch_count=0,
            current_batch_index=1,
            batch_size=len(batches[0]),
        )

    use_concurrency = (
        settings is not None
        and TRANSLATION_BATCH_CONCURRENCY > 1
        and total_batches > TRANSLATION_BATCH_CONCURRENCY
    )
    if not use_concurrency:
        for batch_index, batch in enumerate(batches):
            try:
                batch_result = _translate_unit_batch(client, batch)
                expected_ids = {unit.unit_id for unit in batch}
                if set(batch_result) != expected_ids:
                    raise ValueError("Translated unit ids do not match batch ids")
                translated.update(batch_result)
                completed_units = len(translated)
                persist(
                    status="complete" if batch_index == total_batches - 1 else "running",
                    completed_batch_count=batch_index + 1,
                    current_batch_index=batch_index + 1,
                    batch_size=len(batch),
                )
            except Exception:  # noqa: BLE001
                for unit in batch:
                    translated[unit.unit_id] = _translate_single_unit(client, unit)
                completed_units = len(translated)
                persist(
                    status="complete" if batch_index == total_batches - 1 else "running",
                    completed_batch_count=batch_index + 1,
                    current_batch_index=batch_index + 1,
                    batch_size=len(batch),
                )
        return translated

    max_workers = min(TRANSLATION_BATCH_CONCURRENCY, total_batches)
    completed_batch_count = 0
    next_batch_index = 0
    in_flight: dict[object, tuple[int, list[_TextUnit]]] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        while next_batch_index < total_batches and len(in_flight) < max_workers:
            batch = batches[next_batch_index]
            future = executor.submit(_translate_batch_with_fallback, settings, batch)
            in_flight[future] = (next_batch_index, batch)
            next_batch_index += 1

        while in_flight:
            done, _ = wait(tuple(in_flight), return_when=FIRST_COMPLETED)
            for future in done:
                batch_index, batch = in_flight.pop(future)
                batch_result = future.result()
                translated.update(batch_result)
                completed_units = len(translated)
                completed_batch_count += 1
                persist(
                    status="complete" if completed_batch_count == total_batches else "running",
                    completed_batch_count=completed_batch_count,
                    current_batch_index=batch_index + 1,
                    batch_size=len(batch),
                )
                if next_batch_index < total_batches:
                    next_batch = batches[next_batch_index]
                    next_future = executor.submit(
                        _translate_batch_with_fallback,
                        settings,
                        next_batch,
                    )
                    in_flight[next_future] = (next_batch_index, next_batch)
                    next_batch_index += 1
    return translated


def _translated_text(translations: dict[str, str], unit_id: str, default: str) -> str:
    translated = translations.get(unit_id, "").strip()
    return normalize_ocp_ko_terminology(translated or default)


def _apply_translations(
    document: CanonicalDocumentAst,
    translations: dict[str, str],
) -> CanonicalDocumentAst:
    translated_sections: list[CanonicalSectionAst] = []
    for section_index, section in enumerate(document.sections):
        section_prefix = f"s{section_index}"
        translated_blocks: list[AstBlock] = []
        for block_index, block in enumerate(section.blocks):
            block_prefix = f"{section_prefix}.b{block_index}"
            if isinstance(block, ParagraphBlock):
                translated_blocks.append(
                    ParagraphBlock(
                        text=_translated_text(
                            translations,
                            f"{block_prefix}.paragraph",
                            block.text,
                        )
                    )
                )
                continue
            if isinstance(block, PrerequisiteBlock):
                items = tuple(
                    _translated_text(
                        translations,
                        f"{block_prefix}.prerequisite.{item_index}",
                        item,
                    )
                    for item_index, item in enumerate(block.items)
                )
                translated_blocks.append(PrerequisiteBlock(items=items))
                continue
            if isinstance(block, ProcedureBlock):
                steps: list[ProcedureStep] = []
                for step_index, step in enumerate(block.steps):
                    substeps = tuple(
                        _translated_text(
                            translations,
                            f"{block_prefix}.procedure.{step_index}.substep.{substep_index}",
                            substep,
                        )
                        for substep_index, substep in enumerate(step.substeps)
                    )
                    steps.append(
                        ProcedureStep(
                            ordinal=step.ordinal,
                            text=_translated_text(
                                translations,
                                f"{block_prefix}.procedure.{step_index}.text",
                                step.text,
                            ),
                            substeps=substeps,
                        )
                    )
                translated_blocks.append(ProcedureBlock(steps=tuple(steps)))
                continue
            if isinstance(block, CodeBlock):
                translated_blocks.append(
                    CodeBlock(
                        code=block.code,
                        language=block.language,
                        copy_text=block.copy_text,
                        wrap_hint=block.wrap_hint,
                        overflow_hint=block.overflow_hint,
                        caption=_translated_text(
                            translations,
                            f"{block_prefix}.code.caption",
                            block.caption,
                        ),
                    )
                )
                continue
            if isinstance(block, NoteBlock):
                translated_blocks.append(
                    NoteBlock(
                        text=_translated_text(
                            translations,
                            f"{block_prefix}.note.text",
                            block.text,
                        ),
                        title=_translated_text(
                            translations,
                            f"{block_prefix}.note.title",
                            block.title,
                        ),
                        variant=block.variant,
                    )
                )
                continue
            if isinstance(block, TableBlock):
                headers = tuple(
                    _translated_text(
                        translations,
                        f"{block_prefix}.table.header.{header_index}",
                        header,
                    )
                    for header_index, header in enumerate(block.headers)
                )
                rows = tuple(
                    tuple(
                        _translated_text(
                            translations,
                            f"{block_prefix}.table.cell.{row_index}.{cell_index}",
                            cell,
                        )
                        for cell_index, cell in enumerate(row)
                    )
                    for row_index, row in enumerate(block.rows)
                )
                translated_blocks.append(
                    TableBlock(
                        headers=headers,
                        rows=rows,
                        caption=_translated_text(
                            translations,
                            f"{block_prefix}.table.caption",
                            block.caption,
                        ),
                    )
                )
                continue
            if isinstance(block, AnchorBlock):
                translated_blocks.append(
                    AnchorBlock(
                        anchor=block.anchor,
                        label=_translated_text(
                            translations,
                            f"{block_prefix}.anchor.label",
                            block.label,
                        ),
                    )
                )
                continue
            translated_blocks.append(block)

        translated_sections.append(
            CanonicalSectionAst(
                section_id=section.section_id,
                ordinal=section.ordinal,
                heading=_translated_text(
                    translations,
                    f"{section_prefix}.heading",
                    section.heading,
                ),
                level=section.level,
                path=tuple(
                    _translated_text(
                        translations,
                        f"{section_prefix}.path.{path_index}",
                        path_item,
                    )
                    for path_index, path_item in enumerate(section.path)
                ),
                anchor=section.anchor,
                source_url=section.source_url,
                viewer_path=section.viewer_path,
                semantic_role=section.semantic_role,
                blocks=tuple(translated_blocks),
            )
        )

    translated_title = _translated_text(translations, "doc.title", document.title)
    provenance = replace(
        document.provenance,
        translation_stage="translated_ko_draft",
        translation_source_language=(
            document.provenance.translation_source_language or document.source_language
        ),
        translation_target_language="ko",
        translation_source_url=document.provenance.translation_source_url or document.source_url,
        translation_source_fingerprint=(
            document.provenance.translation_source_fingerprint
            or document.provenance.source_fingerprint
        ),
        notes=tuple((*document.provenance.notes, "machine_translated_draft")),
    )
    notes = tuple((*document.notes, "machine_translated_draft"))
    return CanonicalDocumentAst(
        doc_id=document.doc_id,
        book_slug=document.book_slug,
        title=translated_title,
        source_type=document.source_type,
        source_url=document.source_url,
        viewer_base_path=document.viewer_base_path,
        source_language=document.source_language,
        display_language="ko",
        translation_status="translated_ko_draft",
        pack_id=document.pack_id,
        pack_label=document.pack_label,
        inferred_product=document.inferred_product,
        inferred_version=document.inferred_version,
        sections=tuple(translated_sections),
        notes=notes,
        provenance=provenance,
    )


def translate_document_ast(
    document: CanonicalDocumentAst,
    settings: Settings,
) -> CanonicalDocumentAst:
    if document.translation_status == "approved_ko":
        return document

    units = _iter_text_units(document)
    if not units:
        return document
    cached_translations = _load_translation_cache(document, settings)
    if all(cached_translations.get(unit.unit_id, "").strip() for unit in units):
        return _apply_translations(document, cached_translations)

    client = LLMClient(settings)
    translations = _translate_units(
        client,
        units,
        existing=cached_translations,
        persist_callback=lambda payload, progress: _write_translation_cache(
            document,
            settings,
            payload,
            progress=progress,
        ),
        settings=settings,
    )
    return _apply_translations(document, translations)
