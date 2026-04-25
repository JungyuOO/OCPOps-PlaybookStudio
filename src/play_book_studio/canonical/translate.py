"""영문 fallback 문서를 한국어 draft AST로 바꾼다."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from play_book_studio.answering.llm import LLMClient
from play_book_studio.config.settings import Settings
from play_book_studio.ingestion.localization_quality import english_prose_reason

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
    FigureBlock,
    NoteBlock,
    ParagraphBlock,
    PrerequisiteBlock,
    ProcedureBlock,
    ProcedureStep,
    TableBlock,
)


UNIT_BATCH_SIZE = 32
UNIT_BATCH_CHAR_LIMIT = 4800
MAX_SINGLE_TEXT_CHARS = 1200
TRANSLATION_BATCH_CONCURRENCY = 24
OCP_KO_TERMINOLOGY_PROMPT = ocp_ko_terminology_prompt()
STRICT_TRANSLATION_REPAIR_PASSES = 2

DETERMINISTIC_TRANSLATION_OVERRIDES = {
    "Abstract": "개요",
    "Additional resources": "추가 리소스",
    "A build fails with:": "빌드가 다음 메시지와 함께 실패합니다:",
    "Adding certificate authorities to the cluster": "클러스터에 인증 기관 추가",
    "Important": "중요",
    "Issue": "문제",
    "Legal Notice": "법적 고지",
    "Note": "참고",
    "Prerequisites": "사전 요구 사항",
    "Procedure": "절차",
    "Resolution": "해결",
    "Red Hat OpenShift Documentation Team Legal Notice Abstract": (
        "Red Hat OpenShift 문서 팀 법적 고지 및 개요"
    ),
    "Builds for OpenShift Container Platform": "OpenShift Container Platform 빌드",
    "Builds using BuildConfig": "BuildConfig 을 사용한 빌드",
    "Configuring build settings": "빌드 설정 구성",
    "Create a `ConfigMap`": "`ConfigMap` 생성",
    "Example output": "예제 출력",
    "Expand": "펼치기",
    "Resolving denial for access to resources": "리소스 액세스 거부 해결",
    "Service certificate generation failure": "서비스 인증서 생성 실패",
    "The `ConfigMap` must be created in the `openshift-config` namespace.": (
        "`ConfigMap`은 `openshift-config` 네임스페이스에 생성해야 합니다."
    ),
    "Tip": "팁",
    "Update the cluster image configuration:": "클러스터 이미지 구성을 업데이트합니다:",
    "NooBaa, unless installed using Multicloud Object Gateway (MCG)": (
        "Multicloud Object Gateway(MCG)를 사용하여 설치한 경우를 제외한 NooBaa"
    ),
    "IPL the bootstrap machine from the reader:": "리더에서 부트스트랩 머신을 IPL합니다:",
    "Core limit range object definition": "핵심 LimitRange 객체 정의",
    "An example network workflow showing an Ingress Controller running in an OpenShift Container Platform environment.": (
        "OpenShift Container Platform 환경에서 실행되는 Ingress Controller의 예제 네트워크 워크플로입니다."
    ),
    "Istio Control Plane Dashboard showing data for bookinfo sample project": (
        "bookinfo 샘플 프로젝트의 데이터를 보여주는 Istio Control Plane 대시보드"
    ),
    "Diagram showing four OpenShift workloads on top of OpenStack. Each workload is connected to an external data center via NIC using the provider network.": (
        "OpenStack 위에서 실행되는 네 개의 OpenShift 워크로드를 보여주는 다이어그램입니다. "
        "각 워크로드는 공급자 네트워크를 사용하는 NIC를 통해 외부 데이터 센터에 연결됩니다."
    ),
}


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
        str(unit_id).strip(): normalize_ocp_ko_terminology(str(text).strip())
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
            if isinstance(block, FigureBlock):
                add(f"{block_prefix}.figure.caption", block.caption)
                add(f"{block_prefix}.figure.alt", block.alt)
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


def _batch_max_tokens(client: LLMClient, batch: list[_TextUnit]) -> int:
    source_chars = sum(len(unit.text[:MAX_SINGLE_TEXT_CHARS]) for unit in batch)
    requested = 900 + int(source_chars * 0.8)
    return max(client.max_tokens, min(requested, 4096))


def _generate_with_retries(
    client: LLMClient,
    messages: list[dict[str, str]],
    *,
    max_tokens: int | None = None,
    attempts: int = 3,
) -> str:
    last_exc: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            return client.generate(messages, max_tokens=max_tokens)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < attempts - 1:
                time.sleep(min(2.0 * (attempt + 1), 5.0))
    if last_exc is not None:
        raise last_exc
    return ""


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
    response_text = _generate_with_retries(
        client,
        messages,
        max_tokens=_batch_max_tokens(client, batch),
    )
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
        return _parse_translated_items(
            _parse_json_payload(
                _generate_with_retries(
                    client,
                    repair_messages,
                    max_tokens=_batch_max_tokens(client, batch),
                )
            )
        )


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
    try:
        response_text = _generate_with_retries(messages=messages, client=client)
    except Exception:  # noqa: BLE001
        return unit.text
    for _attempt in range(2):
        try:
            data = _parse_translated_items(_parse_json_payload(response_text))
            return data.get(unit.unit_id, "").strip() or unit.text
        except (json.JSONDecodeError, ValueError):
            repair_messages = [
                {
                    "role": "system",
                    "content": (
                        "Repair the malformed single-item translation JSON below.\n"
                        "Return valid JSON only with schema {\"id\":\"...\",\"text\":\"...\"}.\n"
                        "Keep the id and translated text unchanged. Do not explain anything."
                    ),
                },
                {"role": "user", "content": response_text},
            ]
            try:
                response_text = _generate_with_retries(client, repair_messages)
            except Exception:  # noqa: BLE001
                return unit.text

    retry_messages = [
        {
            "role": "system",
            "content": (
                "Translate one OpenShift documentation text snippet from English to Korean.\n"
                "Return compact valid JSON only: {\"id\":\"...\",\"text\":\"...\"}.\n"
                "Escape quotes and newlines correctly. Do not add markdown or explanations.\n"
                "Keep commands, file paths, API names, env vars, URLs, and inline code literals unchanged when natural.\n"
                f"{OCP_KO_TERMINOLOGY_PROMPT}"
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    try:
        data = _parse_translated_items(
            _parse_json_payload(_generate_with_retries(client, retry_messages))
        )
        return data.get(unit.unit_id, "").strip() or unit.text
    except (json.JSONDecodeError, ValueError, Exception):
        return unit.text


def _translate_single_unit_strict(
    client: LLMClient,
    unit: _TextUnit,
    *,
    previous_text: str = "",
) -> str:
    payload = {
        "id": unit.unit_id,
        "source_text": unit.text[:MAX_SINGLE_TEXT_CHARS],
        "previous_output": previous_text[:MAX_SINGLE_TEXT_CHARS],
    }
    messages = [
        {
            "role": "system",
            "content": (
                "The previous Korean documentation translation still leaked English prose.\n"
                "Translate the source_text into Korean now.\n"
                "Return JSON only: {\"id\":\"...\",\"text\":\"...\"}.\n"
                "Preserve product names, CLI commands, API fields, file paths, URLs, YAML/JSON keys, "
                "and inline code literals when natural.\n"
                "Do not return the original English sentence unless the entire snippet is a command, "
                "API field path, URL, or code literal.\n"
                f"{OCP_KO_TERMINOLOGY_PROMPT}"
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    try:
        translated = _parse_translated_items(
            _parse_json_payload(
                _generate_with_retries(
                    client,
                    messages,
                    max_tokens=max(client.max_tokens, min(2200, 700 + len(unit.text))),
                )
            )
        )
    except Exception:  # noqa: BLE001
        return previous_text.strip() or unit.text
    return translated.get(unit.unit_id, "").strip() or previous_text.strip() or unit.text


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


def _deterministic_translation(text: str) -> str:
    normalized = " ".join(str(text or "").split())
    override = DETERMINISTIC_TRANSLATION_OVERRIDES.get(normalized, "")
    return normalize_ocp_ko_terminology(override) if override else ""


def _translation_still_needs_repair(unit: _TextUnit, text: str) -> bool:
    return bool(
        english_prose_reason(
            text,
            field=_unit_localization_field(unit.unit_id),
        )
    )


def _translate_strict_with_fresh_client(
    settings: Settings,
    unit: _TextUnit,
    previous_text: str,
) -> str:
    return _translate_single_unit_strict(
        LLMClient(settings),
        unit,
        previous_text=previous_text,
    )


def _repair_unusable_translations(
    client: LLMClient,
    units: list[_TextUnit],
    translations: dict[str, str],
    *,
    settings: Settings | None = None,
) -> dict[str, str]:
    repaired = dict(translations)

    for unit in units:
        deterministic = _deterministic_translation(unit.text)
        current = repaired.get(unit.unit_id, "").strip()
        if deterministic and (
            not current
            or current == unit.text
            or _translation_still_needs_repair(unit, current)
        ):
            repaired[unit.unit_id] = deterministic

    for _pass_index in range(STRICT_TRANSLATION_REPAIR_PASSES):
        bad_units = [
            unit
            for unit in units
            if _translation_still_needs_repair(
                unit,
                repaired.get(unit.unit_id, "").strip() or unit.text,
            )
        ]
        if not bad_units:
            break
        strict_units: list[_TextUnit] = []
        for unit in bad_units:
            deterministic = _deterministic_translation(unit.text)
            if deterministic:
                repaired[unit.unit_id] = deterministic
                continue
            strict_units.append(unit)
        if not strict_units:
            continue
        if settings is not None and len(strict_units) > 1:
            max_workers = min(TRANSLATION_BATCH_CONCURRENCY, len(strict_units))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_by_unit = {
                    executor.submit(
                        _translate_strict_with_fresh_client,
                        settings,
                        unit,
                        repaired.get(unit.unit_id, "").strip(),
                    ): unit
                    for unit in strict_units
                }
                for future, unit in future_by_unit.items():
                    repaired[unit.unit_id] = normalize_ocp_ko_terminology(future.result())
            continue
        for unit in strict_units:
            previous_text = repaired.get(unit.unit_id, "").strip()
            repaired[unit.unit_id] = normalize_ocp_ko_terminology(
                _translate_single_unit_strict(
                    client,
                    unit,
                    previous_text=previous_text,
                )
            )

    return repaired


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
    def completed_unit_count() -> int:
        return sum(1 for unit in units if translated.get(unit.unit_id, "").strip())

    completed_units = completed_unit_count()

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
        and total_batches > 1
    )
    if not use_concurrency:
        for batch_index, batch in enumerate(batches):
            try:
                batch_result = _translate_unit_batch(client, batch)
                expected_ids = {unit.unit_id for unit in batch}
                if set(batch_result) != expected_ids:
                    raise ValueError("Translated unit ids do not match batch ids")
                translated.update(batch_result)
                completed_units = completed_unit_count()
                persist(
                    status="complete" if batch_index == total_batches - 1 else "running",
                    completed_batch_count=batch_index + 1,
                    current_batch_index=batch_index + 1,
                    batch_size=len(batch),
                )
            except Exception:  # noqa: BLE001
                for unit in batch:
                    translated[unit.unit_id] = _translate_single_unit(client, unit)
                completed_units = completed_unit_count()
                persist(
                    status="complete" if batch_index == total_batches - 1 else "running",
                    completed_batch_count=batch_index + 1,
                    current_batch_index=batch_index + 1,
                    batch_size=len(batch),
                )
        translated = _repair_unusable_translations(
            client,
            units,
            translated,
            settings=settings,
        )
        completed_units = completed_unit_count()
        persist(
            status="complete",
            completed_batch_count=total_batches,
            current_batch_index=total_batches if total_batches else None,
            batch_size=0,
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
                completed_units = completed_unit_count()
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
    translated = _repair_unusable_translations(
        client,
        units,
        translated,
        settings=settings,
    )
    completed_units = completed_unit_count()
    persist(
        status="complete",
        completed_batch_count=total_batches,
        current_batch_index=total_batches if total_batches else None,
        batch_size=0,
    )
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
            if isinstance(block, FigureBlock):
                translated_blocks.append(
                    FigureBlock(
                        src=block.src,
                        caption=_translated_text(
                            translations,
                            f"{block_prefix}.figure.caption",
                            block.caption,
                        ),
                        alt=_translated_text(
                            translations,
                            f"{block_prefix}.figure.alt",
                            block.alt,
                        ),
                        asset_ref=block.asset_ref,
                        asset_url=block.asset_url,
                        viewer_path=block.viewer_path,
                        source_file=block.source_file,
                        source_anchor=block.source_anchor,
                        asset_kind=block.asset_kind,
                        diagram_type=block.diagram_type,
                        kind_label=block.kind_label,
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
    cached_translations = _filter_usable_cached_translations(
        units,
        _load_translation_cache(document, settings),
    )
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


def _unit_localization_field(unit_id: str) -> str:
    if unit_id == "doc.title":
        return "title"
    if unit_id.endswith(".heading") or ".path." in unit_id:
        return "heading"
    return "body"


def _usable_cached_translation(unit: _TextUnit, text: str) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return False
    field = _unit_localization_field(unit.unit_id)
    return not english_prose_reason(normalized, field=field)


def _filter_usable_cached_translations(
    units: list[_TextUnit],
    cached_translations: dict[str, str],
) -> dict[str, str]:
    unit_by_id = {unit.unit_id: unit for unit in units}
    usable: dict[str, str] = {}
    for unit_id, text in cached_translations.items():
        unit = unit_by_id.get(unit_id)
        if unit is None:
            usable[unit_id] = text
            continue
        deterministic = _deterministic_translation(unit.text)
        if deterministic and (
            text.strip() == unit.text.strip()
            or english_prose_reason(text, field=_unit_localization_field(unit.unit_id))
        ):
            usable[unit_id] = deterministic
            continue
        if _usable_cached_translation(unit, text):
            usable[unit_id] = text
    return usable


def repair_unlocalized_english_units(
    document: CanonicalDocumentAst,
    settings: Settings,
) -> CanonicalDocumentAst:
    units = [
        unit
        for unit in _iter_text_units(document)
        if english_prose_reason(unit.text, field=_unit_localization_field(unit.unit_id))
    ]
    if not units:
        return document

    cached_translations = _load_translation_cache(document, settings)
    usable_cached_translations = _filter_usable_cached_translations(
        units,
        cached_translations,
    )
    target_unit_ids = {unit.unit_id for unit in units}
    relevant_cached_translations = {
        unit_id: text
        for unit_id, text in usable_cached_translations.items()
        if unit_id in target_unit_ids and text.strip()
    }
    if all(relevant_cached_translations.get(unit.unit_id, "").strip() for unit in units):
        return _apply_translations(document, relevant_cached_translations)

    client = LLMClient(settings)
    translations = _translate_units(
        client,
        units,
        existing=relevant_cached_translations,
        persist_callback=lambda payload, progress: _write_translation_cache(
            document,
            settings,
            {**cached_translations, **payload},
            progress=progress,
        ),
        settings=settings,
    )
    return _apply_translations(document, translations)
