from __future__ import annotations

import re
import uuid
from typing import Any

from play_book_studio.ingestion.chunk_question_candidates import build_chunk_question_candidates

NARRATIVE_VERSION = 1
OPS_LEARNING_DERIVE_VERSION = 1

STAGE_LABELS = {
    "architecture": "아키텍처와 운영 구성",
    "unit_test": "단위 검증",
    "integration_test": "통합 검증",
    "perf_test": "성능 검증",
    "completion": "완료 보고",
}

GENERIC_TITLE_FRAGMENTS = (
    "목차",
    "개정이력",
    "완료보고",
    "감사합니다",
    "contents",
    "index",
)

TOKEN_RE = re.compile(r"\b(?:OpenShift|OCP|Pod|PVC|PV|Route|Service|Deployment|ConfigMap|Secret|Ingress|HAProxy|HPA|JMeter|TPS|DB|SQL|CI/CD|ArgoCD|Tekton|Quay|GitOps)\b", re.I)


def build_beginner_narrative(chunk: dict[str, Any]) -> str:
    title = _clean(str(chunk.get("title") or chunk.get("heading_title") or "운영 자료"))
    stage_label = STAGE_LABELS.get(str(chunk.get("stage_id") or "").strip(), "운영 확인")
    summary = _summary_text(chunk)
    terms = _source_terms(chunk)
    term_text = ", ".join(terms[:4])
    first = f"이 청크는 {stage_label} 관점에서 {title}을 확인하는 자료입니다."
    second = (
        f"처음 보는 사용자는 먼저 {term_text} 같은 핵심 단어를 찾고, 화면이나 표가 어떤 상태를 증명하는지 보면 됩니다."
        if term_text
        else "처음 보는 사용자는 먼저 제목과 화면 설명을 연결해서 무엇을 검증하는 자료인지 확인하면 됩니다."
    )
    third = f"본문에서 중요한 단서는 {summary}입니다." if summary else "본문이 짧다면 이미지 설명, 캡션, OCR 텍스트를 함께 근거로 봅니다."
    fourth = "그 다음 정상 상태, 실패 징후, 확인 명령 또는 화면 경로를 분리해서 질문하면 더 정확한 답변을 받을 수 있습니다."
    return " ".join(part for part in (first, second, third, fourth) if part).strip()


def derive_ops_learning_chunks(
    course_chunks: list[dict[str, Any]],
    *,
    existing_learning_chunks: list[dict[str, Any]] | None = None,
    min_count: int = 100,
    max_count: int = 200,
) -> list[dict[str, Any]]:
    existing = list(existing_learning_chunks or [])
    derived: list[dict[str, Any]] = []
    seen_source_ids = {
        str(source_id)
        for chunk in existing
        for source_id in (chunk.get("source_chunk_ids") if isinstance(chunk.get("source_chunk_ids"), list) else [])
        if str(source_id).strip()
    }
    target_count = max(min_count, len(existing))
    target_count = min(max_count, target_count)
    for chunk in sorted(course_chunks, key=_chunk_rank):
        if len(existing) + len(derived) >= target_count:
            break
        chunk_id = str(chunk.get("chunk_id") or "").strip()
        if not chunk_id or chunk_id in seen_source_ids or _is_low_value_chunk(chunk):
            continue
        learning_chunk = derive_ops_learning_chunk(chunk, ordinal=len(existing) + len(derived) + 1)
        if learning_chunk:
            derived.append(learning_chunk)
            seen_source_ids.add(chunk_id)
    return existing + derived


def derive_ops_learning_chunk(chunk: dict[str, Any], *, ordinal: int = 1) -> dict[str, Any] | None:
    chunk_id = str(chunk.get("chunk_id") or "").strip()
    if not chunk_id:
        return None
    title = _clean(str(chunk.get("title") or "운영 확인"))
    stage_id = str(chunk.get("stage_id") or "operations").strip() or "operations"
    narrative = build_beginner_narrative(chunk)
    terms = _source_terms(chunk)
    candidates = build_chunk_question_candidates(
        {
            **chunk,
            "heading": title,
            "text": "\n".join(part for part in (narrative, _summary_text(chunk), _chunk_text(chunk)) if part),
        }
    )
    query_variants = candidates["starter_question_candidates"][:5]
    if not query_variants:
        query_variants = [f"{title}은 처음에 무엇부터 확인하면 돼?"]
    return {
        "schema": "ops_learning_chunk_v1",
        "chunk_type": "ops_learning_step",
        "learning_chunk_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"kmsc-auto-learning:{chunk_id}")),
        "guide_id": f"auto_{stage_id}",
        "step_id": f"auto_{ordinal:03d}_{_slug(title)[:48]}",
        "stage_id": stage_id,
        "title": title,
        "learning_goal": f"{title}에서 운영자가 먼저 확인할 상태와 근거를 이해한다.",
        "beginner_explanation": narrative,
        "source_summary": _summary_text(chunk),
        "source_terms": terms,
        "source_titles": [title],
        "source_chunk_ids": [chunk_id],
        "hidden_native_ids": [str(chunk.get("native_id") or "").strip()] if str(chunk.get("native_id") or "").strip() else [],
        "visual_evidence_roles": _image_roles(chunk),
        "image_evidence_texts": _image_evidence_texts(chunk)[:5],
        "query_variants": query_variants,
        "embedding_text": "\n".join(part for part in (title, narrative, _summary_text(chunk), " ".join(terms)) if part),
        "metadata": {
            "generated": True,
            "derive_version": OPS_LEARNING_DERIVE_VERSION,
            "source": "kmsc_course_chunks",
        },
    }


def _chunk_rank(chunk: dict[str, Any]) -> tuple[int, str]:
    attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
    evidence_score = sum(1 for item in attachments if isinstance(item, dict) and item.get("is_default_visible"))
    text_score = len(_chunk_text(chunk))
    return (-evidence_score, -text_score, str(chunk.get("chunk_id") or ""))


def _is_low_value_chunk(chunk: dict[str, Any]) -> bool:
    title = _clean(str(chunk.get("title") or ""))
    if not title:
        return True
    lowered = title.lower()
    if any(fragment.lower() in lowered for fragment in GENERIC_TITLE_FRAGMENTS):
        return True
    return len(_chunk_text(chunk)) < 80 and not _image_evidence_texts(chunk)


def _chunk_text(chunk: dict[str, Any]) -> str:
    index_texts = chunk.get("index_texts") if isinstance(chunk.get("index_texts"), dict) else {}
    values = [
        index_texts.get("dense_text"),
        index_texts.get("sparse_text"),
        chunk.get("search_text"),
        chunk.get("body_md"),
        chunk.get("visual_text"),
    ]
    return _clean(" ".join(str(value) for value in values if str(value or "").strip()))


def _summary_text(chunk: dict[str, Any], *, limit: int = 240) -> str:
    values: list[str] = []
    for key in ("source_summary", "summary", "visual_text", "search_text", "body_md"):
        value = str(chunk.get(key) or "").strip()
        if value:
            values.append(value)
    values.extend(_image_evidence_texts(chunk))
    text = _clean(" ".join(dict.fromkeys(values)))
    return text[:limit].strip()


def _image_evidence_texts(chunk: dict[str, Any]) -> list[str]:
    attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
    rows: list[str] = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        text = _clean(
            " ".join(
                str(attachment.get(key) or "")
                for key in ("visual_summary", "caption_text", "ocr_text", "state_signal")
                if str(attachment.get(key) or "").strip()
            )
        )
        if text and text not in rows:
            rows.append(text)
    return rows


def _image_roles(chunk: dict[str, Any]) -> list[str]:
    attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
    roles: list[str] = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        values = attachment.get("instructional_roles") if isinstance(attachment.get("instructional_roles"), list) else []
        values = [*values, attachment.get("instructional_role")]
        for value in values:
            role = str(value or "").strip()
            if role and role not in roles:
                roles.append(role)
    return roles


def _source_terms(chunk: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    for value in TOKEN_RE.findall(_chunk_text(chunk)):
        normalized = value.strip()
        if normalized and normalized not in terms:
            terms.append(normalized)
    for key in ("k8s_objects", "operator_names", "source_terms"):
        value = chunk.get(key)
        if isinstance(value, list):
            for item in value:
                term = str(item or "").strip()
                if term and term not in terms:
                    terms.append(term)
    return terms[:12]


def _slug(text: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z가-힣]+", "-", text).strip("-").lower()
    return slug or "step"


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


__all__ = [
    "NARRATIVE_VERSION",
    "OPS_LEARNING_DERIVE_VERSION",
    "build_beginner_narrative",
    "derive_ops_learning_chunk",
    "derive_ops_learning_chunks",
]
