from __future__ import annotations

import json
import os
import re
import html
import threading
import time
import uuid
from datetime import datetime
from io import BytesIO
from http import HTTPStatus
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs

from play_book_studio.answering.llm import LLMClient
from play_book_studio.app.sessions import Turn
from play_book_studio.config.settings import load_settings
from play_book_studio.course.qdrant_course import search_course_and_official, search_ops_learning_chunks


COURSE_RUNTIME_LABEL = "실운영 가이드"


def _normalize_query(query: str) -> str:
    return " ".join(str(query or "").strip().lower().split())


def _tokenize(text: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9._/-]{1,}|[가-힣]{2,}", str(text or ""))]


def _query_identifiers(query: str) -> set[str]:
    normalized = str(query or "").upper()
    return {
        token
        for token in re.findall(r"\b[A-Z]{2,}(?:-[A-Z0-9]+)+\b", normalized)
        if len(token) >= 5
    }


def _is_route_intent(query: str) -> bool:
    normalized = _normalize_query(query)
    if any(
        term in normalized
        for term in [
            "learn",
            "flow",
            "학습",
            "순서",
            "처음",
            "다음",
            "단계",
            "카드",
            "흐름",
            "안내",
            "이어",
            "계속",
        ]
    ):
        return True
    route_terms = [
        "guided",
        "tour",
        "route",
        "step",
        "next",
        "sequence",
        "start",
        "학습",
        "순서",
        "처음",
        "다음",
        "단계",
        "카드",
        "어디부터",
        "무엇을",
        "뭘",
        "뭐",
        "흐름",
        "이어",
        "후속",
    ]
    return any(term in normalized for term in route_terms)


def _is_next_step_intent(query: str) -> bool:
    normalized = _normalize_query(query)
    if any(term in normalized for term in ["다음", "이후", "계속", "이어", "그 다음", "뭘 봐", "무엇을 봐", "무엇을 확인"]):
        return True
    return any(
        term in normalized
        for term in [
            "next",
            "then",
            "follow",
            "다음",
            "이후",
            "후속",
            "이어",
            "그 다음",
            "뭐 봐",
            "무엇을 봐",
            "무엇을 확인",
        ]
    )


def _is_official_doc_intent(query: str) -> bool:
    normalized = _normalize_query(query)
    return any(
        term in normalized
        for term in [
            "공식",
            "공식문서",
            "red hat",
            "redhat",
            "openshift docs",
            "documentation",
            "docs",
            "vendor",
            "벤더",
            "기준",
            "검증",
            "참조",
        ]
    )


def _stage_beginner_label(stage_id: str) -> str:
    labels = {
        "architecture": "아키텍처 설계",
        "unit_test": "단위 테스트",
        "integration_test": "통합 테스트",
        "perf_test": "성능 테스트",
        "completion": "완료보고",
    }
    return labels.get(stage_id, stage_id.replace("_", " ").strip() or "이 단계")


def _infer_stage_id_from_query(query: str) -> str:
    normalized = _normalize_query(query)
    if any(term in normalized for term in ["아키텍처", "설계", "architecture", "dmz", "내부망", "외부"]):
        return "architecture"
    if any(term in normalized for term in ["성능", "병목", "부하", "performance", "perf", "metric", "메트릭"]):
        return "perf_test"
    if any(term in normalized for term in ["통합", "연계", "integration"]):
        return "integration_test"
    if any(term in normalized for term in ["단위", "ci/cd", "cicd", "형상관리", "pipeline", "파이프라인"]):
        return "unit_test"
    if any(term in normalized for term in ["완료", "보고", "completion"]):
        return "completion"
    return ""


def _clean_beginner_title(value: Any) -> str:
    text = INTERNAL_DOC_ID_RE.sub("", str(value or ""))
    text = re.sub(r"\b[A-Z]{2,}(?:-[A-Z0-9]+)+\b", "", text)
    text = re.sub(r"\bCH-\d+\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bKMSC[-A-Z0-9]*\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:KMSC|COCP|RTER|PLAN|RESULT|FRONT)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*\d+(?:\.\d+)*\.?\s*", "", text)
    text = re.sub(r"\((?:상세|요약)\)", "", text)
    text = re.sub(r"\s+", " ", text).strip(" -:_")
    return text or "핵심 절차"

def _public_course_text(value: Any, *, limit: int = 220) -> str:
    text = INTERNAL_DOC_ID_RE.sub("", str(value or ""))
    text = re.sub(r"\b[A-Z]{2,}(?:-[A-Z0-9]+)+\b", "", text)
    text = re.sub(r"\b(?:architecture|unit_test|integration_test|perf_test|completion)\s+단계의\s+[A-Za-z_]+\s+청크\.?", "", text)
    text = re.sub(r"\b\d+(?:\.\d+)*\.\s*", "", text)
    text = re.sub(r"\b\d+장\.\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip(" -:_")
    return _short_text(text, limit=limit)


def _public_chunk_label(chunk: dict[str, Any]) -> str:
    return _clean_beginner_title(chunk.get("title") or chunk.get("chunk_id") or COURSE_RUNTIME_LABEL)


def _chunk_beginner_question(chunk: dict[str, Any], *, intent: str = "learn") -> str:
    stage_id = str(chunk.get("stage_id") or "")
    stage_label = _stage_beginner_label(stage_id)
    title = _clean_beginner_title(chunk.get("title"))
    facets = chunk.get("facets") if isinstance(chunk.get("facets"), dict) else {}
    technologies = [str(item) for item in facets.get("technologies", []) if str(item).strip()] if isinstance(facets.get("technologies"), list) else []
    tech_hint = technologies[0] if technologies else ""

    if intent == "next":
        if tech_hint:
            return f"{title}에서 {tech_hint} 다음에는 무엇을 확인하면 돼?"
        return f"{title} 다음에는 무엇을 확인하면 돼?"
    if intent == "verify":
        return f"{title}이 정상인지 화면에서 무엇을 보면 돼?"
    if intent == "troubleshooting":
        return f"{title}에서 실패하면 어떤 로그와 상태부터 확인해야 해?"
    if intent == "performance":
        return f"{title} 결과에서 병목은 어디를 보면 돼?"
    if intent == "official":
        return f"{title}를 공식문서 기준과 실운영 기준으로 같이 설명해줘"
    if tech_hint:
        return f"{stage_label}에서 {title}와 {tech_hint} 흐름을 어떤 순서로 이해하면 돼?"
    return f"{stage_label}에서 {title} 흐름을 어떤 순서로 이해하면 돼?"


def _tokenize(text: str) -> list[str]:
    return [
        token.lower()
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9._/-]{1,}|[가-힣]{2,}", str(text or ""))
    ]


def _is_route_intent(query: str) -> bool:
    normalized = _normalize_query(query)
    route_terms = [
        "learn",
        "flow",
        "guided",
        "tour",
        "route",
        "step",
        "next",
        "sequence",
        "start",
        "학습",
        "순서",
        "처음",
        "다음",
        "단계",
        "카드",
        "어디부터",
        "무엇",
        "뭐",
        "흐름",
        "이어",
        "계속",
        "안내",
    ]
    return any(term in normalized for term in route_terms)


def _is_next_step_intent(query: str) -> bool:
    normalized = _normalize_query(query)
    next_terms = [
        "next",
        "then",
        "follow",
        "다음",
        "이후",
        "계속",
        "이어",
        "그 다음",
        "뭐 봐",
        "무엇을 봐",
        "무엇을 확인",
    ]
    return any(term in normalized for term in next_terms)


def _is_official_doc_intent(query: str) -> bool:
    normalized = _normalize_query(query)
    official_terms = [
        "공식",
        "공식문서",
        "red hat",
        "redhat",
        "openshift docs",
        "documentation",
        "docs",
        "vendor",
        "벤더",
        "기준",
        "검증",
        "참조",
    ]
    return any(term in normalized for term in official_terms)


def _stage_beginner_label(stage_id: str) -> str:
    labels = {
        "architecture": "아키텍처 설계",
        "unit_test": "단위 테스트",
        "integration_test": "통합 테스트",
        "perf_test": "성능 테스트",
        "completion": "완료보고",
    }
    return labels.get(stage_id, stage_id.replace("_", " ").strip() or "이 단계")


def _infer_stage_id_from_query(query: str) -> str:
    normalized = _normalize_query(query)
    if any(term in normalized for term in ["아키텍처", "설계", "architecture", "dmz", "외부망", "내부망"]):
        return "architecture"
    if any(term in normalized for term in ["성능", "병목", "부하", "performance", "perf", "metric", "메트릭"]):
        return "perf_test"
    if any(term in normalized for term in ["통합", "연계", "integration"]):
        return "integration_test"
    if any(term in normalized for term in ["단위", "ci/cd", "cicd", "형상관리", "pipeline", "파이프라인"]):
        return "unit_test"
    if any(term in normalized for term in ["완료", "보고", "completion"]):
        return "completion"
    return ""


def _clean_beginner_title(value: Any) -> str:
    text = INTERNAL_DOC_ID_RE.sub("", str(value or ""))
    text = re.sub(r"\b[A-Z]{2,}(?:-[A-Z0-9]+)+\b", "", text)
    text = re.sub(r"\bCH-\d+\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bKMSC[-A-Z0-9]*\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:KMSC|COCP|RTER|PLAN|RESULT|FRONT)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*\d+(?:\.\d+)*\.?\s*", "", text)
    text = re.sub(r"\((?:상세|요약)\)", "", text)
    text = re.sub(r"\s+", " ", text).strip(" -:_")
    return text or "운영 학습 절차"


def _public_course_text(value: Any, *, limit: int = 220) -> str:
    text = INTERNAL_DOC_ID_RE.sub("", str(value or ""))
    text = re.sub(r"\b[A-Z]{2,}(?:-[A-Z0-9]+)+\b", "", text)
    text = re.sub(r"\b(?:architecture|unit_test|integration_test|perf_test|completion)\s+단계\s+[A-Za-z_]+\s+청크\.?", "", text)
    text = re.sub(r"\b\d+(?:\.\d+)*\.\s*", "", text)
    text = re.sub(r"\b\d+쪽\.\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip(" -:_")
    return _short_text(text, limit=limit)


def _chunk_beginner_question(chunk: dict[str, Any], *, intent: str = "learn") -> str:
    stage_id = str(chunk.get("stage_id") or "")
    stage_label = _stage_beginner_label(stage_id)
    title = _clean_beginner_title(chunk.get("title"))
    facets = chunk.get("facets") if isinstance(chunk.get("facets"), dict) else {}
    technologies = [str(item) for item in facets.get("technologies", []) if str(item).strip()] if isinstance(facets.get("technologies"), list) else []
    tech_hint = technologies[0] if technologies else ""

    if intent == "next":
        if tech_hint:
            return f"{title}에서 {tech_hint} 다음에는 무엇을 확인하면 돼?"
        return f"{title} 다음에는 무엇을 확인하면 돼?"
    if intent == "verify":
        return f"{title}이 정상인지 화면에서 무엇을 보면 돼?"
    if intent == "troubleshooting":
        return f"{title}에서 실패하면 어떤 로그와 상태부터 확인해야 해?"
    if intent == "performance":
        return f"{title} 결과에서 병목은 어디를 보면 돼?"
    if intent == "official":
        return f"{title} 기준을 공식문서와 실운영 자료로 같이 설명해줘"
    if tech_hint:
        return f"{stage_label}에서 {title}와 {tech_hint} 흐름을 어떤 순서로 이해하면 돼?"
    return f"{stage_label}에서 {title} 흐름을 어떤 순서로 이해하면 돼?"


def _course_root(root_dir: Path) -> Path:
    return root_dir / "data" / "course_pbs"


def _course_manifest_path(root_dir: Path) -> Path:
    return _course_root(root_dir) / "manifests" / "course_v1.json"


def _ops_learning_guides_path(root_dir: Path) -> Path:
    return _course_root(root_dir) / "manifests" / "ops_learning_guides_v1.json"


def _ops_learning_chunks_path(root_dir: Path) -> Path:
    return _course_root(root_dir) / "manifests" / "ops_learning_chunks_v1.jsonl"


def _course_chunks_dir(root_dir: Path) -> Path:
    return _course_root(root_dir) / "chunks"


def _course_chunks_jsonl_path(root_dir: Path) -> Path:
    return _course_root(root_dir) / "chunks.jsonl"


CHUNK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
INTERNAL_DOC_ID_RE = re.compile(r"\b(?:DSGN|TEST|CH|KMSC|COCP|RTER|PLAN|RESULT|FRONT)[-A-Z0-9]*\b", re.IGNORECASE)
OFFICIAL_DOC_MIN_SCORE = 0.65
COURSE_CHUNK_CACHE_TTL_SECONDS = 300.0
_COURSE_CHUNK_CACHE_LOCK = threading.Lock()
_COURSE_CHUNK_CACHE: dict[str, tuple[float, list[dict[str, Any]], dict[str, dict[str, Any]]]] = {}
_COURSE_SINGLE_CHUNK_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _validate_chunk_id(chunk_id: str) -> str:
    normalized = str(chunk_id or "").strip()
    if not normalized or not CHUNK_ID_RE.fullmatch(normalized):
        raise ValueError("Invalid course chunk id")
    return normalized


def _resolve_course_path(root_dir: Path, path_like: str) -> Path:
    raw = str(path_like or "").strip()
    if not raw:
        return Path()
    candidate = Path(raw)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (root_dir / candidate).resolve()
    if not _is_relative_to(resolved, root_dir):
        raise ValueError("Course asset path is outside the workspace")
    return resolved


def _course_asset_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".jpg" or suffix == ".jpeg":
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gif":
        return "image/gif"
    return "image/png"


def _course_asset_payload(path: Path) -> tuple[bytes, str]:
    expected_content_type = _course_asset_content_type(path)
    try:
        from PIL import Image

        image = Image.open(path)
        image.load()
        source_format = str(image.format or "").upper()
        if source_format in {"PNG", "JPEG", "GIF", "WEBP"}:
            image.close()
            return path.read_bytes(), expected_content_type
        output = BytesIO()
        converted = image.convert("RGBA") if image.mode not in {"RGB", "RGBA"} else image
        converted.save(output, format="PNG")
        converted.close()
        return output.getvalue(), "image/png"
    except Exception:
        return path.read_bytes(), expected_content_type


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[Any]:
    rows: list[Any] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _load_manifest(root_dir: Path) -> dict[str, Any]:
    path = _course_manifest_path(root_dir)
    if not path.exists():
        raise FileNotFoundError("Course manifest not found")
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise ValueError("Course manifest is invalid")
    return payload


def _load_ops_learning_guides(root_dir: Path) -> dict[str, Any]:
    path = _ops_learning_guides_path(root_dir)
    if not path.exists():
        return {"canonical_model": "ops_learning_guide_v1", "guides": []}
    try:
        payload = _read_json(path)
    except Exception:  # noqa: BLE001
        return {"canonical_model": "ops_learning_guide_v1", "guides": []}
    return payload if isinstance(payload, dict) else {"canonical_model": "ops_learning_guide_v1", "guides": []}


def _load_ops_learning_chunks(root_dir: Path) -> list[dict[str, Any]]:
    path = _ops_learning_chunks_path(root_dir)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:  # noqa: BLE001
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(payload, dict) and str(payload.get("learning_chunk_id") or "").strip():
            rows.append(payload)
    return rows


def _index_texts_for_chunk(chunk: dict[str, Any]) -> dict[str, str]:
    index_texts = chunk.get("index_texts") if isinstance(chunk.get("index_texts"), dict) else {}
    title = str(chunk.get("title") or "").strip()
    native_id = str(chunk.get("native_id") or "").strip()
    body = str(chunk.get("body_md") or "").strip()
    visual = str(chunk.get("visual_text") or "").strip()
    facets = chunk.get("facets") if isinstance(chunk.get("facets"), dict) else {}
    facet_terms: list[str] = []
    for value in facets.values():
        if isinstance(value, list):
            facet_terms.extend(str(item).strip() for item in value if str(item).strip())
        elif str(value or "").strip():
            facet_terms.append(str(value).strip())
    dense_default = "\n".join(part for part in [title, body, visual] if part)
    sparse_default = "\n".join(dict.fromkeys(part for part in [native_id, *facet_terms, title] if part))
    return {
        "dense_text": str(index_texts.get("dense_text") or dense_default).strip(),
        "sparse_text": str(index_texts.get("sparse_text") or sparse_default).strip(),
        "title_text": str(index_texts.get("title_text") or title).strip(),
        "visual_text": str(index_texts.get("visual_text") or visual).strip(),
    }


def _annotate_official_docs(docs: Any) -> list[dict[str, Any]]:
    rows = docs if isinstance(docs, list) else []
    annotated: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        score = float(row.get("score") or 0.0)
        annotated.append({**row, "trusted": score >= OFFICIAL_DOC_MIN_SCORE})
    return annotated


def _trusted_official_docs(docs: Any) -> list[dict[str, Any]]:
    return [row for row in _annotate_official_docs(docs) if row.get("trusted")]


def _short_text(value: Any, *, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _contains_any_term(text: str, terms: list[str]) -> bool:
    normalized = _normalize_query(text)
    return any(term in normalized for term in terms)


def _is_image_evidence_intent(query: str) -> bool:
    return _contains_any_term(
        query,
        [
            "image",
            "screen",
            "screenshot",
            "status",
            "state",
            "log",
            "metric",
            "dashboard",
            "evidence",
            "이미지",
            "화면",
            "캡처",
            "상태",
            "로그",
            "메트릭",
            "대시보드",
            "증적",
            "구성도",
            "아키텍처",
            "다이어그램",
            "어떻게 보여",
            "무엇으로 확인",
        ],
    )


def _is_performance_bottleneck_intent(query: str) -> bool:
    return _contains_any_term(
        query,
        [
            "performance",
            "bottleneck",
            "improve",
            "improvement",
            "성능",
            "병목",
            "개선",
            "응답시간",
            "처리량",
            "부하",
            "connection pool",
            "worker-thread",
        ],
    )


def _body_contains(body: str, needle: str) -> bool:
    return needle.lower() in body.lower()


def _performance_learning_summary(chunk: dict[str, Any]) -> str:
    body = re.sub(r"\s+", " ", str(chunk.get("body_md") or "")).strip()
    points: list[str] = []
    if _body_contains(body, "DB SQL 응답시간") and _body_contains(body, "병목"):
        points.append("병목은 DB SQL 응답 지연으로 전체 응답시간이 늦어진 부분부터 확인합니다")
    if _body_contains(body, "DB Connection Pool"):
        points.append("DB Connection Pool 대기와 max 도달 여부를 함께 봅니다")
    if _body_contains(body, "worker-thread"):
        points.append("worker-thread 수가 DB Connection Pool보다 과도하지 않은지 조정 포인트로 봅니다")
    if _body_contains(body, "HPA"):
        points.append("HPA scale-out 반응과 Pod min/max 설정이 부하를 분산하는지 확인합니다")
    if _body_contains(body, "HAProxy") or _body_contains(body, "Router"):
        points.append("HAProxy와 Router 자원 사용량 및 소켓 현황을 보조 지표로 확인합니다")
    if _body_contains(body, "200 user"):
        points.append("현재 자료에서는 동시 사용자 200 user까지 안정적으로 본 근거가 있습니다")
    if not points:
        return ""
    return ". ".join(points[:5]) + "."


def _official_doc_viewer_path(root_dir: Path, doc: dict[str, Any]) -> str:
    raw_book_slug = str(doc.get("book_slug") or doc.get("title") or "").strip()
    section_id = str(doc.get("section_id") or "").strip()
    if ":" in raw_book_slug and not section_id:
        raw_book_slug, section_id = raw_book_slug.split(":", 1)
    book_slug = raw_book_slug.split(":", 1)[0].strip()
    if not book_slug:
        return ""
    settings = load_settings(root_dir)
    viewer_path = f"/docs/ocp/{settings.ocp_version}/{settings.docs_language}/{book_slug}/index.html"
    if section_id:
        viewer_path = f"{viewer_path}#{section_id}"
    return viewer_path


def _course_source_to_citation(root_dir: Path, source: dict[str, Any]) -> dict[str, Any]:
    index = int(source.get("index") or 0)
    source_kind = str(source.get("source_kind") or "")
    if source_kind == "official_doc":
        viewer_path = str(source.get("viewer_path") or "").strip()
        if not viewer_path:
            viewer_path = _official_doc_viewer_path(
                root_dir,
                {
                    "book_slug": source.get("source_path") or source.get("title"),
                    "section_id": source.get("chunk_id"),
                    "title": source.get("title"),
                },
            )
        return {
            "index": index,
            "book_slug": str(source.get("source_path") or source.get("title") or "official-doc"),
            "book_title": str(source.get("title") or "Official doc"),
            "section": str(source.get("section_title") or source.get("title") or ""),
            "section_path": str(source.get("section_title") or ""),
            "viewer_path": viewer_path,
            "source_label": str(source.get("title") or "Official doc"),
            "source_collection": "official_docs",
            "source_lane": "official_validated_runtime",
            "approval_state": "approved",
            "publication_state": "active",
            "boundary_truth": "official_validated_runtime",
            "runtime_truth_label": "Official Docs",
            "boundary_badge": "Official",
        }
    return {
        "index": index,
        "book_slug": str(source.get("stage_id") or "course"),
            "book_title": COURSE_RUNTIME_LABEL,
        "section": str(source.get("section_title") or source.get("title") or ""),
        "section_path": str(source.get("section_title") or ""),
        "viewer_path": str(source.get("viewer_path") or ""),
        "source_label": str(source.get("title") or source.get("chunk_id") or COURSE_RUNTIME_LABEL),
        "source_collection": "study_docs",
        "source_lane": "study_docs_course_runtime",
        "approval_state": "course_reviewed",
        "publication_state": "internal",
        "boundary_truth": "internal_course_runtime",
            "runtime_truth_label": COURSE_RUNTIME_LABEL,
        "boundary_badge": "Internal Course",
    }


def _course_related_links_from_artifacts(artifacts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    related_links: list[dict[str, Any]] = []
    related_sections: list[dict[str, Any]] = []
    suggested_queries: list[str] = []
    seen: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict) or artifact.get("kind") != "course_guided_tour":
            continue
        for item in artifact.get("items", []) if isinstance(artifact.get("items"), list) else []:
            if not isinstance(item, dict):
                continue
            href = str(item.get("viewer_path") or "")
            label = str(item.get("label") or item.get("title") or item.get("native_id") or item.get("chunk_id") or "").strip()
            question = str(item.get("question") or "").strip()
            if not href or href in seen:
                continue
            seen.add(href)
            row = {
                "label": label or href,
                "href": href,
                "kind": "course_stop",
                "summary": str(item.get("reason") or question or ""),
                "source_lane": "study_docs_course_runtime",
                "boundary_truth": "internal_course_runtime",
                "runtime_truth_label": COURSE_RUNTIME_LABEL,
                "boundary_badge": "Internal Course",
            }
            if str(item.get("role") or "") == "next":
                related_sections.append(row)
                suggested_queries.append(question or f"{label} 다음에는 무엇을 확인하면 돼?")
            else:
                related_links.append(row)
    return related_links[:6], related_sections[:6], suggested_queries[:4]


def _attach_chat_response_fields(root_dir: Path, response: dict[str, Any]) -> dict[str, Any]:
    citations = [_course_source_to_citation(root_dir, source) for source in response.get("sources", []) if isinstance(source, dict)]
    related_links, related_sections, suggested_queries = _course_related_links_from_artifacts(
        [artifact for artifact in response.get("artifacts", []) if isinstance(artifact, dict)]
    )
    response["citations"] = citations
    response["warnings"] = list(response.get("warnings") or [])
    response["session_id"] = str(response.get("session_id") or "course")
    response["response_kind"] = "rag" if citations else "no_answer"
    response["suggested_queries"] = suggested_queries
    response["related_links"] = related_links
    response["related_sections"] = related_sections
    response["citation_map"] = {str(item["index"]): item for item in citations}
    return response


def _first_course_truth(response: dict[str, Any]) -> dict[str, str]:
    citations = response.get("citations") if isinstance(response.get("citations"), list) else []
    primary = next((item for item in citations if isinstance(item, dict)), None)
    if primary is None:
        return {}
    return {
        "primary_source_lane": str(primary.get("source_lane") or ""),
        "primary_boundary_truth": str(primary.get("boundary_truth") or ""),
        "primary_runtime_truth_label": str(primary.get("runtime_truth_label") or ""),
        "primary_boundary_badge": str(primary.get("boundary_badge") or ""),
        "primary_publication_state": str(primary.get("publication_state") or ""),
        "primary_approval_state": str(primary.get("approval_state") or ""),
    }


def _course_session_id(payload: dict[str, Any], response: dict[str, Any]) -> str:
    requested = str(payload.get("session_id") or "").strip()
    if requested:
        return requested
    response_id = str(response.get("session_id") or "").strip()
    if response_id and response_id != "course":
        return response_id
    return uuid.uuid4().hex


def _persist_course_session_turn(store: Any | None, payload: dict[str, Any], response: dict[str, Any]) -> None:
    if store is None:
        return
    query = str(payload.get("message") or "").strip()
    if not query:
        return

    session_id = _course_session_id(payload, response)
    response["session_id"] = session_id
    session = store.get(session_id)
    session.mode = "course"
    session.context.mode = "course"
    requested_user_id = str(payload.get("user_id") or "").strip()
    if requested_user_id:
        session.context.user_id = requested_user_id

    now = datetime.now().isoformat(timespec="seconds")
    truth = _first_course_truth(response)
    turn = Turn(
        turn_id=uuid.uuid4().hex,
        parent_turn_id=session.history[-1].turn_id if session.history else "",
        created_at=now,
        query=query,
        mode="course",
        answer=str(response.get("answer") or ""),
        response_kind=str(response.get("response_kind") or "rag"),
        citations=[dict(item) for item in response.get("citations") or [] if isinstance(item, dict)],
        related_links=[dict(item) for item in response.get("related_links") or [] if isinstance(item, dict)],
        related_sections=[dict(item) for item in response.get("related_sections") or [] if isinstance(item, dict)],
        warnings=[str(item) for item in response.get("warnings") or [] if str(item).strip()],
        primary_source_lane=truth.get("primary_source_lane", ""),
        primary_boundary_truth=truth.get("primary_boundary_truth", ""),
        primary_runtime_truth_label=truth.get("primary_runtime_truth_label", ""),
        primary_boundary_badge=truth.get("primary_boundary_badge", ""),
        primary_publication_state=truth.get("primary_publication_state", ""),
        primary_approval_state=truth.get("primary_approval_state", ""),
    )
    session.history.append(turn)
    session.history = session.history[-20:]
    session.revision += 1
    session.updated_at = now
    store.update(session)


def _course_answer_llm_rewrite_enabled(settings: Any) -> bool:
    flag = os.environ.get("COURSE_CHAT_LLM_REWRITE", "").strip().lower()
    if flag not in {"1", "true", "yes", "on"}:
        return False
    return bool(str(getattr(settings, "llm_endpoint", "") or "").strip() and str(getattr(settings, "llm_model", "") or "").strip())


def _compact_ops_learning_evidence(learning_chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for chunk in learning_chunks[:2]:
        if not isinstance(chunk, dict):
            continue
        sequence = chunk.get("operational_sequence") if isinstance(chunk.get("operational_sequence"), list) else []
        look_for = chunk.get("what_to_look_for") if isinstance(chunk.get("what_to_look_for"), list) else []
        rows.append(
            {
                "title": _public_course_text(chunk.get("title") or "", limit=120),
                "learning_goal": _public_course_text(chunk.get("learning_goal") or "", limit=260),
                "beginner_explanation": _public_course_text(chunk.get("beginner_explanation") or "", limit=360),
                "operational_sequence": [_public_course_text(item, limit=560) for item in sequence[:4] if _public_course_text(item, limit=560)],
                "what_to_look_for": [_public_course_text(item, limit=140) for item in look_for[:8] if _public_course_text(item, limit=140)],
            }
        )
    return rows


def _ops_learning_chunk_id(chunk: dict[str, Any]) -> str:
    return str(chunk.get("learning_chunk_id") or "").strip()


def _parse_llm_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE).strip()
    raw = re.sub(r"\s*```$", "", raw).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("LLM JSON response is not an object")
    return payload


def _build_ops_learning_selector_messages(*, query: str, candidates: list[dict[str, Any]]) -> list[dict[str, str]]:
    compact_candidates: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates[:4], start=1):
        sequence = candidate.get("operational_sequence") if isinstance(candidate.get("operational_sequence"), list) else []
        look_for = candidate.get("what_to_look_for") if isinstance(candidate.get("what_to_look_for"), list) else []
        compact_candidates.append(
            {
                "rank": index,
                "learning_chunk_id": _ops_learning_chunk_id(candidate),
                "guide_id": str(candidate.get("guide_id") or ""),
                "step_id": str(candidate.get("step_id") or ""),
                "stage_id": str(candidate.get("stage_id") or ""),
                "title": _public_course_text(candidate.get("title") or "", limit=120),
                "learning_goal": _public_course_text(candidate.get("learning_goal") or "", limit=260),
                "operational_sequence": [_public_course_text(item, limit=360) for item in sequence[:3] if _public_course_text(item, limit=360)],
                "what_to_look_for": [_public_course_text(item, limit=120) for item in look_for[:6] if _public_course_text(item, limit=120)],
                "source_chunk_ids": _learning_source_chunk_ids(candidate)[:4],
                "next_step_ids": [str(item) for item in candidate.get("next_step_ids", [])[:4]]
                if isinstance(candidate.get("next_step_ids"), list)
                else [],
            }
        )
    system = (
        "당신은 실운영 가이드 RAG의 후보 선택 agent다. "
        "사용자 질문에 직접 답하는 ops_learning 후보만 고른다. "
        "다음 단계 안내용 후보, 변형 후보, 질문과 느슨하게만 관련된 후보는 rejected로 둔다. "
        "답변을 작성하지 말고 JSON object만 반환한다."
    )
    user = (
        f"사용자 질문:\n{query}\n\n"
        f"후보(JSON):\n{json.dumps(compact_candidates, ensure_ascii=False, indent=2)}\n\n"
        "출력 JSON schema:\n"
        "{\n"
        "  \"selected_learning_chunk_ids\": [\"...\"],\n"
        "  \"rejected_learning_chunk_ids\": [\"...\"],\n"
        "  \"reason\": \"짧은 한국어 이유\"\n"
        "}\n\n"
        "규칙:\n"
        "- selected는 후보 learning_chunk_id 중에서만 고른다.\n"
        "- selected는 최대 2개다.\n"
        "- 현재 질문에 직접 답하는 후보를 우선한다.\n"
        "- 다음에 볼 단계나 개선 권고 후보는 사용자가 직접 묻지 않았다면 rejected로 둔다.\n"
        "- 판단이 애매하면 rank 1 후보만 selected로 둔다.\n"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _fallback_selected_learning_chunks(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return candidates[:1]


def _select_ops_learning_chunks_with_llm(
    *,
    settings: Any,
    query: str,
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    if not candidates:
        return [], {"mode": "none", "selected_learning_chunk_ids": []}, ""
    candidate_by_id = {_ops_learning_chunk_id(candidate): candidate for candidate in candidates if _ops_learning_chunk_id(candidate)}
    fallback = _fallback_selected_learning_chunks(candidates)
    fallback_ids = [_ops_learning_chunk_id(candidate) for candidate in fallback if _ops_learning_chunk_id(candidate)]
    if not _course_answer_llm_rewrite_enabled(settings) or len(candidates) == 1:
        return fallback, {"mode": "fallback", "reason": "selector disabled or single candidate", "selected_learning_chunk_ids": fallback_ids}, ""
    try:
        messages = _build_ops_learning_selector_messages(query=query, candidates=candidates)
        raw = LLMClient(settings).generate(messages, max_tokens=500)
        payload = _parse_llm_json_object(raw)
        selected_ids = [
            str(item).strip()
            for item in payload.get("selected_learning_chunk_ids", [])
            if str(item).strip()
        ][:2]
        if not selected_ids:
            raise ValueError("selector returned no selected ids")
        unknown_ids = [item for item in selected_ids if item not in candidate_by_id]
        if unknown_ids:
            raise ValueError(f"selector returned unknown ids: {', '.join(unknown_ids)}")
        selected = [candidate_by_id[item] for item in selected_ids]
        rejected_ids = [
            str(item).strip()
            for item in payload.get("rejected_learning_chunk_ids", [])
            if str(item).strip() and str(item).strip() in candidate_by_id
        ]
        return selected, {
            "mode": "llm",
            "selected_learning_chunk_ids": selected_ids,
            "rejected_learning_chunk_ids": rejected_ids,
            "reason": _public_course_text(payload.get("reason") or "", limit=240),
        }, ""
    except Exception as exc:  # noqa: BLE001
        return fallback, {
            "mode": "fallback",
            "reason": "selector fallback to top1",
            "selected_learning_chunk_ids": fallback_ids,
        }, f"course learning selector skipped: {exc}"


def _build_course_answer_rewrite_messages(
    *,
    query: str,
    draft_answer: str,
    sources: list[dict[str, Any]],
    learning_chunks: list[dict[str, Any]],
    guide_step: dict[str, Any] | None,
) -> list[dict[str, str]]:
    source_rows = [
        {
            "index": int(source.get("index") or 0),
            "title": _public_course_text(source.get("title") or "", limit=120),
            "stage_id": str(source.get("stage_id") or ""),
            "source_kind": str(source.get("source_kind") or ""),
        }
        for source in sources[:4]
        if isinstance(source, dict)
    ]
    guide_payload: dict[str, Any] = {}
    if isinstance(guide_step, dict):
        outline = guide_step.get("answer_outline") if isinstance(guide_step.get("answer_outline"), list) else []
        guide_payload = {
            "title": _public_course_text(guide_step.get("card_text") or "", limit=120),
            "learning_objective": _public_course_text(guide_step.get("learning_objective") or "", limit=260),
            "answer_outline": [_public_course_text(item, limit=260) for item in outline[:5] if _public_course_text(item, limit=260)],
        }
    evidence = {
        "sources": source_rows,
        "ops_learning_chunks": _compact_ops_learning_evidence(learning_chunks),
        "guide_step": guide_payload,
    }
    system = (
        "당신은 실운영 가이드의 마지막 답변 작성 agent다. "
        "입력으로 주어지는 초안 답변과 근거 청크를 바탕으로, 사용자가 바로 이해할 수 있는 운영 가이드 답변으로 재작성한다. "
        "청크 문장을 그대로 복사하지 말고, 의미를 유지한 채 자연스러운 한국어로 정리한다. "
        "근거에 없는 원인, 명령, 수치, 버전, 절차를 새로 만들지 않는다. "
        "내부 문서 ID, native_id, chunk_id, 파일명은 노출하지 않는다. "
        "한국어 조사 앞뒤에 어색한 공백을 넣지 말고, Pod, CPU, Memory, HPA, Scale-out, Scale-in 같은 기술 용어 표기는 일관되게 유지한다. "
        "예를 들어 'HPA 는'이 아니라 'HPA는', 'Pod 의'가 아니라 'Pod의', '15 초'가 아니라 '15초', "
        "'metrics-server 로부터'가 아니라 'metrics-server로부터'처럼 쓴다. "
        "citation은 반드시 제공된 번호만 [1], [2] 형식으로 유지한다. "
        "'실운영 가이드 기준' 같은 시스템 prefix로 시작하지 말고, 바로 사용자 질문에 대한 답으로 시작한다. "
        "출력은 답변 본문만 작성한다."
    )
    user = (
        f"사용자 질문:\n{query}\n\n"
        f"초안 답변:\n{draft_answer}\n\n"
        f"근거 데이터(JSON):\n{json.dumps(evidence, ensure_ascii=False, indent=2)}\n\n"
        "재작성 규칙:\n"
        "- 첫 문단에서 질문에 대한 결론이나 어디부터 봐야 하는지를 바로 말한다.\n"
        "- 이후 2~4개의 짧은 단계나 bullet로 확인 순서를 정리한다.\n"
        "- 원문 OCR처럼 이어진 문장은 그대로 복사하지 말고 운영자가 읽기 쉬운 문장으로 다듬는다.\n"
        "- POD처럼 대문자로 추출된 일반 리소스명은 자연스러운 기술 표기(Pod)로 정리한다.\n"
        "- 띄어쓰기와 조사를 자연스럽게 다듬는다. 예: 'HPA는', 'Pod의', '기본값 15초', 'max 값까지', 'Scale-out은 Pod를 늘리는 동작'처럼 작성한다.\n"
        "- 콜론으로 끊긴 원문 조각은 문장으로 풀어쓴다. 예: 'Scale-out : POD 확장' 대신 'Scale-out은 Pod를 확장하는 동작입니다.'처럼 쓴다.\n"
        "- 초안의 '확인할 것', '상태 기준', '다음에 볼 단계' 정보는 필요하면 유지하되 중복은 줄인다.\n"
        "- 각 핵심 문장이나 bullet 끝에는 관련 citation을 붙인다.\n"
        "- 근거가 부족한 내용은 쓰지 않는다.\n"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _course_answer_style_issues(answer: str) -> list[str]:
    text = str(answer or "")
    issues: list[str] = []
    token_particle_pattern = re.compile(
        r"\b(?:HPA|Pod|CPU|Memory|ArgoCD|HAProxy|Prometheus|JVM|DBMS|Scale-out|Scale-in)\s+(?:은|는|이|가|을|를|의|로|와|과)\b"
    )
    issues.extend(match.group(0) for match in token_particle_pattern.finditer(text))
    issues.extend(match.group(0) for match in re.finditer(r"\b\d+\s+(?:초|분|개|개월|EA|GB|G)(?=\b|마다|간|을|를|의|로|와|과)", text))
    for pattern in (r"metrics-server\s+로부터", r"\bmax\s+값\s+까지\b", r"\bmin\s+값\s+이하\b"):
        issues.extend(match.group(0) for match in re.finditer(pattern, text, flags=re.IGNORECASE))
    return list(dict.fromkeys(issues))[:12]


def _apply_course_answer_typography(answer: str) -> str:
    text = str(answer or "")
    token_pattern = r"\b(HPA|Pod|CPU|Memory|ArgoCD|HAProxy|Prometheus|JVM|DBMS|Scale-out|Scale-in)\s+(은|는|이|가|을|를|의|로|와|과)(?=\s|[.,:;)\]\n]|$)"
    text = re.sub(token_pattern, r"\1\2", text)
    text = re.sub(r"\b(\d+)\s+(초|분|개|개월|EA|GB|G)(?=마다|간|을|를|의|로|와|과|\s|[.,:;)\]\n]|$)", r"\1\2", text)
    text = re.sub(r"metrics-server\s+로부터", "metrics-server로부터", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(max|min)\s+값\s+까지\b", r"\1 값까지", text, flags=re.IGNORECASE)
    text = re.sub(r"([가-힣])\s+\(([^)\n]+)\)", r"\1(\2)", text)
    return text.strip()


def _build_course_answer_copyedit_messages(*, answer: str, style_issues: list[str]) -> list[dict[str, str]]:
    system = (
        "당신은 실운영 가이드 답변의 최종 한국어 교정 agent다. "
        "새 정보, 새 절차, 새 citation을 추가하지 말고 기존 답변의 의미와 citation 번호를 그대로 유지한다. "
        "오직 한국어 조사, 띄어쓰기, 콜론으로 끊긴 원문 조각, 기술 용어 표기만 자연스럽게 교정한다. "
        "출력은 교정된 답변 본문만 작성한다."
    )
    user = (
        f"교정할 답변:\n{answer}\n\n"
        f"반드시 없애야 하는 어색한 표기:\n{json.dumps(style_issues, ensure_ascii=False, indent=2)}\n\n"
        "교정 기준:\n"
        "- 'HPA 는' -> 'HPA는', 'Pod 의' -> 'Pod의', 'Pod 를' -> 'Pod를'처럼 기술 용어와 조사를 붙인다.\n"
        "- '15 초', '5 분', '300 개' -> '15초', '5분', '300개'처럼 수량과 단위를 붙인다.\n"
        "- 'metrics-server 로부터' -> 'metrics-server로부터'처럼 조사 표현을 붙인다.\n"
        "- 'Scale-out : POD 확장'처럼 끊긴 표현은 'Scale-out은 Pod를 확장하는 동작입니다.'처럼 문장으로 풀어쓴다.\n"
        "- citation 번호 [1], [2]와 bullet 구조는 유지한다.\n"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _rewrite_course_answer_with_llm(
    *,
    settings: Any,
    query: str,
    draft_answer: str,
    sources: list[dict[str, Any]],
    learning_chunks: list[dict[str, Any]],
    guide_step: dict[str, Any] | None,
) -> tuple[str, str]:
    if not _course_answer_llm_rewrite_enabled(settings):
        return draft_answer, ""
    messages = _build_course_answer_rewrite_messages(
        query=query,
        draft_answer=draft_answer,
        sources=sources,
        learning_chunks=learning_chunks,
        guide_step=guide_step,
    )
    client = LLMClient(settings)
    rewritten = client.generate(messages, max_tokens=min(max(int(getattr(settings, "llm_max_tokens", 900) or 900), 600), 1200))
    rewritten = re.sub(r"^\s*답변\s*:\s*", "", str(rewritten or "").strip(), flags=re.IGNORECASE)
    rewritten = re.sub(r"^\s*(?:Study-docs|실운영 가이드)\s*기준\s*", "", rewritten).strip()
    if len(rewritten) < 40:
        raise ValueError("course answer rewrite returned too little content")
    style_issues = _course_answer_style_issues(rewritten)
    if style_issues:
        copyedit_messages = _build_course_answer_copyedit_messages(answer=rewritten, style_issues=style_issues)
        copyedited = client.generate(copyedit_messages, max_tokens=min(max(int(getattr(settings, "llm_max_tokens", 900) or 900), 600), 1200))
        copyedited = re.sub(r"^\s*답변\s*:\s*", "", str(copyedited or "").strip(), flags=re.IGNORECASE)
        copyedited = re.sub(r"^\s*(?:Study-docs|실운영 가이드)\s*기준\s*", "", copyedited).strip()
        if len(copyedited) >= 40:
            rewritten = copyedited
    rewritten = _apply_course_answer_typography(rewritten)
    allowed_citations = {str(source.get("index")) for source in sources if isinstance(source, dict) and source.get("index")}
    used_citations = set(re.findall(r"\[(\d+)\]", rewritten))
    if used_citations and not used_citations.issubset(allowed_citations) and len(allowed_citations) == 1:
        only_citation = next(iter(allowed_citations))
        rewritten = re.sub(r"\[(\d+)\]", f"[{only_citation}]", rewritten)
        used_citations = {only_citation}
    if used_citations and not used_citations.issubset(allowed_citations):
        raise ValueError("course answer rewrite used unsupported citations")
    if allowed_citations and not used_citations:
        rewritten = f"{rewritten.rstrip()} [1]"
    return rewritten, "llm"


def _chunk_learning_summary(chunk: dict[str, Any], *, query: str = "") -> str:
    if str(chunk.get("stage_id") or "") == "perf_test" and _is_performance_bottleneck_intent(query):
        performance_summary = _performance_learning_summary(chunk)
        if performance_summary:
            return performance_summary
    facets = chunk.get("facets") if isinstance(chunk.get("facets"), dict) else {}
    technologies = [str(item) for item in facets.get("technologies", []) if str(item).strip()] if isinstance(facets.get("technologies"), list) else []
    network_zones = [str(item) for item in facets.get("network_zones", []) if str(item).strip()] if isinstance(facets.get("network_zones"), list) else []
    if technologies or network_zones:
        parts = []
        if technologies:
            parts.append(f"주요 기술은 {', '.join(technologies[:8])}입니다")
        if network_zones:
            parts.append(f"주요 영역은 {', '.join(network_zones[:5])}입니다")
        return ". ".join(parts) + "."
    search_text = str(chunk.get("search_text") or "").strip()
    if search_text:
        lines = [line.strip() for line in search_text.splitlines() if line.strip()]
        if lines:
            return _short_text(" ".join(lines[:3]), limit=260)
    body = str(chunk.get("body_md") or "").strip()
    return _short_text(body or chunk.get("title") or "", limit=260)


def _chunk_grounded_detail(chunk: dict[str, Any], *, query: str = "") -> str:
    visual_text = str(chunk.get("visual_text") or "").strip()
    if visual_text:
        return _short_text(visual_text, limit=360)
    summary = _chunk_learning_summary(chunk, query=query)
    search_text = str(chunk.get("search_text") or "").strip()
    if search_text and len(summary) < 120:
        return _short_text(search_text, limit=360)
    return _short_text(summary, limit=360)


def _image_query_profile(query: str) -> str:
    normalized = _normalize_query(query)
    if any(term in normalized for term in ["fail", "failed", "error", "crashloop", "degraded", "장애", "실패", "오류", "에러", "비정상"]):
        return "troubleshooting"
    if any(term in normalized for term in ["metric", "metrics", "dashboard", "grafana", "prometheus", "performance", "성능", "메트릭", "대시보드", "모니터링"]):
        return "concept"
    if any(term in normalized for term in ["how", "verify", "check", "expected", "status", "절차", "방법", "검증", "확인", "정상", "상태", "실행"]):
        return "procedure"
    if any(term in normalized for term in ["architecture", "diagram", "topology", "구성도", "아키텍처", "구조", "개념"]):
        return "concept"
    return "procedure"


def _rank_image_attachment(attachment: dict[str, Any], *, profile: str, query: str = "") -> float:
    if attachment.get("exclude_from_default") or str(attachment.get("instructional_role") or "") == "decorative_or_empty":
        return -1.0
    roles = {str(item) for item in attachment.get("instructional_roles", []) if str(item).strip()}
    primary_role = str(attachment.get("instructional_role") or "")
    if primary_role:
        roles.add(primary_role)
    rank_profiles = attachment.get("rank_profiles") if isinstance(attachment.get("rank_profiles"), dict) else {}
    score = float(rank_profiles.get(profile) or max((float(value or 0.0) for value in rank_profiles.values()), default=0.0))
    score += float(attachment.get("evidence_strength") or 0.0) * 0.25
    if attachment.get("is_default_visible"):
        score += 0.05
    normalized_query = _normalize_query(query)
    state = str(attachment.get("state_signal") or "")
    failure_states = {"Failed", "Error", "CrashLoopBackOff", "Degraded"}
    normal_states = {"Running", "Ready", "Succeeded", "Available", "Progressing"}
    is_failure_evidence = "failure_state" in roles or state in failure_states
    is_normal_evidence = bool({"expected_state_indicator", "success_state", "progress_state"} & roles or state in normal_states)
    if profile == "troubleshooting" and {"failure_state", "console_output", "dashboard_metric"} & roles:
        score += 0.8
    if profile == "troubleshooting" and is_failure_evidence:
        score += 2.8
    if profile == "troubleshooting" and is_normal_evidence and not is_failure_evidence:
        score -= 0.4
    if profile == "procedure" and {"command_result_evidence", "expected_state_indicator", "success_state", "progress_state"} & roles:
        score += 0.8
    if profile == "procedure" and is_normal_evidence:
        score += 1.4
    if profile == "procedure" and is_failure_evidence:
        score -= 0.6
    if profile == "concept" and {"diagram", "table"} & roles:
        score += 0.25
    if profile == "concept" and "main_diagram" in roles:
        score += 2.0
    if profile == "concept" and "sub_diagram" in roles:
        score -= 0.5
    if state and _normalize_query(state) in normalized_query:
        score += 5.0
    if "table" in roles and any(term in normalized_query for term in ["table", "표", "결과", "매트릭스"]):
        score += 3.0
    if "diagram" in roles and any(term in normalized_query for term in ["diagram", "구성도", "아키텍처", "그림", "구조"]):
        score += 2.0
    if "dashboard_metric" in roles and any(
        term in normalized_query for term in ["metric", "metrics", "dashboard", "grafana", "prometheus", "performance", "성능", "메트릭", "대시보드", "모니터링"]
    ):
        score += 1.5
    if "expected_state_indicator" in roles and any(term in normalized_query for term in ["ready", "running", "succeeded", "정상", "상태", "확인"]):
        score += 0.9
    attachment_text = _normalize_query(
        " ".join(
            str(part or "")
            for part in [
                attachment.get("visual_summary"),
                attachment.get("caption_text"),
                attachment.get("ocr_text"),
                attachment.get("state_signal"),
                attachment.get("instructional_role"),
                " ".join(str(role) for role in roles),
            ]
        )
    )
    token_matches = 0
    for token in normalized_query.split():
        if len(token) >= 4 and token in attachment_text:
            token_matches += 1
    score += min(token_matches, 10) * 0.08
    return score


def _image_evidence_items(chunks: list[dict[str, Any]], *, query: str, limit: int = 5) -> list[dict[str, Any]]:
    profile = _image_query_profile(query)
    ranked: list[tuple[float, int, dict[str, Any]]] = []
    serial = 0
    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id") or "")
        native_id = str(chunk.get("native_id") or "")
        title = _public_chunk_label(chunk)
        attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            score = _rank_image_attachment(attachment, profile=profile, query=query)
            if score < 0:
                continue
            serial += 1
            ranked.append(
                (
                    score,
                    serial,
                    {
                        "chunk_id": chunk_id,
                        "native_id": native_id,
                        "title": title,
                        "viewer_path": f"/course/chunks/{chunk_id}",
                        "asset_id": str(attachment.get("asset_id") or ""),
                        "asset_path": str(attachment.get("asset_path") or ""),
                        "slide_no": int(attachment.get("slide_no") or 0),
                        "instructional_role": str(attachment.get("instructional_role") or ""),
                        "instructional_roles": attachment.get("instructional_roles") if isinstance(attachment.get("instructional_roles"), list) else [],
                        "quality_label": str(attachment.get("quality_label") or ""),
                        "state_signal": str(attachment.get("state_signal") or ""),
                        "summary": _short_text(attachment.get("visual_summary") or attachment.get("caption_text") or attachment.get("ocr_text") or "", limit=260),
                        "rank_profile": profile,
                        "score": round(score, 3),
                    },
                )
            )
    ranked.sort(key=lambda item: (-item[0], item[1]))
    items: list[dict[str, Any]] = []
    seen_asset: set[str] = set()
    seen_slide: set[tuple[str, int]] = set()
    seen_summary: set[str] = set()
    for _, _, item in ranked:
        asset_id = str(item.get("asset_id") or "")
        if asset_id and asset_id in seen_asset:
            continue
        summary_key = _normalize_query(item.get("summary") or "")[:100]
        if summary_key and summary_key in seen_summary:
            continue
        slide_key = (str(item.get("chunk_id") or ""), int(item.get("slide_no") or 0))
        if profile == "concept" and slide_key in seen_slide:
            continue
        if asset_id:
            seen_asset.add(asset_id)
        if summary_key:
            seen_summary.add(summary_key)
        seen_slide.add(slide_key)
        items.append(item)
        if len(items) >= limit:
            break
    return items


def _official_doc_key(doc: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(doc.get("book_slug") or doc.get("title") or "").strip(),
        str(doc.get("section_id") or "").strip(),
        str(doc.get("section_title") or "").strip(),
    )


def _official_doc_summary(doc: dict[str, Any], *, related_chunk_id: str = "", stage_id: str = "") -> dict[str, Any]:
    return {
        "book_slug": str(doc.get("book_slug") or ""),
        "section_id": str(doc.get("section_id") or ""),
        "title": str(doc.get("title") or doc.get("book_slug") or "Official doc"),
        "section_title": str(doc.get("section_title") or ""),
        "snippet": _short_text(doc.get("snippet") or doc.get("text") or "", limit=220),
        "score": float(doc.get("score") or 0.0),
        "trusted": bool(doc.get("trusted", True)),
        "match_reason": str(doc.get("match_reason") or "").strip(),
        "related_chunk_id": related_chunk_id,
        "stage_id": stage_id,
    }


def _collect_official_docs(chunks: list[dict[str, Any]], official_hits: list[dict[str, Any]], *, limit: int = 4) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id") or "")
        stage_id = str(chunk.get("stage_id") or "")
        for doc in _trusted_official_docs(chunk.get("related_official_docs")):
            key = _official_doc_key(doc)
            if key in seen:
                continue
            seen.add(key)
            docs.append(_official_doc_summary(doc, related_chunk_id=chunk_id, stage_id=stage_id))
            if len(docs) >= limit:
                return docs
    for doc in official_hits:
        key = _official_doc_key(doc)
        if key in seen:
            continue
        seen.add(key)
        docs.append(_official_doc_summary(doc))
        if len(docs) >= limit:
            break
    return docs


def _stage_official_docs(root_dir: Path, stage_id: str, *, limit: int = 4) -> list[dict[str, Any]]:
    if not stage_id:
        return []
    try:
        manifest = _load_manifest(root_dir)
    except Exception:  # noqa: BLE001
        return []
    for stage in manifest.get("stages", []) if isinstance(manifest.get("stages"), list) else []:
        if not isinstance(stage, dict) or str(stage.get("stage_id") or "") != stage_id:
            continue
        refs = stage.get("official_route_refs") if isinstance(stage.get("official_route_refs"), list) else []
        return [_official_doc_summary(ref, stage_id=stage_id) for ref in refs if isinstance(ref, dict)][:limit]
    return []


def _stage_start_chunk_ids(root_dir: Path, stage_id: str, *, limit: int = 3) -> list[str]:
    if not stage_id:
        return []
    try:
        manifest = _load_manifest(root_dir)
    except Exception:  # noqa: BLE001
        return []
    for stage in manifest.get("stages", []) if isinstance(manifest.get("stages"), list) else []:
        if not isinstance(stage, dict) or str(stage.get("stage_id") or "") != stage_id:
            continue
        learning_route = stage.get("learning_route") if isinstance(stage.get("learning_route"), dict) else {}
        rows = learning_route.get("start_here") if isinstance(learning_route.get("start_here"), list) else []
        return [str(item) for item in rows if str(item).strip()][:limit]
    return []


def _guided_tour_items(root_dir: Path, chunks: list[dict[str, Any]], *, limit: int = 3) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    by_id: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id") or "")
        if chunk_id:
            by_id[chunk_id] = chunk

    def load_if_needed(chunk_id: str) -> dict[str, Any] | None:
        if not chunk_id:
            return None
        if chunk_id in by_id:
            return by_id[chunk_id]
        try:
            loaded = _load_chunk(root_dir, chunk_id)
        except Exception:  # noqa: BLE001
            return None
        by_id[chunk_id] = loaded
        return loaded

    for chunk in chunks:
        tour_stop = chunk.get("tour_stop") if isinstance(chunk.get("tour_stop"), dict) else {}
        if not tour_stop:
            continue
        current_id = str(chunk.get("chunk_id") or "")
        if current_id and current_id not in seen:
            current_label = _clean_beginner_title(chunk.get("title") or current_id)
            seen.add(current_id)
            items.append(
                {
                    "role": "current",
                    "chunk_id": current_id,
                    "stage_id": str(chunk.get("stage_id") or ""),
                    "title": str(chunk.get("title") or current_id),
                    "label": current_label,
                    "question": _chunk_beginner_question(chunk, intent="learn"),
                    "native_id": str(chunk.get("native_id") or ""),
                    "stop_order": int(tour_stop.get("stop_order") or 0),
                    "total_stops": int(tour_stop.get("total_stops") or 0),
                    "route_role": str(tour_stop.get("route_role") or "standard"),
                    "viewer_path": f"/course/chunks/{current_id}",
                    "reason": "지금 질문에서 먼저 확인할 단계입니다.",
                }
            )
        next_id = str(tour_stop.get("next_chunk_id") or "").strip()
        next_chunk = load_if_needed(next_id)
        if next_chunk is not None and next_id not in seen:
            next_tour = next_chunk.get("tour_stop") if isinstance(next_chunk.get("tour_stop"), dict) else {}
            next_label = _clean_beginner_title(next_chunk.get("title") or next_id)
            seen.add(next_id)
            items.append(
                {
                    "role": "next",
                    "chunk_id": next_id,
                    "stage_id": str(next_chunk.get("stage_id") or ""),
                    "title": str(next_chunk.get("title") or next_id),
                    "label": next_label,
                    "question": _chunk_beginner_question(next_chunk, intent="next"),
                    "native_id": str(next_chunk.get("native_id") or ""),
                    "stop_order": int(next_tour.get("stop_order") or 0),
                    "total_stops": int(next_tour.get("total_stops") or 0),
                    "route_role": str(next_tour.get("route_role") or "standard"),
                    "viewer_path": f"/course/chunks/{next_id}",
                    "reason": "이어서 확인할 다음 단계입니다.",
                }
            )
        if len(items) >= limit:
            break
    return items[:limit]


def _iter_ops_guide_steps(root_dir: Path) -> Iterable[tuple[dict[str, Any], dict[str, Any]]]:
    payload = _load_ops_learning_guides(root_dir)
    guides = payload.get("guides") if isinstance(payload.get("guides"), list) else []
    for guide in guides:
        if not isinstance(guide, dict):
            continue
        steps = guide.get("steps") if isinstance(guide.get("steps"), list) else []
        for step in steps:
            if isinstance(step, dict):
                yield guide, step


def _guide_step_source_chunk_ids(step: dict[str, Any]) -> list[str]:
    anchors = step.get("source_anchors") if isinstance(step.get("source_anchors"), list) else []
    chunk_ids: list[str] = []
    for anchor in anchors:
        if not isinstance(anchor, dict):
            continue
        chunk_id = str(anchor.get("chunk_id") or "").strip()
        if chunk_id and chunk_id not in chunk_ids:
            chunk_ids.append(chunk_id)
    return chunk_ids


def _learning_chunk_text(chunk: dict[str, Any]) -> str:
    rows: list[str] = []
    for key in ("title", "learning_goal", "beginner_explanation", "source_summary", "official_mapping_summary", "embedding_text"):
        value = str(chunk.get(key) or "").strip()
        if value:
            rows.append(value)
    for key in (
        "operational_sequence",
        "what_to_look_for",
        "normal_state",
        "failure_state",
        "visual_evidence_roles",
        "query_variants",
        "source_titles",
        "source_terms",
        "image_evidence_texts",
    ):
        value = chunk.get(key)
        if isinstance(value, list):
            rows.extend(str(item).strip() for item in value if str(item).strip())
    return "\n".join(dict.fromkeys(rows))


def _learning_source_chunk_ids(chunk: dict[str, Any]) -> list[str]:
    return [str(item).strip() for item in chunk.get("source_chunk_ids", []) if str(item).strip()] if isinstance(chunk.get("source_chunk_ids"), list) else []


def _search_ops_learning_chunks(
    root_dir: Path,
    *,
    query: str,
    stage_id: str = "",
    guide_id: str = "",
    step_id: str = "",
    limit: int = 5,
) -> list[tuple[float, dict[str, Any]]]:
    rows = _load_ops_learning_chunks(root_dir)
    if not rows:
        return []
    tokens = set(_tokenize(query))
    normalized_query = _normalize_query(query)
    ranked: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        if stage_id and str(row.get("stage_id") or "") != stage_id:
            continue
        text = _learning_chunk_text(row)
        normalized_text = _normalize_query(text)
        text_tokens = set(_tokenize(text))
        score = float(len(tokens & text_tokens) * 12)
        title = _normalize_query(row.get("title") or "")
        if title and title in normalized_query:
            score += 120
        for variant in row.get("query_variants", []) if isinstance(row.get("query_variants"), list) else []:
            normalized_variant = _normalize_query(variant)
            if normalized_variant and normalized_variant == normalized_query:
                score += 40
            elif normalized_variant and normalized_variant in normalized_query:
                score += 18
        if guide_id and str(row.get("guide_id") or "") == guide_id:
            score += 18
        if step_id and str(row.get("step_id") or "") == step_id:
            score += 24
        if normalized_query and normalized_query in normalized_text:
            score += 20
        if score <= 0:
            continue
        ranked.append((score, row))
    ranked.sort(key=lambda item: (-item[0], str(item[1].get("learning_chunk_id") or "")))
    return ranked[:limit]


def _ops_learning_chunk_by_step(root_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    rows = _load_ops_learning_chunks(root_dir)
    return {
        (str(row.get("guide_id") or ""), str(row.get("step_id") or "")): row
        for row in rows
        if str(row.get("guide_id") or "") and str(row.get("step_id") or "")
    }


def _ops_learning_tour_items(root_dir: Path, learning_chunk: dict[str, Any], *, limit: int = 3) -> list[dict[str, Any]]:
    by_key = _ops_learning_chunk_by_step(root_dir)
    items: list[dict[str, Any]] = []
    seen_steps: set[tuple[str, str]] = set()
    seen_chunks: set[str] = set()

    def first_question(candidate: dict[str, Any]) -> str:
        variants = candidate.get("query_variants") if isinstance(candidate.get("query_variants"), list) else []
        for variant in variants:
            text = _public_course_text(variant, limit=140)
            if text:
                return text
        return _public_course_text(candidate.get("title") or "", limit=120)

    def append_item(role: str, candidate: dict[str, Any], reason: str) -> None:
        source_ids = _learning_source_chunk_ids(candidate)
        chunk_id = source_ids[0] if source_ids else ""
        step_key = (str(candidate.get("guide_id") or ""), str(candidate.get("step_id") or ""))
        if step_key in seen_steps or (chunk_id and chunk_id in seen_chunks):
            return
        seen_steps.add(step_key)
        if chunk_id:
            seen_chunks.add(chunk_id)
        title = _public_course_text(candidate.get("title") or candidate.get("learning_goal") or "", limit=120)
        items.append(
            {
                "role": role,
                "guide_id": str(candidate.get("guide_id") or ""),
                "step_id": str(candidate.get("step_id") or ""),
                "chunk_id": chunk_id,
                "stage_id": str(candidate.get("stage_id") or ""),
                "title": title,
                "label": title,
                "question": first_question(candidate),
                "native_id": "",
                "route_role": "ops_learning_retrieved",
                "viewer_path": f"/course/chunks/{chunk_id}" if chunk_id else "",
                "reason": reason,
            }
        )

    append_item("current", learning_chunk, "retrieved_ops_learning_step")
    next_keys: list[tuple[str, str]] = []
    guide_id = str(learning_chunk.get("guide_id") or "")
    for next_step_id in learning_chunk.get("next_step_ids", []) if isinstance(learning_chunk.get("next_step_ids"), list) else []:
        next_keys.append((guide_id, str(next_step_id)))
    next_guide = learning_chunk.get("next_guide") if isinstance(learning_chunk.get("next_guide"), dict) else {}
    if next_guide:
        next_keys.append((str(next_guide.get("guide_id") or ""), str(next_guide.get("step_id") or "")))
    for key in next_keys:
        candidate = by_key.get(key)
        if candidate:
            append_item("next", candidate, "retrieved_context_next_step")
        if len(items) >= limit:
            break
    return items[:limit]


def _resolve_ops_guide_step(
    root_dir: Path,
    *,
    query: str,
    stage_id: str = "",
    guide_id: str = "",
    step_id: str = "",
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    normalized_query = _normalize_query(query)
    query_tokens = set(_tokenize(query))
    best_score = 0
    best: tuple[dict[str, Any], dict[str, Any]] | None = None
    for guide, step in _iter_ops_guide_steps(root_dir):
        if guide_id and str(guide.get("guide_id") or "") != guide_id:
            continue
        if stage_id and str(step.get("stage_id") or guide.get("stage_id") or "") != stage_id:
            continue
        if step_id and str(step.get("step_id") or "") == step_id:
            return guide, step
        fields = [
            step.get("user_query"),
            step.get("card_text"),
            step.get("learning_objective"),
            guide.get("title"),
            guide.get("learning_goal"),
        ]
        normalized_fields = [_normalize_query(field) for field in fields if str(field or "").strip()]
        score = 0
        if normalized_query and normalized_query in normalized_fields[:2]:
            score += 1000
        elif any(normalized_field and normalized_field in normalized_query for normalized_field in normalized_fields[:2]):
            score += 300
        candidate_tokens = set(_tokenize(" ".join(str(field or "") for field in fields)))
        score += len(query_tokens & candidate_tokens) * 18
        if any(term in normalized_query for term in ("순서", "흐름", "어디부터", "무엇", "어떻게", "확인", "보면")):
            score += 20
        if score > best_score:
            best_score = score
            best = (guide, step)
    return best if best_score >= 54 else None


def _ops_guide_tour_items(root_dir: Path, guide: dict[str, Any], step: dict[str, Any], *, limit: int = 3) -> list[dict[str, Any]]:
    payload = _load_ops_learning_guides(root_dir)
    all_guides = payload.get("guides") if isinstance(payload.get("guides"), list) else []
    guides_by_id = {str(item.get("guide_id") or ""): item for item in all_guides if isinstance(item, dict)}
    steps = guide.get("steps") if isinstance(guide.get("steps"), list) else []
    by_step_id = {str(item.get("step_id") or ""): item for item in steps if isinstance(item, dict)}
    items: list[dict[str, Any]] = []

    def append_step(role: str, candidate: dict[str, Any], reason: str, *, source_guide: dict[str, Any] | None = None) -> None:
        item_guide = source_guide or guide
        chunk_ids = _guide_step_source_chunk_ids(candidate)
        first_chunk_id = chunk_ids[0] if chunk_ids else ""
        title = str(candidate.get("card_text") or candidate.get("user_query") or candidate.get("step_id") or "")
        items.append(
            {
                "role": role,
                "guide_id": str(item_guide.get("guide_id") or ""),
                "step_id": str(candidate.get("step_id") or ""),
                "chunk_id": first_chunk_id,
                "stage_id": str(candidate.get("stage_id") or item_guide.get("stage_id") or ""),
                "title": title,
                "label": title,
                "question": str(candidate.get("user_query") or ""),
                "native_id": "",
                "route_role": "ops_learning_guide",
                "viewer_path": f"/course/chunks/{first_chunk_id}" if first_chunk_id else "",
                "reason": reason,
            }
        )

    append_step("current", step, "현재 학습 카드입니다.")
    for next_step_id in step.get("next_step_ids", []) if isinstance(step.get("next_step_ids"), list) else []:
        next_step = by_step_id.get(str(next_step_id))
        if next_step:
            append_step("next", next_step, "이어서 볼 운영 학습 카드입니다.")
        if len(items) >= limit:
            break
    if len(items) < limit:
        next_guide = step.get("next_guide") if isinstance(step.get("next_guide"), dict) else {}
        next_guide_id = str(next_guide.get("guide_id") or "")
        next_step_id = str(next_guide.get("step_id") or "")
        linked_guide = guides_by_id.get(next_guide_id)
        linked_steps = linked_guide.get("steps") if isinstance(linked_guide, dict) and isinstance(linked_guide.get("steps"), list) else []
        linked_by_step_id = {str(item.get("step_id") or ""): item for item in linked_steps if isinstance(item, dict)}
        linked_step = linked_by_step_id.get(next_step_id)
        if linked_guide and linked_step:
            append_step("next", linked_step, "다음 운영 학습 경로의 첫 카드입니다.", source_guide=linked_guide)
    return items[:limit]


def _normalize_chunk_payload(chunk: dict[str, Any]) -> dict[str, Any]:
    payload = dict(chunk)
    payload["schema_version"] = str(payload.get("schema_version") or "ppt_chunk_v1")
    payload["source_kind"] = str(payload.get("source_kind") or "project_artifact")
    payload["index_texts"] = _index_texts_for_chunk(payload)
    payload["related_official_docs"] = _annotate_official_docs(payload.get("related_official_docs"))
    return payload


def _load_chunk(root_dir: Path, chunk_id: str) -> dict[str, Any]:
    chunk_id = _validate_chunk_id(chunk_id)
    chunks_jsonl = _course_chunks_jsonl_path(root_dir)
    chunks_dir = _course_chunks_dir(root_dir)
    cache_source = chunks_jsonl if chunks_jsonl.exists() else chunks_dir
    cache_key = f"{cache_source}:{chunk_id}"
    now = time.monotonic()
    with _COURSE_CHUNK_CACHE_LOCK:
        cached_single = _COURSE_SINGLE_CHUNK_CACHE.get(cache_key)
        if cached_single is not None and now - cached_single[0] < COURSE_CHUNK_CACHE_TTL_SECONDS:
            return dict(cached_single[1])
        cached_full = _COURSE_CHUNK_CACHE.get(str(cache_source))
        if cached_full is not None and now - cached_full[0] < COURSE_CHUNK_CACHE_TTL_SECONDS:
            payload = cached_full[2].get(chunk_id)
            if payload is not None:
                return dict(payload)

    if chunks_jsonl.exists():
        _, by_id = _course_chunk_cache(root_dir)
        payload = by_id.get(chunk_id)
        if payload is None:
            raise FileNotFoundError(f"Course chunk not found: {chunk_id}")
        return dict(payload)

    path = chunks_dir / f"{chunk_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Course chunk not found: {chunk_id}")
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise ValueError("Course chunk is invalid")
    normalized = _normalize_chunk_payload(payload)
    with _COURSE_CHUNK_CACHE_LOCK:
        _COURSE_SINGLE_CHUNK_CACHE[cache_key] = (now, normalized)
        while len(_COURSE_SINGLE_CHUNK_CACHE) > 256:
            _COURSE_SINGLE_CHUNK_CACHE.pop(next(iter(_COURSE_SINGLE_CHUNK_CACHE)))
    return dict(normalized)


def _iter_chunks(root_dir: Path) -> list[dict[str, Any]]:
    rows, _ = _course_chunk_cache(root_dir)
    return [dict(row) for row in rows]


def _course_chunk_cache(root_dir: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    chunks_jsonl = _course_chunks_jsonl_path(root_dir)
    chunks_dir = _course_chunks_dir(root_dir)
    cache_key = str(chunks_jsonl if chunks_jsonl.exists() else chunks_dir)
    now = time.monotonic()
    with _COURSE_CHUNK_CACHE_LOCK:
        cached = _COURSE_CHUNK_CACHE.get(cache_key)
        if cached is not None and now - cached[0] < COURSE_CHUNK_CACHE_TTL_SECONDS:
            return cached[1], cached[2]

    rows: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    if chunks_jsonl.exists():
        for payload in _read_jsonl(chunks_jsonl):
            if not isinstance(payload, dict):
                continue
            normalized = _normalize_chunk_payload(payload)
            chunk_id = str(normalized.get("chunk_id") or "").strip()
            if not chunk_id:
                continue
            rows.append(normalized)
            by_id[chunk_id] = normalized
    elif chunks_dir.exists():
        for path in sorted(chunks_dir.glob("*.json")):
            try:
                payload = _read_json(path)
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(payload, dict):
                continue
            normalized = _normalize_chunk_payload(payload)
            chunk_id = str(normalized.get("chunk_id") or "").strip()
            if not chunk_id:
                continue
            rows.append(normalized)
            by_id[chunk_id] = normalized
    with _COURSE_CHUNK_CACHE_LOCK:
        _COURSE_CHUNK_CACHE[cache_key] = (now, rows, by_id)
    return rows, by_id


def _chunk_summary(chunk: dict[str, Any]) -> dict[str, Any]:
    slide_refs = chunk.get("slide_refs") if isinstance(chunk.get("slide_refs"), list) else []
    return {
        "chunk_id": str(chunk.get("chunk_id") or ""),
        "title": str(chunk.get("title") or ""),
        "native_id": str(chunk.get("native_id") or ""),
        "variant": chunk.get("variant"),
        "chunk_kind": str(chunk.get("chunk_kind") or ""),
        "review_status": str(chunk.get("review_status") or ""),
        "bundle_id": str(chunk.get("bundle_id") or ""),
        "parent_chunk_id": str(chunk.get("parent_chunk_id") or ""),
        "slide_count": len(slide_refs),
        "slide_refs": slide_refs[:1],
        "related_official_docs": _trusted_official_docs(chunk.get("related_official_docs")),
        "beginner_label": _clean_beginner_title(chunk.get("title") or chunk.get("chunk_id") or ""),
        "beginner_question": _chunk_beginner_question(chunk, intent="learn"),
        "next_question": _chunk_beginner_question(chunk, intent="next"),
        "verification_question": _chunk_beginner_question(chunk, intent="verify"),
    }


def _guided_card_for_chunk(chunk: dict[str, Any], *, role: str) -> dict[str, Any]:
    intent = "next" if role == "then_open" else "learn"
    if role == "official_check":
        intent = "official"
    return {
        "role": role,
        "chunk_id": str(chunk.get("chunk_id") or ""),
        "stage_id": str(chunk.get("stage_id") or ""),
        "label": _clean_beginner_title(chunk.get("title") or chunk.get("chunk_id") or ""),
        "question": _chunk_beginner_question(chunk, intent=intent),
        "viewer_path": f"/course/chunks/{chunk.get('chunk_id') or ''}",
        "atlas_path": f"/course/atlas/{chunk.get('chunk_id') or ''}",
        "slide_count": len(chunk.get("slide_refs") if isinstance(chunk.get("slide_refs"), list) else []),
        "official_ref_count": len(_trusted_official_docs(chunk.get("related_official_docs"))),
        "source": {
            "chunk_id": str(chunk.get("chunk_id") or ""),
            "native_id": str(chunk.get("native_id") or ""),
            "hidden_doc_anchor": True,
        },
    }


def _guided_card_for_ops_step(root_dir: Path, guide: dict[str, Any], step: dict[str, Any], *, role: str) -> dict[str, Any]:
    chunk_ids = _guide_step_source_chunk_ids(step)
    chunk_id = chunk_ids[0] if chunk_ids else ""
    chunk: dict[str, Any] = {}
    if chunk_id:
        try:
            chunk = _load_chunk(root_dir, chunk_id)
        except Exception:  # noqa: BLE001
            chunk = {}
    slide_refs = chunk.get("slide_refs") if isinstance(chunk.get("slide_refs"), list) else []
    official_refs = _trusted_official_docs(chunk.get("related_official_docs"))
    quality = step.get("quality") if isinstance(step.get("quality"), dict) else {}
    anchors = step.get("source_anchors") if isinstance(step.get("source_anchors"), list) else []
    native_id = ""
    if anchors and isinstance(anchors[0], dict):
        native_id = str(anchors[0].get("native_id") or "")
    return {
        "role": role,
        "guide_id": str(guide.get("guide_id") or ""),
        "step_id": str(step.get("step_id") or ""),
        "chunk_id": chunk_id,
        "stage_id": str(step.get("stage_id") or guide.get("stage_id") or ""),
        "label": str(step.get("card_text") or step.get("user_query") or ""),
        "question": str(step.get("user_query") or ""),
        "learning_objective": str(step.get("learning_objective") or guide.get("learning_goal") or ""),
        "viewer_path": f"/course/chunks/{chunk_id}" if chunk_id else "",
        "atlas_path": f"/course/atlas/{chunk_id}" if chunk_id else "",
        "slide_count": len(slide_refs),
        "official_ref_count": len(official_refs),
        "quality": {
            "status": str(quality.get("status") or "draft"),
            "needs_review": quality.get("needs_review") if isinstance(quality.get("needs_review"), list) else [],
        },
        "source": {
            "chunk_id": chunk_id,
            "native_id": native_id,
            "hidden_doc_anchor": True,
        },
    }


def _guided_card_for_learning_chunk(root_dir: Path, learning_chunk: dict[str, Any], *, role: str) -> dict[str, Any]:
    source_ids = _learning_source_chunk_ids(learning_chunk)
    chunk_id = source_ids[0] if source_ids else ""
    chunk: dict[str, Any] = {}
    if chunk_id:
        try:
            chunk = _load_chunk(root_dir, chunk_id)
        except Exception:  # noqa: BLE001
            chunk = {}
    slide_refs = chunk.get("slide_refs") if isinstance(chunk.get("slide_refs"), list) else []
    variants = learning_chunk.get("query_variants") if isinstance(learning_chunk.get("query_variants"), list) else []
    question = ""
    for variant in variants:
        question = _public_course_text(variant, limit=140)
        if question:
            break
    if not question:
        question = _public_course_text(learning_chunk.get("title") or learning_chunk.get("learning_goal") or "", limit=140)
    return {
        "role": role,
        "guide_id": str(learning_chunk.get("guide_id") or ""),
        "step_id": str(learning_chunk.get("step_id") or ""),
        "chunk_id": chunk_id,
        "stage_id": str(learning_chunk.get("stage_id") or ""),
        "label": _public_course_text(learning_chunk.get("title") or "", limit=120),
        "question": question,
        "learning_objective": _public_course_text(learning_chunk.get("learning_goal") or learning_chunk.get("beginner_explanation") or "", limit=220),
        "viewer_path": f"/course/chunks/{chunk_id}" if chunk_id else "",
        "atlas_path": f"/course/atlas/{chunk_id}" if chunk_id else "",
        "slide_count": len(slide_refs),
        "official_ref_count": len(learning_chunk.get("official_ref_ids") if isinstance(learning_chunk.get("official_ref_ids"), list) else []),
        "quality": learning_chunk.get("quality") if isinstance(learning_chunk.get("quality"), dict) else {"status": "draft", "needs_review": []},
        "source": {
            "chunk_id": chunk_id,
            "native_id": "",
            "hidden_doc_anchor": True,
        },
    }


def _ops_guided_cards_for_stage(root_dir: Path, stage_id: str) -> dict[str, list[dict[str, Any]]]:
    start_here: list[dict[str, Any]] = []
    then_open: list[dict[str, Any]] = []
    learning_chunks = [row for row in _load_ops_learning_chunks(root_dir) if str(row.get("stage_id") or "") == stage_id]
    if learning_chunks:
        first_by_guide: set[str] = set()
        for row in learning_chunks:
            guide_id = str(row.get("guide_id") or "")
            role = "start_here" if guide_id not in first_by_guide else "then_open"
            first_by_guide.add(guide_id)
            card = _guided_card_for_learning_chunk(root_dir, row, role=role)
            if role == "start_here":
                start_here.append(card)
            else:
                then_open.append(card)
        return {"start_here": start_here, "then_open": then_open}
    for guide, step in _iter_ops_guide_steps(root_dir):
        if str(guide.get("stage_id") or "") != stage_id:
            continue
        step_ids = guide.get("step_ids") if isinstance(guide.get("step_ids"), list) else []
        role = "start_here" if str(step.get("step_id") or "") == str(guide.get("entry_step_id") or (step_ids[0] if step_ids else "")) else "then_open"
        card = _guided_card_for_ops_step(root_dir, guide, step, role=role)
        if role == "start_here":
            start_here.append(card)
        else:
            then_open.append(card)
    return {"start_here": start_here, "then_open": then_open}


def _search_chunks(
    root_dir: Path,
    *,
    query: str,
    stage_id: str = "",
    chunk_ids: list[str] | None = None,
    limit: int = 5,
) -> list[tuple[int, dict[str, Any]]]:
    tokens = _tokenize(query)
    if not tokens:
        return []
    query_text = str(query or "").lower()
    identifiers = _query_identifiers(query)
    allowed_chunk_ids = {item.strip() for item in (chunk_ids or []) if str(item).strip()}
    matches: list[tuple[int, dict[str, Any]]] = []
    for chunk in _iter_chunks(root_dir):
        if stage_id and str(chunk.get("stage_id") or "").strip() != stage_id:
            continue
        if allowed_chunk_ids and str(chunk.get("chunk_id") or "").strip() not in allowed_chunk_ids:
            continue
        attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
        attachment_text = " ".join(
            " ".join(
                str(attachment.get(key) or "")
                for key in ("ocr_text", "caption_text", "visual_summary", "instructional_role", "state_signal")
            )
            for attachment in attachments
            if isinstance(attachment, dict)
        )
        haystack = f"{chunk.get('title') or ''} {chunk.get('search_text') or chunk.get('body_md') or ''} {attachment_text}".lower()
        score = sum(2 for token in tokens if token in str(chunk.get("title") or "").lower())
        score += sum(1 for token in tokens if token in haystack)
        native_id = str(chunk.get("native_id") or "").strip()
        chunk_id = str(chunk.get("chunk_id") or "").strip()
        title = str(chunk.get("title") or "").strip().lower()
        if native_id and native_id.upper() in identifiers:
            score += 1000
        if chunk_id and chunk_id.lower() in query_text:
            score += 1000
        if title and len(title) >= 4 and title in query_text:
            score += 120
        if score <= 0:
            continue
        matches.append((score, chunk))
    matches.sort(key=lambda item: (-item[0], str(item[1].get("chunk_id") or "")))
    return matches[:limit]


def _resolve_route_step_chunk(root_dir: Path, *, query: str, stage_id: str = "") -> dict[str, Any] | None:
    normalized_query = _normalize_query(query)
    if not normalized_query:
        return None
    best_score = 0
    best_chunk: dict[str, Any] | None = None
    query_tokens = set(_tokenize(query))
    for chunk in _iter_chunks(root_dir):
        if stage_id and str(chunk.get("stage_id") or "").strip() != stage_id:
            continue
        tour_stop = chunk.get("tour_stop") if isinstance(chunk.get("tour_stop"), dict) else {}
        if not tour_stop:
            continue
        native_id = str(chunk.get("native_id") or "").strip()
        title = str(chunk.get("title") or "").strip()
        clean_title = _clean_beginner_title(title)
        candidate_text = " ".join(
            str(part or "")
            for part in [
                native_id,
                title,
                clean_title,
                chunk.get("search_text"),
                chunk.get("body_md"),
            ]
        )
        candidate_tokens = set(_tokenize(candidate_text))
        token_overlap = len(query_tokens & candidate_tokens)
        strong_match = False
        score = 0
        normalized_native_id = _normalize_query(native_id)
        if native_id and "-" in native_id and normalized_native_id in normalized_query:
            score += 500
            strong_match = True
        elif native_id and normalized_native_id in query_tokens:
            score += 500
            strong_match = True
        normalized_title = _normalize_query(title)
        normalized_clean_title = _normalize_query(clean_title)
        if normalized_title and len(normalized_title) >= 4 and normalized_title in normalized_query:
            score += 240
            strong_match = True
        if normalized_clean_title and len(normalized_clean_title) >= 4 and normalized_clean_title in normalized_query:
            score += 180
            strong_match = True
        score += token_overlap * 12
        if _is_next_step_intent(query) and str(tour_stop.get("next_chunk_id") or "").strip():
            score += 15
        if not strong_match and token_overlap < 3:
            continue
        if score > best_score:
            best_score = score
            best_chunk = chunk
    return best_chunk if best_score >= 36 else None


def _bundle_context_chunks(root_dir: Path, primary_chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not primary_chunks:
        return []
    by_id = {str(chunk.get("chunk_id") or ""): chunk for chunk in primary_chunks if str(chunk.get("chunk_id") or "")}
    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    def load_if_needed(chunk_id: str) -> dict[str, Any] | None:
        normalized = str(chunk_id or "").strip()
        if not normalized:
            return None
        if normalized in by_id:
            return by_id[normalized]
        try:
            loaded = _load_chunk(root_dir, normalized)
        except Exception:  # noqa: BLE001
            return None
        by_id[normalized] = loaded
        return loaded

    def append_chunk(chunk: dict[str, Any] | None) -> None:
        if not isinstance(chunk, dict):
            return
        chunk_id = str(chunk.get("chunk_id") or "").strip()
        if not chunk_id or chunk_id in seen:
            return
        seen.add(chunk_id)
        result.append(chunk)

    for chunk in primary_chunks:
        append_chunk(chunk)
        parent_chunk_id = str(chunk.get("parent_chunk_id") or "").strip()
        if not parent_chunk_id:
            continue
        parent = load_if_needed(parent_chunk_id)
        append_chunk(parent)
        sibling_ids = list((parent or {}).get("child_chunk_ids") or []) if isinstance(parent, dict) else []
        sibling_count = 0
        for sibling_id in sibling_ids:
            sibling = load_if_needed(str(sibling_id))
            if sibling is None or str(sibling.get("chunk_id") or "") == str(chunk.get("chunk_id") or ""):
                continue
            append_chunk(sibling)
            sibling_count += 1
            if sibling_count >= 2:
                break
    return result


def _public_course_answer_lines(
    *,
    chunks: list[dict[str, Any]],
    official_docs: list[dict[str, Any]],
    tour_items: list[dict[str, Any]],
    image_items: list[dict[str, Any]],
    official_doc_intent: bool,
    query: str,
    show_image_evidence: bool,
) -> list[str]:
    lines: list[str] = [f"{COURSE_RUNTIME_LABEL} 기준"]
    for index, chunk in enumerate(chunks, start=1):
        label = _public_chunk_label(chunk)
        summary = _public_course_text(_chunk_learning_summary(chunk, query=query), limit=360)
        lines.append(f"{index}. {label}: {summary} [{index}]")
    if official_doc_intent and official_docs:
        lines.extend(["", "공식문서 확인"])
        source_index = len(chunks) + 1
        for doc in official_docs[:2]:
            title = _public_course_text(doc.get("title") or "OpenShift 공식문서", limit=80)
            summary = _public_course_text(doc.get("snippet") or doc.get("match_reason") or "공식문서 근거입니다.", limit=180)
            lines.append(f"- {title}: {summary} [{source_index}]")
            source_index += 1
    if tour_items:
        lines.extend(["", "다음에 볼 단계"])
        for item in tour_items:
            role_label = "현재 단계" if str(item.get("role") or "") == "current" else "다음 단계"
            label = _clean_beginner_title(item.get("label") or item.get("title") or "")
            lines.append(f"- {role_label}: {label}")
    if show_image_evidence and image_items:
        lines.extend(["", "화면 증적"])
        for item in image_items[:3]:
            role_values = [str(item.get("instructional_role") or "image")]
            if isinstance(item.get("instructional_roles"), list):
                role_values.extend(str(role) for role in item.get("instructional_roles", []) if str(role).strip())
            roles = list(dict.fromkeys(role_values))
            state = f" / {item['state_signal']}" if item.get("state_signal") else ""
            summary = _public_course_text(item.get("summary") or "", limit=140)
            lines.append(f"- slide {item.get('slide_no') or 0}: {', '.join(roles)}{state} - {summary}")
    return lines


def _public_ops_learning_answer_lines(
    *,
    learning_chunks: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    official_docs: list[dict[str, Any]],
    tour_items: list[dict[str, Any]],
    image_items: list[dict[str, Any]],
    official_doc_intent: bool,
    show_image_evidence: bool,
) -> list[str]:
    lines: list[str] = [f"{COURSE_RUNTIME_LABEL} 기준"]
    citation_count = max(1, len(chunks))
    for learning_index, learning_chunk in enumerate(learning_chunks[:2], start=1):
        title = _public_course_text(learning_chunk.get("title") or "운영 학습 단계", limit=120)
        goal = _public_course_text(learning_chunk.get("learning_goal") or learning_chunk.get("beginner_explanation") or "", limit=260)
        lines.append(title)
        if goal:
            lines.append(goal)
        sequence = learning_chunk.get("operational_sequence") if isinstance(learning_chunk.get("operational_sequence"), list) else []
        look_for = learning_chunk.get("what_to_look_for") if isinstance(learning_chunk.get("what_to_look_for"), list) else []
        source_index = min(learning_index, citation_count)
        for index, item in enumerate(sequence[:3], start=1):
            text = _public_course_text(item, limit=560)
            if text:
                lines.append(f"{index}. {text} [{source_index}]")
        if look_for:
            lines.append("")
            lines.append("확인할 것")
            for item in look_for[:4]:
                text = _public_course_text(item, limit=140)
                if text:
                    lines.append(f"- {text} [{source_index}]")
        normal_state = learning_chunk.get("normal_state") if isinstance(learning_chunk.get("normal_state"), list) else []
        failure_state = learning_chunk.get("failure_state") if isinstance(learning_chunk.get("failure_state"), list) else []
        if normal_state or failure_state:
            lines.append("")
            lines.append("상태 기준")
            if normal_state:
                lines.append(f"- 정상/진행 상태: {', '.join(_public_course_text(item, limit=60) for item in normal_state[:4] if _public_course_text(item, limit=60))}")
            if failure_state:
                lines.append(f"- 실패/주의 상태: {', '.join(_public_course_text(item, limit=60) for item in failure_state[:4] if _public_course_text(item, limit=60))}")
    if official_doc_intent and official_docs:
        lines.extend(["", "공식문서 확인"])
        source_index = len(chunks) + 1
        for doc in official_docs[:2]:
            title = _public_course_text(doc.get("title") or "OpenShift 공식문서", limit=80)
            summary = _public_course_text(doc.get("snippet") or doc.get("match_reason") or "공식문서 근거입니다.", limit=180)
            lines.append(f"- {title}: {summary} [{source_index}]")
            source_index += 1
    if tour_items:
        lines.extend(["", "다음에 볼 단계"])
        for item in tour_items:
            role_label = "현재 단계" if str(item.get("role") or "") == "current" else "다음 단계"
            label = _public_course_text(item.get("label") or item.get("title") or "", limit=120)
            if label:
                lines.append(f"- {role_label}: {label}")
    if show_image_evidence and image_items:
        lines.extend(["", "화면 증적"])
        for item in image_items[:3]:
            state = f" / {item['state_signal']}" if item.get("state_signal") else ""
            summary = _public_course_text(item.get("summary") or "", limit=140)
            lines.append(f"- slide {item.get('slide_no') or 0}: {item.get('instructional_role') or 'image'}{state} - {summary}")
    return [line for line in lines if str(line).strip()]


def _public_ops_guide_answer_lines(
    *,
    step: dict[str, Any],
    chunks: list[dict[str, Any]],
    official_docs: list[dict[str, Any]],
    tour_items: list[dict[str, Any]],
    image_items: list[dict[str, Any]],
    official_doc_intent: bool,
    show_image_evidence: bool,
) -> list[str]:
    lines: list[str] = [f"{COURSE_RUNTIME_LABEL} 기준"]
    title = _public_course_text(step.get("card_text") or step.get("user_query") or "운영 학습 단계", limit=120)
    objective = _public_course_text(step.get("learning_objective") or "", limit=240)
    lines.append(title)
    if objective:
        lines.append(objective)
        lines.append("")
    outline = step.get("answer_outline") if isinstance(step.get("answer_outline"), list) else []
    citation_count = max(1, len(chunks))
    for index, item in enumerate(outline, start=1):
        source_index = min(index, citation_count)
        text = _public_course_text(item, limit=260)
        if text:
            lines.append(f"{index}. {text} [{source_index}]")
    if not outline:
        for index, chunk in enumerate(chunks, start=1):
            label = _public_chunk_label(chunk)
            summary = _public_course_text(_chunk_learning_summary(chunk), limit=300)
            lines.append(f"{index}. {label}: {summary} [{index}]")
    if chunks:
        lines.extend(["", "근거에서 확인되는 연결"])
        for index, chunk in enumerate(chunks[:3], start=1):
            detail = _public_course_text(_chunk_grounded_detail(chunk), limit=360)
            if detail:
                lines.append(f"- {detail} [{index}]")
    if official_doc_intent and official_docs:
        lines.extend(["", "공식문서 확인"])
        source_index = len(chunks) + 1
        for doc in official_docs[:2]:
            title = _public_course_text(doc.get("title") or "OpenShift 공식문서", limit=80)
            summary = _public_course_text(doc.get("snippet") or doc.get("match_reason") or "공식문서 근거입니다.", limit=180)
            lines.append(f"- {title}: {summary} [{source_index}]")
            source_index += 1
    if tour_items:
        lines.extend(["", "다음에 볼 단계"])
        for item in tour_items:
            role_label = "현재 단계" if str(item.get("role") or "") == "current" else "다음 단계"
            label = _clean_beginner_title(item.get("label") or item.get("title") or "")
            lines.append(f"- {role_label}: {label}")
    if show_image_evidence and image_items:
        lines.extend(["", "화면 증적"])
        for item in image_items[:3]:
            state = f" / {item['state_signal']}" if item.get("state_signal") else ""
            summary = _public_course_text(item.get("summary") or "", limit=140)
            lines.append(f"- slide {item.get('slide_no') or 0}: {item.get('instructional_role') or 'image'}{state} - {summary}")
    return lines


def _course_chat_payload(root_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("message") or "").strip()
    if not query:
        raise ValueError("message is required")
    stage_id = str(payload.get("stage_id") or "").strip() or _infer_stage_id_from_query(query)
    guide_id = str(payload.get("guide_id") or "").strip()
    step_id = str(payload.get("step_id") or "").strip()
    chunk_ids = payload.get("chunk_ids") if isinstance(payload.get("chunk_ids"), list) else []
    settings = load_settings(root_dir)
    course_hits: list[dict[str, Any]] = []
    official_hits: list[dict[str, Any]] = []

    explicit_chunk_ids = [str(item).strip() for item in chunk_ids if str(item).strip()]
    normalized_query = _normalize_query(query)
    official_doc_intent = _is_official_doc_intent(query)
    image_evidence_terms = [
        "image",
        "screen",
        "status",
        "state",
        "log",
        "metric",
        "table",
        "이미지",
        "화면",
        "상태",
        "증적",
        "로그",
        "메트릭",
        "표",
        "차트",
    ]
    image_evidence_terms.extend(["이미지", "화면", "상태", "증적", "로그", "메트릭", "표", "차트"])
    has_query_identifiers = bool(_query_identifiers(query)) or bool(re.match(r"^\s*\d+\b", query))
    learning_ranked = [] if explicit_chunk_ids or has_query_identifiers else _search_ops_learning_chunks(
        root_dir,
        query=query,
        stage_id=stage_id,
        guide_id=guide_id,
        step_id=step_id,
        limit=4,
    )
    if not learning_ranked and not explicit_chunk_ids and not has_query_identifiers:
        try:
            local_by_id = {str(row.get("learning_chunk_id") or ""): row for row in _load_ops_learning_chunks(root_dir)}
            vector_learning_hits = search_ops_learning_chunks(settings, query=query, top_k=4)
            for hit in vector_learning_hits:
                payload_hit = hit.get("payload") if isinstance(hit.get("payload"), dict) else {}
                candidate = local_by_id.get(str(hit.get("chunk_id") or "")) or payload_hit
                if not isinstance(candidate, dict):
                    continue
                if stage_id and str(candidate.get("stage_id") or "") != stage_id:
                    continue
                learning_ranked.append((float(hit.get("score") or 0.0), candidate))
        except Exception:  # noqa: BLE001
            learning_ranked = []
    learning_candidates = [row for _, row in learning_ranked]
    learning_chunks, learning_selector_meta, learning_selector_warning = _select_ops_learning_chunks_with_llm(
        settings=settings,
        query=query,
        candidates=learning_candidates,
    )
    if learning_chunks and not stage_id:
        stage_id = str(learning_chunks[0].get("stage_id") or "")
    resolved_guide = _resolve_ops_guide_step(
        root_dir,
        query=query,
        stage_id=stage_id,
        guide_id=guide_id,
        step_id=step_id,
    ) if not explicit_chunk_ids and not learning_chunks else None
    guide: dict[str, Any] | None = None
    guide_step: dict[str, Any] | None = None
    if resolved_guide is not None:
        guide, guide_step = resolved_guide
        stage_id = str(guide_step.get("stage_id") or guide.get("stage_id") or stage_id)
    route_like_query = _is_route_intent(query) and not any(term in normalized_query for term in image_evidence_terms)
    resolved_route_chunk = (
        _resolve_route_step_chunk(root_dir, query=query, stage_id=stage_id)
        if route_like_query and not explicit_chunk_ids and guide_step is None and not learning_chunks and not has_query_identifiers
        else None
    )
    route_start_ids = (
        _stage_start_chunk_ids(root_dir, stage_id)
        if route_like_query and not explicit_chunk_ids and guide_step is None and not learning_chunks and not resolved_route_chunk and not has_query_identifiers
        else []
    )
    ranked: list[tuple[float, dict[str, Any]]] = []
    if explicit_chunk_ids:
        for index, chunk_id in enumerate(explicit_chunk_ids, start=1):
            try:
                ranked.append((3000 - index, _load_chunk(root_dir, chunk_id)))
            except Exception:  # noqa: BLE001
                continue
    elif learning_chunks:
        seen_source_ids: set[str] = set()
        for learning_index, learning_chunk in enumerate(learning_chunks[:2], start=1):
            for source_index, chunk_id in enumerate(_learning_source_chunk_ids(learning_chunk), start=1):
                if chunk_id in seen_source_ids:
                    continue
                try:
                    ranked.append((3300 - (learning_index * 10) - source_index, _load_chunk(root_dir, chunk_id)))
                    seen_source_ids.add(chunk_id)
                except Exception:  # noqa: BLE001
                    continue
    elif guide_step is not None:
        for index, chunk_id in enumerate(_guide_step_source_chunk_ids(guide_step), start=1):
            try:
                ranked.append((3200 - index, _load_chunk(root_dir, chunk_id)))
            except Exception:  # noqa: BLE001
                continue
    elif resolved_route_chunk is not None:
        ranked = [(2800, resolved_route_chunk)]
    else:
        ranked = _search_chunks(
            root_dir,
            query=query,
            stage_id=stage_id,
            chunk_ids=route_start_ids,
            limit=3,
        )
    if route_start_ids:
        route_chunks: list[dict[str, Any]] = []
        for chunk_id in route_start_ids:
            try:
                route_chunks.append(_load_chunk(root_dir, chunk_id))
            except Exception:  # noqa: BLE001
                continue
        if route_chunks:
            ranked = [(2000 - index, chunk) for index, chunk in enumerate(route_chunks, start=1)]
    should_use_vector = (
        guide_step is None
        and (official_doc_intent
        or (
            not explicit_chunk_ids
            and not learning_chunks
            and not route_start_ids
            and resolved_route_chunk is None
            and (not ranked or ranked[0][0] < 36)
        ))
    )
    if should_use_vector:
        try:
            course_vector_hits, official_vector_hits = search_course_and_official(settings, query=query)
            for hit in course_vector_hits:
                chunk = _load_chunk(root_dir, str(hit.get("chunk_id") or ""))
                if stage_id and str(chunk.get("stage_id") or "").strip() != stage_id:
                    continue
                course_hits.append(chunk)
            official_hits = [
                {
                    "book_slug": str(hit.get("book_slug") or ""),
                    "section_id": str(hit.get("section_id") or ""),
                    "score": float(hit.get("score") or 0.0),
                    "trusted": float(hit.get("score") or 0.0) >= OFFICIAL_DOC_MIN_SCORE,
                    "title": str(hit.get("book_slug") or ""),
                    "section_title": str(hit.get("section") or ""),
                    "snippet": str(hit.get("text") or "")[:240],
                }
                for hit in official_vector_hits
                if float(hit.get("score") or 0.0) >= OFFICIAL_DOC_MIN_SCORE
            ]
        except Exception:  # noqa: BLE001
            course_hits = []
            official_hits = []
    if course_hits and not route_start_ids and not resolved_route_chunk and not explicit_chunk_ids and (not ranked or ranked[0][0] < 36):
        ranked = [(999 - index, chunk) for index, chunk in enumerate(course_hits[:3], start=1)]
    ranked_chunks = [chunk for _, chunk in ranked]

    response: dict[str, Any] = {
        "lane": "course",
        "mode": "course",
        "fallback_used": False,
        "preview_ready": False,
        "answer": "",
        "sources": [],
        "artifacts": [],
        "citation_map": {},
    }
    if learning_candidates:
        response["answer_generation"] = {
            "selector": learning_selector_meta,
            "candidate_learning_chunk_ids": [
                _ops_learning_chunk_id(candidate)
                for candidate in learning_candidates[:4]
                if _ops_learning_chunk_id(candidate)
            ],
            "selected_learning_chunk_ids": [
                _ops_learning_chunk_id(candidate)
                for candidate in learning_chunks
                if _ops_learning_chunk_id(candidate)
            ],
        }
    if learning_selector_warning:
        response.setdefault("warnings", []).append(learning_selector_warning)
    if not ranked_chunks:
        response["answer"] = "현재 코스 범위에서 직접 매칭되는 사업 산출물을 찾지 못했습니다. 더 구체적인 설계 ID, 테스트 ID, 단계명을 넣어 다시 질문해 주세요."
        return _attach_chat_response_fields(root_dir, response)

    official_docs = _collect_official_docs(ranked_chunks, official_hits) if official_doc_intent else []
    if official_doc_intent and not official_docs:
        official_docs = _stage_official_docs(root_dir, stage_id)
    tour_items = (
        _ops_learning_tour_items(root_dir, learning_chunks[0])
        if learning_chunks
        else _ops_guide_tour_items(root_dir, guide, guide_step) if guide is not None and guide_step is not None else _guided_tour_items(root_dir, ranked_chunks)
    )
    show_image_evidence = _is_image_evidence_intent(query)
    image_items = _image_evidence_items(ranked_chunks, query=query) if show_image_evidence else []

    answer_lines = [
        f"{COURSE_RUNTIME_LABEL} 기준",
        "질문과 직접 연결된 사내 산출물을 먼저 봅니다. 아래 항목은 PPT/PDF에서 추출된 청크와 원본 slide ref를 기준으로 한 근거입니다.",
    ]
    source_index = 1
    for chunk in ranked_chunks:
        chunk_id = str(chunk.get("chunk_id") or "")
        title = str(chunk.get("title") or chunk_id)
        stage = str(chunk.get("stage_id") or "")
        answer_lines.append(f"- [{chunk.get('native_id') or chunk_id}] {title}: {_chunk_learning_summary(chunk)} [{source_index}]")
        response["sources"].append(
            {
                "index": source_index,
                "source_kind": "project_artifact",
                "chunk_id": chunk_id,
                "stage_id": stage,
                "title": title,
                "section_title": stage,
                "viewer_path": f"/course/chunks/{chunk_id}",
                "source_path": str(chunk.get("source_pptx") or ""),
            }
        )
        source_index += 1
        response["artifacts"].append(
            {
                "kind": "course_chunk",
                "title": title,
                "chunk_id": chunk_id,
                "stage_id": stage,
                "items": [],
                "summary": _chunk_summary(chunk),
            }
        )
    answer_lines.append("")
    answer_lines.append("공식문서 확인")
    if official_docs:
        for doc in official_docs:
            answer_lines.append(f"- {doc['title']} {doc['section_title']}: {_short_text(doc.get('snippet') or doc.get('match_reason') or '공식문서 신뢰 기준을 통과한 참조입니다.', limit=220)} [{source_index}]")
            response["sources"].append(
                {
                    "index": source_index,
                    "source_kind": "official_doc",
                    "chunk_id": str(doc.get("section_id") or ""),
                    "stage_id": str(doc.get("stage_id") or ""),
                    "title": str(doc.get("title") or ""),
                    "section_title": str(doc.get("section_title") or ""),
                    "viewer_path": _official_doc_viewer_path(root_dir, doc),
                    "source_path": str(doc.get("book_slug") or doc.get("title") or ""),
                }
            )
            source_index += 1
    else:
        answer_lines.append("- 이 질문의 상위 후보에는 신뢰 기준을 넘긴 공식문서 매핑이 없습니다. 이 경우 답변은 실운영 산출물과 슬라이드 근거를 우선으로 봐야 합니다.")
    answer_lines.append("")
    answer_lines.append("다음 Guided Tour")
    if tour_items:
        for item in tour_items:
            label = "현재" if item["role"] == "current" else "다음"
            answer_lines.append(f"- {label}: {item['native_id'] or item['chunk_id']} {item['title']} ({item['reason']})")
    else:
        answer_lines.append("- 이 후보에는 tour_stop 메타데이터가 없어 다음 카드 추천을 확정하지 않았습니다.")
    if image_items:
        answer_lines.append("")
        answer_lines.append("이미지 증적")
        for item in image_items[:5]:
            role_values = [str(item.get("instructional_role") or "image")]
            role_values.extend(str(role) for role in item.get("instructional_roles", []) if str(role).strip())
            seen_roles: set[str] = set()
            roles = []
            for role in role_values:
                if role not in seen_roles:
                    seen_roles.add(role)
                    roles.append(role)
            role = ", ".join(roles)
            state = f" / {item['state_signal']}" if item.get("state_signal") else ""
            answer_lines.append(f"- {item['native_id']} slide {item['slide_no']}: {role}{state} - {_short_text(item.get('summary') or '', limit=140)}")

    if tour_items:
        response["artifacts"].append(
            {
                "kind": "course_guided_tour",
                "title": "Guided Tour",
                "items": tour_items,
            }
        )
    if image_items:
        response["artifacts"].append(
            {
                "kind": "course_image_evidence",
                "title": "Image Evidence",
                "summary": "질문 의도와 chunk context를 함께 반영해 대표 이미지를 고른 결과입니다.",
                "items": image_items,
            }
        )
    response["artifacts"].append(
        {
            "kind": "official_check",
            "title": "Official Check",
            "items": official_docs,
            "summary": "공식문서 신뢰 기준을 넘긴 참조만 포함합니다." if official_docs else "신뢰 기준을 넘긴 공식문서 매핑이 없습니다.",
        }
    )
    if learning_chunks:
        answer_lines = _public_ops_learning_answer_lines(
            learning_chunks=learning_chunks,
            chunks=ranked_chunks,
            official_docs=official_docs,
            tour_items=tour_items,
            image_items=image_items,
            official_doc_intent=official_doc_intent,
            show_image_evidence=show_image_evidence,
        )
    elif guide_step is not None:
        answer_lines = _public_ops_guide_answer_lines(
            step=guide_step,
            chunks=ranked_chunks,
            official_docs=official_docs,
            tour_items=tour_items,
            image_items=image_items,
            official_doc_intent=official_doc_intent,
            show_image_evidence=show_image_evidence,
        )
    else:
        answer_lines = _public_course_answer_lines(
            chunks=ranked_chunks,
            official_docs=official_docs,
            tour_items=tour_items,
            image_items=image_items,
            official_doc_intent=official_doc_intent,
            query=query,
            show_image_evidence=show_image_evidence,
        )
    draft_answer = "\n".join(answer_lines)
    response["answer"] = draft_answer
    try:
        rewritten_answer, rewrite_mode = _rewrite_course_answer_with_llm(
            settings=settings,
            query=query,
            draft_answer=draft_answer,
            sources=[source for source in response.get("sources", []) if isinstance(source, dict)],
            learning_chunks=learning_chunks,
            guide_step=guide_step,
        )
        if rewrite_mode:
            response["answer"] = rewritten_answer
            response["answer_rewrite"] = {"mode": rewrite_mode}
            if isinstance(response.get("answer_generation"), dict):
                response["answer_generation"]["mode"] = rewrite_mode
                response["answer_generation"]["fallback_used"] = False
        elif isinstance(response.get("answer_generation"), dict):
            response["answer_generation"]["mode"] = "deterministic"
            response["answer_generation"]["fallback_used"] = False
    except Exception as exc:  # noqa: BLE001
        response.setdefault("warnings", []).append(f"course answer LLM rewrite skipped: {exc}")
        if isinstance(response.get("answer_generation"), dict):
            response["answer_generation"]["mode"] = "deterministic"
            response["answer_generation"]["fallback_used"] = True
    response["preview_ready"] = bool(response["artifacts"])
    return _attach_chat_response_fields(root_dir, response)


def warmup_course_runtime(root_dir: Path) -> None:
    try:
        manifest = _load_manifest(root_dir)
    except Exception:  # noqa: BLE001
        return
    stages = manifest.get("stages") if isinstance(manifest.get("stages"), list) else []
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        learning_route = stage.get("learning_route") if isinstance(stage.get("learning_route"), dict) else {}
        start_refs = learning_route.get("start_here") if isinstance(learning_route.get("start_here"), list) else []
        for chunk_id in start_refs[:3]:
            try:
                _load_chunk(root_dir, str(chunk_id))
            except Exception:  # noqa: BLE001
                continue


def course_viewer_source_meta(root_dir: Path, viewer_path: str) -> dict[str, Any] | None:
    match = re.fullmatch(r"/course/chunks/([^/#?]+)(?:#slide-\d+)?", str(viewer_path or "").strip())
    if not match:
        return None
    try:
        chunk = _load_chunk(root_dir, match.group(1))
    except Exception:  # noqa: BLE001
        return None
    title = str(chunk.get("title") or chunk.get("chunk_id") or "")
    stage_id = str(chunk.get("stage_id") or "course")
    native_id = str(chunk.get("native_id") or "")
    return {
        "book_slug": stage_id,
        "book_title": COURSE_RUNTIME_LABEL,
        "anchor": str(chunk.get("chunk_id") or ""),
        "section": title,
        "section_path": [stage_id, native_id or title],
        "section_path_label": " > ".join(part for part in [stage_id, native_id or title] if part),
        "source_url": str(chunk.get("source_pptx") or ""),
        "viewer_path": viewer_path,
        "section_match_exact": True,
        "source_collection": "study_docs",
        "source_lane": "study_docs_course_runtime",
        "approval_state": str(chunk.get("review_status") or "course_reviewed"),
        "publication_state": "internal",
        "parser_backend": "course_chunk_v1",
        "boundary_truth": "internal_course_runtime",
        "runtime_truth_label": COURSE_RUNTIME_LABEL,
        "boundary_badge": "Internal Course",
    }


def _course_viewer_inline_style(root_dir: Path) -> str:
    base_css_path = root_dir / "src" / "play_book_studio" / "app" / "viewer_page.css"
    base_css = base_css_path.read_text(encoding="utf-8") if base_css_path.exists() else ""
    course_css = """
      .course-viewer-document .hero {
        padding-bottom: 22px;
        margin-bottom: 22px;
      }
      .course-viewer-document .eyebrow {
        color: #0f766e;
      }
      .course-viewer-document .summary {
        font-size: 1rem;
      }
      .course-viewer-document .meta-pill {
        border-color: #ccfbf1;
        background: #f0fdfa;
        color: #115e59;
      }
      .course-viewer-document .section-card {
        margin-bottom: 18px;
      }
      .course-viewer-document .reader-key-point-list {
        margin: 0;
        padding: 0;
        list-style: none;
        display: grid;
        gap: 10px;
      }
      .course-viewer-document .reader-key-point-list li {
        padding: 12px 14px;
        border: 1px solid #dbeafe;
        border-radius: 12px;
        background: #f8fbff;
        color: #1e293b;
        line-height: 1.65;
      }
      .course-viewer-document details.reader-details {
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        background: #ffffff;
        padding: 12px 14px;
      }
      .course-viewer-document details.reader-details > summary {
        cursor: pointer;
        color: #334155;
        font-weight: 700;
      }
      .course-viewer-document details.reader-details .details-body {
        margin-top: 14px;
      }
      .course-viewer-document .course-figure-grid {
        display: grid;
        gap: 14px;
      }
      .course-viewer-document .course-slide-actions a {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 32px;
        padding: 0 11px;
        border-radius: 999px;
        border: 1px solid #cbd5e1;
        background: #ffffff;
        color: #0f172a;
        font-size: 0.82rem;
        font-weight: 700;
        text-decoration: none;
      }
      .course-viewer-document .course-slide-actions a:hover {
        border-color: #38bdf8;
        background: #f0f9ff;
        color: #075985;
      }
      .course-viewer-document .course-slide-card {
        scroll-margin-top: 18px;
      }
      .course-viewer-document .course-slide-actions {
        display: flex;
        justify-content: space-between;
        gap: 10px;
        margin-bottom: 14px;
      }
      .course-viewer-document .course-slide-counter {
        color: #64748b;
        font-size: 0.86rem;
        font-weight: 700;
      }
      .course-viewer-document .course-figure-grid figure {
        margin: 0;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        background: #ffffff;
        padding: 12px;
      }
      .course-viewer-document .course-figure-grid img {
        width: 100%;
        height: auto;
        border-radius: 8px;
        border: 1px solid #edf2f7;
      }
      .course-viewer-document .course-figure-grid figcaption {
        margin-top: 8px;
        color: #64748b;
        font-size: 0.86rem;
        line-height: 1.55;
      }
      .course-viewer-document .source-trace-list {
        margin: 0;
        padding-left: 18px;
        color: #475569;
        line-height: 1.65;
      }
      .course-viewer-document .source-trace-list code {
        background: #f1f5f9;
        border: 1px solid #e2e8f0;
        border-radius: 6px;
        padding: 1px 5px;
      }
    """
    return f"{base_css}\n{course_css}"


def _course_anchor(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9가-힣_-]+", "-", str(value or "").strip()).strip("-")
    return normalized or fallback


def _course_section_html(*, anchor: str, title: str, body_html: str, meta: str = "") -> str:
    if not str(body_html or "").strip():
        return ""
    meta_html = f'<div class="section-meta">{html.escape(meta)}</div>' if meta.strip() else ""
    return """
      <section id="{anchor}" class="section-card section-level-2" data-semantic-role="course_section" data-section-level="2">
        <div class="section-header">
          {meta_html}
          <h2>{title}</h2>
        </div>
        <div class="section-body">{body_html}</div>
      </section>
    """.format(
        anchor=html.escape(anchor, quote=True),
        meta_html=meta_html,
        title=html.escape(title),
        body_html=body_html,
    ).strip()


def _course_render_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    command_html = _course_shell_commands_html(text)
    if command_html:
        return command_html
    return _course_render_normalized_section_html(text)


def _course_render_normalized_section_html(text: str) -> str:
    try:
        from play_book_studio.app.viewer_blocks import _render_normalized_section_html
    except ModuleNotFoundError:
        return f"<p>{html.escape(text)}</p>"
    return _render_normalized_section_html(text)


def _course_render_code_block_html(
    code: str,
    *,
    language: str,
    copy_text: str,
    wrap_hint: bool,
    overflow_hint: str,
    caption: str,
) -> str:
    try:
        from play_book_studio.app.viewer_blocks_rich import _render_code_block_html
    except ModuleNotFoundError:
        return f"<pre><code>{html.escape(code)}</code></pre>"
    return _render_code_block_html(
        code,
        language=language,
        copy_text=copy_text,
        wrap_hint=wrap_hint,
        overflow_hint=overflow_hint,
        caption=caption,
    )


def _course_shell_commands_html(text: str) -> str:
    command_pattern = re.compile(
        r"(?P<cmd>(?:^|\s)(?:#|\$|>)\s*(?:oc|kubectl|helm|curl|podman|docker|git|npm|python)\b.*?)(?=(?:\s(?:#|\$|>)\s*(?:oc|kubectl|helm|curl|podman|docker|git|npm|python)\b)|(?:\s+CLI\b)|$)",
        re.IGNORECASE | re.DOTALL,
    )
    commands = [
        re.sub(r"\s+", " ", match.group("cmd")).strip()
        for match in command_pattern.finditer(text)
        if str(match.group("cmd") or "").strip()
    ]
    if not commands:
        return ""
    narrative = command_pattern.sub(" ", text)
    narrative = re.sub(r"\bCLI\b", " ", narrative, flags=re.IGNORECASE)
    narrative = re.sub(r"\s+", " ", narrative).strip()
    fragments: list[str] = []
    if narrative:
        fragments.append(_course_render_normalized_section_html(narrative))
    fragments.append(
        _course_render_code_block_html(
            "\n".join(commands),
            language="shell",
            copy_text="\n".join(commands),
            wrap_hint=True,
            overflow_hint="toggle",
            caption="실행 명령",
        )
    )
    return "".join(fragment for fragment in fragments if fragment)


def _course_structured_sections_html(chunk: dict[str, Any]) -> str:
    structured = chunk.get("structured") if isinstance(chunk.get("structured"), dict) else {}
    metadata_keys = {"section_id", "layout_type", "section_name", "native_id", "chunk_id"}
    labels = {
        "method": "실행 방법",
        "expected": "기대 결과",
        "verification": "검증 명령 및 기준",
        "procedure": "절차",
        "result": "결과",
    }
    sections: list[str] = []
    for key, label in labels.items():
        if key in metadata_keys:
            continue
        value = structured.get(key)
        body_html = _course_render_text(value)
        if body_html:
            sections.append(
                _course_section_html(
                    anchor=f"structured-{html.escape(key, quote=True)}",
                    title=label,
                    meta="PPT에서 추출한 structured field",
                    body_html=body_html,
                )
            )
    for key, value in structured.items():
        if key in labels or key in metadata_keys or not str(value or "").strip():
            continue
        sections.append(
            _course_section_html(
                anchor=f"structured-{_course_anchor(str(key), 'field')}",
                title=str(key),
                meta="PPT에서 추출한 structured field",
                body_html=_course_render_text(value),
            )
        )
    return "\n".join(sections)


def _course_key_points(chunk: dict[str, Any], *, limit: int = 6) -> list[str]:
    perf_summary = _performance_learning_summary(chunk)
    if perf_summary:
        return [part.strip() for part in perf_summary.rstrip(".").split(". ") if part.strip()][:limit]
    body = re.sub(r"\s+", " ", str(chunk.get("body_md") or "")).strip()
    if not body:
        return []
    terms = [
        "병목",
        "개선",
        "정상",
        "확인",
        "Ready",
        "Running",
        "Succeeded",
        "Failed",
        "Error",
        "HPA",
        "DB",
        "Connection Pool",
        "Prometheus",
        "ArgoCD",
        "Service Mesh",
        "HAProxy",
    ]
    candidates: list[str] = []
    for term in terms:
        for match in re.finditer(re.escape(term), body, flags=re.IGNORECASE):
            start = max(0, match.start() - 90)
            end = min(len(body), match.end() + 150)
            fragment = body[start:end].strip(" ,.;:")
            fragment = re.sub(r"^\S{0,20}\s+", "", fragment) if start > 0 else fragment
            fragment = _short_text(fragment, limit=220)
            if fragment and fragment not in candidates:
                candidates.append(fragment)
            if len(candidates) >= limit:
                return candidates
    return [_short_text(body, limit=260)] if body else []


def _course_key_points_html(chunk: dict[str, Any]) -> str:
    points = _course_key_points(chunk)
    if not points:
        return ""
    items = "".join(f"<li>{html.escape(point)}</li>" for point in points)
    return f'<ul class="reader-key-point-list">{items}</ul>'


def _course_image_attachments_with_assets(chunk: dict[str, Any]) -> list[dict[str, Any]]:
    attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
    return [
        attachment
        for attachment in attachments
        if isinstance(attachment, dict) and str(attachment.get("asset_path") or "").strip()
    ]


def _course_relevant_slide_numbers(chunk: dict[str, Any], *, limit: int = 3) -> list[int]:
    query = " ".join(
        part
        for part in [
            str(chunk.get("title") or ""),
            _short_text(chunk.get("body_md") or "", limit=500),
        ]
        if part
    )
    profile = _image_query_profile(query)
    attachments = _course_image_attachments_with_assets(chunk)
    ranked: list[tuple[float, int, int]] = []
    serial = 0
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        slide_no = int(attachment.get("slide_no") or 0)
        if slide_no <= 0:
            continue
        score = _rank_image_attachment(attachment, profile=profile, query=query)
        if score < 0:
            continue
        serial += 1
        ranked.append((score, serial, slide_no))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    slides: list[int] = []
    for _, _, slide_no in ranked:
        if slide_no not in slides:
            slides.append(slide_no)
        if len(slides) >= limit:
            return slides
    return slides


def _course_attachments_for_slide(chunk: dict[str, Any], slide_no: int, *, limit: int = 4) -> list[dict[str, Any]]:
    attachments = _course_image_attachments_with_assets(chunk)
    exact = [
        attachment
        for attachment in attachments
        if int(attachment.get("slide_no") or 0) == int(slide_no)
    ]
    candidates = exact or attachments
    candidates = sorted(
        candidates,
        key=lambda item: (
            bool(item.get("exclude_from_default", False)),
            not bool(item.get("is_default_visible", True)),
            int(item.get("default_visible_order") or item.get("image_rank_order") or 9999),
            str(item.get("asset_id") or item.get("attachment_id") or ""),
        ),
    )
    return candidates[:limit]


def _course_slides_html(chunk: dict[str, Any], *, active_slide_no: int | None = None) -> str:
    raw_chunk_id = str(chunk.get("chunk_id") or "")
    slides = _course_relevant_slide_numbers(chunk)
    if not slides:
        return ""
    if active_slide_no not in slides:
        active_slide_no = slides[0]
    index = slides.index(int(active_slide_no))
    previous_slide = slides[index - 1] if index > 0 else slides[-1]
    next_slide = slides[index + 1] if index + 1 < len(slides) else slides[0]
    previous_link = f'<a href="/course/chunks/{html.escape(raw_chunk_id, quote=True)}#slide-{previous_slide}">이전 슬라이드</a>'
    next_link = f'<a href="/course/chunks/{html.escape(raw_chunk_id, quote=True)}#slide-{next_slide}">다음 슬라이드</a>'
    counter = f"{index + 1} / {len(slides)}"
    figures: list[str] = []
    for attachment in _course_attachments_for_slide(chunk, int(active_slide_no)):
        asset_path = str(attachment.get("asset_path") or "").strip()
        caption = _short_text(
            attachment.get("visual_summary") or attachment.get("ocr_text") or attachment.get("instructional_role") or "",
            limit=220,
        )
        figures.append(
            '<figure><img src="/api/v1/course/assets?path={asset_path}" alt="{alt}"><figcaption>{caption}</figcaption></figure>'.format(
                asset_path=html.escape(asset_path, quote=True),
                alt=html.escape(caption or f"Slide {int(active_slide_no)} evidence", quote=True),
                caption=html.escape(caption or f"Slide {int(active_slide_no)} evidence"),
            )
        )
    if not figures:
        return ""
    return """
      <div class="course-slide-actions">
        {previous_link}
        <span class="course-slide-counter">Slide {slide_no} · {counter}</span>
        {next_link}
      </div>
      <div class="course-figure-grid">
        {figures}
      </div>
    """.format(
        previous_link=previous_link,
        slide_no=int(active_slide_no),
        counter=html.escape(counter),
        next_link=next_link,
        figures="".join(figures),
    ).strip()


def _course_images_html(chunk: dict[str, Any]) -> str:
    attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
    figures: list[str] = []
    for attachment in attachments[:6]:
        if not isinstance(attachment, dict):
            continue
        asset_path = str(attachment.get("asset_path") or "").strip()
        if not asset_path:
            continue
        caption = _short_text(
            attachment.get("visual_summary") or attachment.get("ocr_text") or attachment.get("instructional_role") or "",
            limit=220,
        )
        slide_no = int(attachment.get("slide_no") or 0)
        role = str(attachment.get("instructional_role") or "").strip()
        caption_parts = [part for part in [f"Slide {slide_no}" if slide_no else "", role, caption] if part]
        figures.append(
            '<figure><img src="/api/v1/course/assets?path={asset_path}" alt="{alt}"><figcaption>{caption}</figcaption></figure>'.format(
                asset_path=html.escape(asset_path, quote=True),
                alt=html.escape(caption or "Course evidence", quote=True),
                caption=html.escape(" - ".join(caption_parts)),
            )
        )
    return '<div class="course-figure-grid">{}</div>'.format("".join(figures)) if figures else ""


def _course_source_trace_html(chunk: dict[str, Any]) -> str:
    source_pptx = str(chunk.get("source_pptx") or "").strip()
    slide_refs = chunk.get("slide_refs") if isinstance(chunk.get("slide_refs"), list) else []
    slide_numbers = [
        str(int(slide.get("slide_no") or 0))
        for slide in slide_refs
        if isinstance(slide, dict) and int(slide.get("slide_no") or 0) > 0
    ]
    items = [
        f"<li>원본 파일: <code>{html.escape(source_pptx)}</code></li>" if source_pptx else "",
        f"<li>슬라이드: {html.escape(', '.join(slide_numbers[:24]))}</li>" if slide_numbers else "",
        f"<li>내부 anchor: <code>{html.escape(str(chunk.get('native_id') or ''))}</code></li>" if str(chunk.get("native_id") or "").strip() else "",
        f"<li>chunk: <code>{html.escape(str(chunk.get('chunk_id') or ''))}</code></li>" if str(chunk.get("chunk_id") or "").strip() else "",
    ]
    return '<details class="reader-details"><summary>원본 추적 정보</summary><div class="details-body"><ul class="source-trace-list">{}</ul></div></details>'.format(
        "".join(item for item in items if item)
    )


def course_viewer_html(root_dir: Path, viewer_path: str) -> str | None:
    match = re.fullmatch(r"/course/chunks/([^/#?]+)(?:#slide-(\d+))?", str(viewer_path or "").strip())
    if not match:
        return None
    try:
        chunk = _load_chunk(root_dir, match.group(1))
    except Exception:  # noqa: BLE001
        return None
    title = html.escape(str(chunk.get("title") or chunk.get("chunk_id") or "Course chunk"))
    summary = "챗봇 답변의 근거가 된 원본 PPT 슬라이드를 확인합니다."
    body_html = _course_render_text(chunk.get("body_md"))
    active_slide_no = int(match.group(2)) if match.group(2) else None
    slides_html = _course_slides_html(chunk, active_slide_no=active_slide_no)
    sections = "\n".join(
        section
        for section in [
            _course_section_html(
                anchor="course-slides",
                title="슬라이드",
                meta="버튼으로 원본 PPT 페이지를 넘겨보세요",
                body_html=slides_html,
            ),
            _course_section_html(
                anchor="course-body",
                title="본문",
                meta="슬라이드가 없는 자료에서만 보조로 표시됩니다",
                body_html=f'<details class="reader-details"><summary>본문 보기</summary><div class="details-body">{body_html}</div></details>' if body_html and not slides_html else "",
            ),
        ]
        if section
    )
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    {_course_viewer_inline_style(root_dir)}
  </style>
</head>
<body class="is-embedded course-viewer-document">
  <main>
    <article class="study-document study-document-embedded">
      <section class="hero">
        <div class="hero-grid">
          <div class="hero-main">
            <div class="eyebrow">{COURSE_RUNTIME_LABEL}</div>
            <h1>{title}</h1>
            <p class="summary">{summary}</p>
          </div>
        </div>
      </section>
      <div class="section-list">
        {sections}
      </div>
    </article>
  </main>
</body>
</html>"""


def _stream_course_chat_result(handler: Any, result: dict[str, Any]) -> None:
    handler._start_ndjson_stream()
    handler._stream_event({"type": "stage", "stage": {"key": "course-retrieve", "label": "Retrieve", "detail": "Searching course chunks", "status": "running"}})
    handler._stream_event({"type": "stage", "stage": {"key": "course-retrieve", "label": "Retrieve", "detail": "Course candidates prepared", "status": "done"}})
    answer = str(result.get("answer") or "")
    if answer.strip():
        for part in re.split(r"(\n+)", answer):
            if part:
                handler._stream_event({"type": "answer_delta", "delta": part})
    handler._stream_event({"type": "result", "response": result})


def handle_course_get(handler: Any, path: str, query: str, *, root_dir: Path) -> bool:
    if path == "/api/v1/course/manifest":
        try:
            handler._send_json(_load_manifest(root_dir))
        except FileNotFoundError as exc:
            handler._send_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        return True

    if path == "/api/v1/course/search":
        params = parse_qs(query, keep_blank_values=False)
        q = _normalize_query(str((params.get("q") or [""])[0]))
        limit = max(1, min(50, int(str((params.get("limit") or ["20"])[0]).strip() or "20")))
        matches: list[dict[str, Any]] = []
        for chunk in _iter_chunks(root_dir):
            haystack = f"{chunk.get('title') or ''} {chunk.get('search_text') or chunk.get('body_md') or ''}".lower()
            if q and q not in haystack:
                continue
            matches.append(_chunk_summary(chunk))
            if len(matches) >= limit:
                break
        handler._send_json({"items": matches, "query": q})
        return True

    stage_prefix = "/api/v1/course/stages/"
    if path.startswith(stage_prefix):
        stage_id = path.removeprefix(stage_prefix).strip()
        try:
            manifest = _load_manifest(root_dir)
        except FileNotFoundError as exc:
            handler._send_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
            return True
        stage = next(
            (
                item
                for item in manifest.get("stages", [])
                if isinstance(item, dict) and str(item.get("stage_id") or "").strip() == stage_id
            ),
            None,
        )
        if stage is None:
            handler._send_json({"error": f"Course stage not found: {stage_id}"}, HTTPStatus.NOT_FOUND)
            return True
        chunk_refs = [str(item).strip() for item in (stage.get("chunk_refs") or []) if str(item).strip()]
        full_chunks: list[dict[str, Any]] = []
        for chunk_id in chunk_refs:
            try:
                full_chunks.append(_load_chunk(root_dir, chunk_id))
            except Exception:  # noqa: BLE001
                continue
        chunks = [_chunk_summary(chunk) for chunk in full_chunks]
        by_id = {str(chunk.get("chunk_id") or ""): chunk for chunk in full_chunks}
        learning_route = stage.get("learning_route") if isinstance(stage.get("learning_route"), dict) else {}
        start_ids = learning_route.get("start_here") if isinstance(learning_route.get("start_here"), list) else []
        then_ids = learning_route.get("then_open") if isinstance(learning_route.get("then_open"), list) else []
        start_cards = [
            _guided_card_for_chunk(by_id[chunk_id], role="start_here")
            for chunk_id in [str(item) for item in start_ids if str(item).strip()]
            if chunk_id in by_id
        ]
        then_cards = [
            _guided_card_for_chunk(by_id[chunk_id], role="then_open")
            for chunk_id in [str(item) for item in then_ids if str(item).strip()]
            if chunk_id in by_id
        ]
        official_cards = [
            _guided_card_for_chunk(chunk, role="official_check")
            for chunk in full_chunks
            if _trusted_official_docs(chunk.get("related_official_docs"))
        ][:6]
        ops_cards = _ops_guided_cards_for_stage(root_dir, stage_id)
        handler._send_json(
            {
                **stage,
                "chunks": chunks,
                "guided_cards": {
                    "start_here": ops_cards["start_here"] or start_cards,
                    "then_open": ops_cards["then_open"] or then_cards,
                    "official_check": official_cards,
                },
            }
        )
        return True

    chunk_prefix = "/api/v1/course/chunks/"
    if path.startswith(chunk_prefix):
        chunk_id = path.removeprefix(chunk_prefix).strip()
        try:
            handler._send_json(_load_chunk(root_dir, chunk_id))
        except ValueError as exc:
            handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except FileNotFoundError as exc:
            handler._send_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        return True

    if path == "/api/v1/course/assets":
        params = parse_qs(query, keep_blank_values=False)
        asset_path_raw = str((params.get("path") or [""])[0]).strip()
        try:
            asset_path = _resolve_course_path(root_dir, asset_path_raw)
        except ValueError as exc:
            handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return True
        assets_root = (_course_root(root_dir) / "assets").resolve()
        if not asset_path_raw or not _is_relative_to(asset_path, assets_root):
            handler._send_json({"error": "Course asset path must be under data/course_pbs/assets"}, HTTPStatus.BAD_REQUEST)
            return True
        if asset_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            handler._send_json({"error": "Course asset must be an image"}, HTTPStatus.BAD_REQUEST)
            return True
        if not asset_path.exists() or not asset_path.is_file():
            handler._send_json({"error": "Course asset not found"}, HTTPStatus.NOT_FOUND)
            return True
        body, content_type = _course_asset_payload(asset_path)
        handler._send_bytes(body, content_type=content_type)
        return True

    slide_prefix = "/api/v1/course/slides/"
    if path.startswith(slide_prefix):
        remainder = path.removeprefix(slide_prefix)
        if "/" not in remainder:
            handler._send_json({"error": "chunk_id and slide number are required"}, HTTPStatus.BAD_REQUEST)
            return True
        chunk_id, slide_fragment = remainder.split("/", 1)
        try:
            chunk_id = _validate_chunk_id(chunk_id)
            slide_no = int(slide_fragment.split(".", 1)[0])
        except ValueError as exc:
            handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return True
        try:
            chunk = _load_chunk(root_dir, chunk_id)
        except ValueError as exc:
            handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return True
        except FileNotFoundError as exc:
            handler._send_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
            return True
        attachment = next(iter(_course_attachments_for_slide(chunk, slide_no, limit=1)), None)
        try:
            asset_path = _resolve_course_path(root_dir, str((attachment or {}).get("asset_path") or "")) if attachment else None
        except ValueError as exc:
            handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return True
        if asset_path is not None and asset_path.suffix.lower() != ".png":
            handler._send_json({"error": "Course slide asset must be a PNG"}, HTTPStatus.BAD_REQUEST)
            return True
        if asset_path is None or not asset_path.exists():
            handler._send_json({"error": f"Slide PNG not found for {chunk_id}:{slide_no}"}, HTTPStatus.NOT_FOUND)
            return True
        handler._send_bytes(asset_path.read_bytes(), content_type="image/png")
        return True

    return False


def handle_course_post(handler: Any, path: str, payload: dict[str, Any], *, root_dir: Path, store: Any | None = None) -> bool:
    if path == "/api/v1/course/chat":
        try:
            result = _course_chat_payload(root_dir, payload)
            _persist_course_session_turn(store, payload, result)
            handler._send_json(result)
        except ValueError as exc:
            handler._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        return True
    if path == "/api/v1/course/chat/stream":
        try:
            result = _course_chat_payload(root_dir, payload)
            _persist_course_session_turn(store, payload, result)
        except ValueError as exc:
            handler._start_ndjson_stream()
            handler._stream_event({"type": "error", "status_code": 400, "message": str(exc)})
            return True
        _stream_course_chat_result(handler, result)
        return True
    return False


__all__ = ["handle_course_get", "handle_course_post"]
