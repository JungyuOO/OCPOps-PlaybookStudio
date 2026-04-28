from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from play_book_studio.app.course_api import _chunk_beginner_question, _clean_beginner_title, _course_chat_payload


CASE_SCHEMA = "course_chat_quality_case_v1"
REPORT_SCHEMA = "course_chat_quality_report_v1"
ANSWER_FALLBACK_MARKERS = [
    "직접 매칭되는 사업 산출물을 찾지 못했습니다",
    "더 구체적인 설계 ID",
    "다시 질문해 주세요",
]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_chunks(course_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted((course_dir / "chunks").glob("*.json")):
        payload = _read_json(path)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _load_manifest(course_dir: Path) -> dict[str, Any]:
    path = course_dir / "manifests" / "course_v1.json"
    return _read_json(path) if path.exists() else {}


def _short(value: Any, *, limit: int = 60) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit].rstrip()


def _normalize_text(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[_\-/]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _contains_text(haystack: str, needle: Any) -> bool:
    normalized_needle = _normalize_text(needle)
    if len(normalized_needle) < 2:
        return True
    return normalized_needle in _normalize_text(haystack)


def _terms_for_beginner_case(chunk: dict[str, Any], *, fallback: str = "") -> list[str]:
    terms: list[str] = []
    facets = chunk.get("facets") if isinstance(chunk.get("facets"), dict) else {}
    for key in ("technologies", "network_zones"):
        values = facets.get(key) if isinstance(facets.get(key), list) else []
        for value in values:
            text = str(value or "").strip()
            if text and text not in terms:
                terms.append(text)
            if len(terms) >= 4:
                return terms
    for token in re.findall(r"[A-Za-z][A-Za-z0-9+/#.-]{2,}|[가-힣]{2,}", f"{chunk.get('title') or ''} {chunk.get('search_text') or ''} {fallback}"):
        if re.fullmatch(r"[A-Z]{2,}(?:-[A-Z0-9]+)+", token.upper()):
            continue
        if token not in terms:
            terms.append(token)
        if len(terms) >= 4:
            break
    return terms


def _source_anchor(chunk: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "chunk_id": str(chunk.get("chunk_id") or ""),
        "native_id": str(chunk.get("native_id") or ""),
        "hidden_doc_anchor": True,
        **extra,
    }


def _case(
    *,
    case_id: str,
    category: str,
    query: str,
    stage_id: str = "",
    expected_chunk_ids: list[str] | None = None,
    expected_artifact_kinds: list[str] | None = None,
    expected_image_roles: list[str] | None = None,
    expected_state_signals: list[str] | None = None,
    expected_terms: list[str] | None = None,
    source: dict[str, Any] | None = None,
    rationale: str = "",
) -> dict[str, Any]:
    return {
        "schema": CASE_SCHEMA,
        "id": case_id,
        "category": category,
        "query": query,
        "stage_id": stage_id,
        "expected_chunk_ids": expected_chunk_ids or [],
        "expected_artifact_kinds": expected_artifact_kinds or ["course_chunk"],
        "expected_image_roles": expected_image_roles or [],
        "expected_state_signals": expected_state_signals or [],
        "expected_terms": expected_terms or [],
        "source": source or {},
        "rationale": rationale,
    }


def _add_case(cases: list[dict[str, Any]], seen: set[str], case: dict[str, Any]) -> None:
    case_id = str(case.get("id") or "")
    query = str(case.get("query") or "").strip()
    if not case_id or case_id in seen or len(query) < 4:
        return
    seen.add(case_id)
    cases.append(case)


def generate_cases(course_dir: Path, *, target_count: int = 96) -> list[dict[str, Any]]:
    chunks = _load_chunks(course_dir)
    manifest = _load_manifest(course_dir)
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()

    chunks_by_stage: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk in chunks:
        chunks_by_stage[str(chunk.get("stage_id") or "")].append(chunk)
    title_counts_by_stage: dict[str, Counter[str]] = defaultdict(Counter)
    for stage_id, rows in chunks_by_stage.items():
        for chunk in rows:
            title_counts_by_stage[stage_id][_normalize_text(_clean_beginner_title(chunk.get("title")))] += 1

    for stage_id, rows in sorted(chunks_by_stage.items()):
        for chunk in rows:
            chunk_id = str(chunk.get("chunk_id") or "")
            native_id = str(chunk.get("native_id") or "")
            title = _short(chunk.get("title"), limit=44)
            if not chunk_id or not native_id or not title:
                continue
            _add_case(
                cases,
                seen,
                _case(
                    case_id=f"exact-{stage_id}-{len(cases)+1:03d}",
                    category="exact_anchor",
                    query=f"{native_id} {title} 설명해줘",
                    stage_id=stage_id,
                    expected_chunk_ids=[chunk_id],
                    expected_artifact_kinds=["course_chunk"],
                    expected_terms=[native_id],
                    source={"chunk_id": chunk_id, "native_id": native_id},
                    rationale="native_id and title are present in the source chunk.",
                ),
            )
            break

    for stage in manifest.get("stages", []) if isinstance(manifest.get("stages"), list) else []:
        if not isinstance(stage, dict):
            continue
        stage_id = str(stage.get("stage_id") or "")
        title = _short(stage.get("title") or stage_id)
        if not stage_id:
            continue
        expected = [str(item) for item in (stage.get("learning_route") or {}).get("start_here", []) if str(item).strip()][:1]
        _add_case(
            cases,
            seen,
            _case(
                case_id=f"stage-route-{stage_id}",
                category="guided_stage_route",
                query=f"{title} 단계는 어디부터 보면 돼?",
                stage_id=stage_id,
                expected_chunk_ids=expected,
                expected_artifact_kinds=["course_guided_tour"],
                expected_terms=[stage_id],
                source={"stage_id": stage_id},
                rationale="stage manifest has guided learning route metadata.",
            ),
        )

    official_added = 0
    for chunk in chunks:
        docs = chunk.get("related_official_docs") if isinstance(chunk.get("related_official_docs"), list) else []
        if not docs:
            continue
        chunk_id = str(chunk.get("chunk_id") or "")
        stage_id = str(chunk.get("stage_id") or "")
        native_id = str(chunk.get("native_id") or "")
        title = _short(chunk.get("title"), limit=44)
        _add_case(
            cases,
            seen,
            _case(
                case_id=f"official-{official_added+1:03d}",
                category="official_mapping",
                query=f"{native_id or title} 공식문서 기준도 같이 알려줘",
                stage_id=stage_id,
                expected_chunk_ids=[chunk_id],
                expected_artifact_kinds=["course_chunk", "official_check"],
                expected_terms=[native_id or title],
                source={"chunk_id": chunk_id, "native_id": native_id, "official_count": len(docs)},
                rationale="chunk has trusted related_official_docs.",
            ),
        )
        official_added += 1
        if official_added >= 18:
            break

    state_limits = {"Running": 10, "Ready": 6, "Succeeded": 6, "Failed": 10, "CrashLoopBackOff": 10, "Error": 8, "Waiting": 5}
    state_counts: Counter[str] = Counter()
    role_limits = {
        "failure_state": 10,
        "expected_state_indicator": 8,
        "command_result_evidence": 12,
        "console_output": 8,
        "dashboard_metric": 5,
        "diagram": 6,
        "table": 6,
    }
    role_counts: Counter[str] = Counter()
    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id") or "")
        stage_id = str(chunk.get("stage_id") or "")
        chunk_kind = str(chunk.get("chunk_kind") or "")
        if "slide_detail" in chunk_kind:
            continue
        native_id = str(chunk.get("native_id") or "")
        title = _short(chunk.get("title"), limit=44)
        search_hint = _short(chunk.get("search_text") or chunk.get("body_md"), limit=96)
        attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
        for attachment in attachments:
            if not isinstance(attachment, dict) or attachment.get("is_default_visible") is False:
                continue
            asset_id = str(attachment.get("asset_id") or "")
            asset_path = str(attachment.get("asset_path") or "")
            role = str(attachment.get("instructional_role") or "")
            state = str(attachment.get("state_signal") or "")
            summary = _short(attachment.get("visual_summary") or attachment.get("ocr_text"), limit=72)
            if state and state in state_limits and state_counts[state] < state_limits[state]:
                _add_case(
                    cases,
                    seen,
                    _case(
                        case_id=f"image-state-{state.lower()}-{state_counts[state]+1:02d}",
                        category="image_state_evidence",
                        query=" ".join(
                            part
                            for part in [
                                native_id,
                                title,
                                f"{state} 상태 증적은 어떻게 확인해?",
                                summary,
                                search_hint,
                            ]
                            if part
                        ),
                        stage_id=stage_id,
                        expected_chunk_ids=[chunk_id],
                        expected_artifact_kinds=["course_chunk", "course_image_evidence"],
                        expected_image_roles=[role] if role else [],
                        expected_state_signals=[state],
                        expected_terms=[state],
                        source={"chunk_id": chunk_id, "asset_id": asset_id, "asset_path": asset_path, "summary": summary},
                        rationale="default-visible image attachment has a verified state_signal.",
                    ),
                )
                state_counts[state] += 1
            if role and role in role_limits and role_counts[role] < role_limits[role]:
                role_query = {
                    "failure_state": "실패 상태 이미지 증적 보여줘",
                    "expected_state_indicator": "정상 상태 확인 화면은 어떻게 보여?",
                    "command_result_evidence": "명령 실행 결과 증적을 보여줘",
                    "console_output": "터미널 로그 증적을 보여줘",
                    "dashboard_metric": "성능 메트릭 화면을 설명해줘",
                    "diagram": "구성도나 아키텍처 그림을 설명해줘",
                    "table": "표 형태 결과를 설명해줘",
                }.get(role, "이미지 증적을 보여줘")
                summary_hint = summary[:48] if summary else ""
                _add_case(
                    cases,
                    seen,
                    _case(
                        case_id=f"image-role-{role}-{role_counts[role]+1:02d}",
                        category="image_role_evidence",
                        query=" ".join(part for part in [native_id, title, role_query, summary_hint, search_hint] if part),
                        stage_id=stage_id,
                        expected_chunk_ids=[chunk_id],
                        expected_artifact_kinds=["course_chunk", "course_image_evidence"],
                        expected_image_roles=[role],
                        expected_state_signals=[state] if state else [],
                        expected_terms=[],
                        source={"chunk_id": chunk_id, "asset_id": asset_id, "asset_path": asset_path, "summary": summary},
                        rationale="default-visible image attachment has the expected instructional_role.",
                    ),
                )
                role_counts[role] += 1
            if len(cases) >= target_count:
                return cases

    for stage in manifest.get("stages", []) if isinstance(manifest.get("stages"), list) else []:
        if len(cases) >= target_count:
            return cases[:target_count]
        if not isinstance(stage, dict):
            continue
        stage_id = str(stage.get("stage_id") or "")
        title = _short(stage.get("title") or stage_id)
        learning_route = stage.get("learning_route") if isinstance(stage.get("learning_route"), dict) else {}
        ordered_route_ids = [
            str(item)
            for key in ("start_here", "then_open")
            for item in (learning_route.get(key) if isinstance(learning_route.get(key), list) else [])
            if str(item).strip()
        ]
        if not stage_id or not ordered_route_ids:
            continue
        _add_case(
            cases,
            seen,
            _case(
                case_id=f"route-sequence-{stage_id}",
                category="guided_route_sequence",
                query=f"{title} 학습 순서를 처음부터 다음 단계까지 카드 순서로 안내해줘",
                stage_id=stage_id,
                expected_chunk_ids=ordered_route_ids[:1],
                expected_artifact_kinds=["course_guided_tour"],
                expected_terms=[stage_id],
                source={"stage_id": stage_id, "route_chunk_ids": ordered_route_ids[:5]},
                rationale="stage learning_route has an ordered start_here/then_open sequence.",
            ),
        )
        seen_route_labels: set[str] = set()
        for index, chunk_id in enumerate(ordered_route_ids[:5], start=1):
            chunk = next((row for row in chunks if str(row.get("chunk_id") or "") == chunk_id), None)
            if not chunk:
                continue
            tour_stop = chunk.get("tour_stop") if isinstance(chunk.get("tour_stop"), dict) else {}
            if not str(tour_stop.get("next_chunk_id") or "").strip():
                continue
            native_id = str(chunk.get("native_id") or "")
            chunk_title = _short(chunk.get("title"), limit=44)
            route_label = f"{native_id} {chunk_title}".strip() if native_id and not native_id.isdigit() else chunk_title
            normalized_route_label = _normalize_text(route_label)
            normalized_clean_label = _normalize_text(_clean_beginner_title(chunk.get("title")))
            if normalized_clean_label and title_counts_by_stage[stage_id][normalized_clean_label] > 1:
                continue
            if normalized_route_label in seen_route_labels:
                continue
            seen_route_labels.add(normalized_route_label)
            _add_case(
                cases,
                seen,
                _case(
                    case_id=f"route-step-{stage_id}-{index:02d}",
                    category="guided_route_step",
                    query=f"{title}에서 {route_label} 다음에 무엇을 보면 돼?",
                    stage_id=stage_id,
                    expected_chunk_ids=[chunk_id],
                    expected_artifact_kinds=["course_chunk", "course_guided_tour"],
                    expected_terms=[],
                    source={"stage_id": stage_id, "chunk_id": chunk_id, "route_index": index},
                    rationale="route step is listed in stage learning_route and should produce a next-step card.",
                ),
            )
            if len(cases) >= target_count:
                return cases[:target_count]

    official_expanded = 0
    official_broad_limit = min(80, max(0, target_count - len(cases)))
    for chunk in chunks:
        if len(cases) >= target_count:
            return cases[:target_count]
        if official_expanded >= official_broad_limit:
            break
        docs = chunk.get("related_official_docs") if isinstance(chunk.get("related_official_docs"), list) else []
        if not docs:
            continue
        chunk_id = str(chunk.get("chunk_id") or "")
        stage_id = str(chunk.get("stage_id") or "")
        native_id = str(chunk.get("native_id") or "")
        title = _short(chunk.get("title"), limit=44)
        search_hint = _short(chunk.get("search_text") or chunk.get("body_md"), limit=96)
        if not chunk_id or not (native_id or title):
            continue
        _add_case(
            cases,
            seen,
            _case(
                case_id=f"official-expanded-{official_expanded+1:03d}",
                category="official_mapping_broad",
                query=" ".join(
                    part
                    for part in [
                        title,
                        search_hint,
                        "사내 Study-docs 근거와 공식문서 기준을 비교해서 알려줘",
                    ]
                    if part
                ),
                stage_id=stage_id,
                expected_chunk_ids=[chunk_id],
                expected_artifact_kinds=["course_chunk", "official_check"],
                expected_terms=[],
                source={"chunk_id": chunk_id, "native_id": native_id, "official_count": len(docs)},
                rationale="chunk has trusted related_official_docs and extends official mapping coverage.",
            ),
        )
        official_expanded += 1

    beginner_added = 0
    beginner_limit = max(0, target_count - len(cases))
    chunks_by_id = {str(chunk.get("chunk_id") or ""): chunk for chunk in chunks}
    for stage in manifest.get("stages", []) if isinstance(manifest.get("stages"), list) else []:
        if len(cases) >= target_count or beginner_added >= beginner_limit:
            break
        if not isinstance(stage, dict):
            continue
        stage_id = str(stage.get("stage_id") or "")
        learning_route = stage.get("learning_route") if isinstance(stage.get("learning_route"), dict) else {}
        ordered_route_ids = [
            str(item)
            for key in ("start_here", "then_open")
            for item in (learning_route.get(key) if isinstance(learning_route.get(key), list) else [])
            if str(item).strip()
        ]
        stage_beginner_queries: set[str] = set()
        for route_index, chunk_id in enumerate(ordered_route_ids[:8], start=1):
            if len(cases) >= target_count or beginner_added >= beginner_limit:
                break
            chunk = chunks_by_id.get(chunk_id)
            if not chunk:
                continue
            tour_stop = chunk.get("tour_stop") if isinstance(chunk.get("tour_stop"), dict) else {}
            if not str(tour_stop.get("next_chunk_id") or "").strip():
                continue
            normalized_clean_label = _normalize_text(_clean_beginner_title(chunk.get("title")))
            if normalized_clean_label and title_counts_by_stage[stage_id][normalized_clean_label] > 1:
                continue
            step_query = _chunk_beginner_question(chunk, intent="next")
            concept_query = _chunk_beginner_question(chunk, intent="learn")
            if step_query in stage_beginner_queries and concept_query in stage_beginner_queries:
                continue
            stage_beginner_queries.update({step_query, concept_query})
            step_terms = _terms_for_beginner_case({"title": _clean_beginner_title(chunk.get("title")), "search_text": step_query}, fallback=stage_id)
            concept_terms = _terms_for_beginner_case({"title": _clean_beginner_title(chunk.get("title")), "search_text": concept_query}, fallback=stage_id)
            _add_case(
                cases,
                seen,
                _case(
                    case_id=f"beginner-step-{stage_id}-{route_index:02d}",
                    category="beginner_guided_step",
                    query=step_query,
                    stage_id=stage_id,
                    expected_chunk_ids=[chunk_id],
                    expected_artifact_kinds=["course_chunk", "course_guided_tour"],
                    expected_terms=step_terms[:3],
                    source=_source_anchor(chunk, route_index=route_index),
                    rationale="beginner-facing route question keeps the internal document anchor hidden in metadata.",
                ),
            )
            beginner_added += 1
            if len(cases) >= target_count or beginner_added >= beginner_limit:
                break
            _add_case(
                cases,
                seen,
                _case(
                    case_id=f"beginner-concept-{stage_id}-{route_index:02d}",
                    category="beginner_concept",
                    query=concept_query,
                    stage_id=stage_id,
                    expected_chunk_ids=[chunk_id],
                    expected_artifact_kinds=["course_chunk", "course_guided_tour"],
                    expected_terms=concept_terms[:3],
                    source=_source_anchor(chunk, route_index=route_index),
                    rationale="concept case validates natural beginner wording against hidden study-docs anchors.",
                ),
            )
            beginner_added += 1

    for chunk in chunks:
        if len(cases) >= target_count or beginner_added >= beginner_limit:
            break
        chunk_id = str(chunk.get("chunk_id") or "")
        stage_id = str(chunk.get("stage_id") or "")
        chunk_kind = str(chunk.get("chunk_kind") or "")
        if not chunk_id:
            continue
        if "slide_detail" in chunk_kind:
            continue
        normalized_clean_label = _normalize_text(_clean_beginner_title(chunk.get("title")))
        if normalized_clean_label and title_counts_by_stage[stage_id][normalized_clean_label] > 1:
            continue
        attachments = chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else []
        visible_attachments = [
            attachment
            for attachment in attachments
            if isinstance(attachment, dict)
            and not attachment.get("exclude_from_default")
            and str(attachment.get("instructional_role") or "") != "decorative_or_empty"
        ]
        role_pool = {
            str(attachment.get("instructional_role") or "")
            for attachment in visible_attachments
        }
        state_pool = {
            str(attachment.get("state_signal") or "")
            for attachment in visible_attachments
        }
        normal_roles = {"expected_state_indicator", "success_state", "progress_state", "command_result_evidence"}
        failure_roles = {"failure_state", "console_output"}
        failure_states = {"Failed", "Error", "CrashLoopBackOff", "Degraded"}
        normal_states = {"Running", "Ready", "Succeeded", "Available", "Progressing"}
        verification_states = sorted(
            {
                str(attachment.get("state_signal") or "")
                for attachment in visible_attachments
                if str(attachment.get("instructional_role") or "") in normal_roles
                and str(attachment.get("state_signal") or "") in normal_states
            }
        )
        troubleshooting_states = sorted(state for state in state_pool if state in failure_states)
        if normal_roles & role_pool:
            query = _chunk_beginner_question(chunk, intent="verify")
            _add_case(
                cases,
                seen,
                _case(
                    case_id=f"beginner-verification-{beginner_added+1:03d}",
                    category="beginner_verification",
                    query=query,
                    stage_id=stage_id,
                    expected_chunk_ids=[chunk_id],
                    expected_artifact_kinds=["course_chunk", "course_image_evidence"],
                    expected_image_roles=sorted(normal_roles & role_pool)[:2],
                    expected_state_signals=[],
                    expected_terms=_terms_for_beginner_case({"title": _clean_beginner_title(chunk.get("title")), "search_text": query})[:3],
                    source=_source_anchor(chunk),
                    rationale="beginner verification case checks that state screenshots remain usable as evidence.",
                ),
            )
            beginner_added += 1
        if len(cases) >= target_count or beginner_added >= beginner_limit:
            break
        if failure_roles & role_pool or failure_states & state_pool:
            query = _chunk_beginner_question(chunk, intent="troubleshooting")
            _add_case(
                cases,
                seen,
                _case(
                    case_id=f"beginner-troubleshooting-{beginner_added+1:03d}",
                    category="beginner_troubleshooting",
                    query=query,
                    stage_id=stage_id,
                    expected_chunk_ids=[chunk_id],
                    expected_artifact_kinds=["course_chunk", "course_image_evidence"],
                    expected_image_roles=sorted(failure_roles & role_pool)[:2],
                    expected_state_signals=[],
                    expected_terms=_terms_for_beginner_case({"title": _clean_beginner_title(chunk.get("title")), "search_text": query})[:3],
                    source=_source_anchor(chunk),
                    rationale="beginner troubleshooting case validates failure-state evidence without exposing internal IDs in the query.",
                ),
            )
            beginner_added += 1
        if len(cases) >= target_count or beginner_added >= beginner_limit:
            break
        performance_roles = {"dashboard_metric", "table", "console_output", "command_result_evidence"}
        if visible_attachments and (stage_id == "perf_test" or "dashboard_metric" in role_pool) and performance_roles & role_pool:
            query = _chunk_beginner_question(chunk, intent="performance")
            _add_case(
                cases,
                seen,
                _case(
                    case_id=f"beginner-performance-{beginner_added+1:03d}",
                    category="beginner_performance",
                    query=query,
                    stage_id=stage_id,
                    expected_chunk_ids=[chunk_id],
                    expected_artifact_kinds=["course_chunk", "course_image_evidence"],
                    expected_image_roles=["dashboard_metric"] if "dashboard_metric" in role_pool else [],
                    expected_terms=_terms_for_beginner_case({"title": _clean_beginner_title(chunk.get("title")), "search_text": query}, fallback="성능 병목")[:3],
                    source=_source_anchor(chunk),
                    rationale="beginner performance case maps natural bottleneck questions to hidden performance evidence.",
                ),
            )
            beginner_added += 1

    drilldown_added = 0
    for chunk in chunks:
        if len(cases) >= target_count:
            return cases[:target_count]
        chunk_id = str(chunk.get("chunk_id") or "")
        stage_id = str(chunk.get("stage_id") or "")
        native_id = str(chunk.get("native_id") or "")
        title = _short(chunk.get("title"), limit=44)
        if not chunk_id or not (native_id or title):
            continue
        _add_case(
            cases,
            seen,
            _case(
                case_id=f"chunk-drilldown-{drilldown_added+1:03d}",
                category="chunk_drilldown",
                query=f"{native_id or title} 항목을 교육자료 기준으로 요약하고 후속으로 볼 내용을 추천해줘",
                stage_id=stage_id,
                expected_chunk_ids=[chunk_id],
                expected_artifact_kinds=["course_chunk", "course_guided_tour"],
                expected_terms=[native_id or title],
                source={"chunk_id": chunk_id, "native_id": native_id},
                rationale="source chunk has a stable native_id/title and should support drilldown learning Q&A.",
            ),
        )
        drilldown_added += 1
    return cases[:target_count]


def validate_cases(cases: list[dict[str, Any]], course_dir: Path, *, root_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    chunks = _load_chunks(course_dir)
    chunk_by_id = {str(chunk.get("chunk_id") or ""): chunk for chunk in chunks}
    stage_ids = {str(chunk.get("stage_id") or "") for chunk in chunks}
    allowed_artifact_kinds = {"course_chunk", "course_guided_tour", "course_image_evidence", "official_check"}
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for case in cases:
        reasons: list[str] = []
        if case.get("schema") != CASE_SCHEMA:
            reasons.append("invalid_schema")
        case_id = str(case.get("id") or "")
        query = str(case.get("query") or "").strip()
        if not case_id or case_id in seen_ids:
            reasons.append("duplicate_or_missing_id")
        seen_ids.add(case_id)
        if len(query) < 4:
            reasons.append("query_too_short")
        stage_id = str(case.get("stage_id") or "")
        if stage_id and stage_id not in stage_ids:
            reasons.append("unknown_stage_id")
        expected_chunks = [str(item) for item in case.get("expected_chunk_ids", []) if str(item).strip()]
        if not expected_chunks and str(case.get("category") or "") != "guided_stage_route":
            reasons.append("missing_expected_chunk")
        expected_chunk_rows = [chunk_by_id[chunk_id] for chunk_id in expected_chunks if chunk_id in chunk_by_id]
        for chunk_id in expected_chunks:
            if chunk_id not in chunk_by_id:
                reasons.append(f"unknown_expected_chunk:{chunk_id}")
        source = case.get("source") if isinstance(case.get("source"), dict) else {}
        asset_path = str(source.get("asset_path") or "")
        if asset_path:
            resolved = (root_dir / asset_path).resolve()
            if not resolved.exists() or not resolved.is_file():
                reasons.append("asset_path_missing")
        asset_id = str(source.get("asset_id") or "")
        expected_artifact_kinds = [str(item) for item in case.get("expected_artifact_kinds", []) if str(item).strip()]
        if not expected_artifact_kinds:
            reasons.append("missing_expected_artifact_kinds")
        for kind in expected_artifact_kinds:
            if kind not in allowed_artifact_kinds:
                reasons.append(f"unknown_expected_artifact_kind:{kind}")
        if "official_check" in expected_artifact_kinds and expected_chunks:
            has_official_mapping = any(
                isinstance(chunk.get("related_official_docs"), list) and len(chunk.get("related_official_docs") or []) > 0
                for chunk in expected_chunk_rows
            )
            if not has_official_mapping and str(case.get("category") or "") != "guided_stage_route":
                reasons.append("expected_official_check_without_source_mapping")
        expected_roles = [str(item) for item in case.get("expected_image_roles", []) if str(item).strip()]
        expected_states = [str(item) for item in case.get("expected_state_signals", []) if str(item).strip()]
        if expected_roles or expected_states or asset_id:
            attachments = [
                attachment
                for chunk in expected_chunk_rows
                for attachment in (chunk.get("image_attachments") if isinstance(chunk.get("image_attachments"), list) else [])
                if isinstance(attachment, dict)
            ]
            if asset_id and not any(str(attachment.get("asset_id") or "") == asset_id for attachment in attachments):
                reasons.append("asset_id_not_in_expected_chunk")
            role_pool: set[str] = set()
            state_pool: set[str] = set()
            for attachment in attachments:
                role = str(attachment.get("instructional_role") or "")
                if role:
                    role_pool.add(role)
                roles = attachment.get("instructional_roles") if isinstance(attachment.get("instructional_roles"), list) else []
                role_pool.update(str(role) for role in roles if str(role).strip())
                state = str(attachment.get("state_signal") or "")
                if state:
                    state_pool.add(state)
            for role in expected_roles:
                if role not in role_pool:
                    reasons.append(f"expected_role_not_in_source_chunk:{role}")
            for state in expected_states:
                if state not in state_pool:
                    reasons.append(f"expected_state_not_in_source_chunk:{state}")
        if reasons:
            rejected.append({**case, "quality_status": "rejected", "quality_reasons": reasons})
        else:
            accepted.append({**case, "quality_status": "accepted", "quality_reasons": []})
    return accepted, rejected


def _artifact_kinds(response: dict[str, Any]) -> set[str]:
    return {str(item.get("kind") or "") for item in response.get("artifacts", []) if isinstance(item, dict)}


def _source_chunk_ids(response: dict[str, Any]) -> set[str]:
    return {str(item.get("chunk_id") or "") for item in response.get("sources", []) if isinstance(item, dict)}


def _image_items(response: dict[str, Any]) -> list[dict[str, Any]]:
    for artifact in response.get("artifacts", []):
        if isinstance(artifact, dict) and artifact.get("kind") == "course_image_evidence":
            return [item for item in artifact.get("items", []) if isinstance(item, dict)]
    return []


def _artifact_items(response: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    for artifact in response.get("artifacts", []):
        if isinstance(artifact, dict) and artifact.get("kind") == kind:
            return [item for item in artifact.get("items", []) if isinstance(item, dict)]
    return []


def _route_items(response: dict[str, Any]) -> list[dict[str, Any]]:
    return _artifact_items(response, "course_guided_tour")


def _official_items(response: dict[str, Any]) -> list[dict[str, Any]]:
    return _artifact_items(response, "official_check")


def _project_sources(response: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in response.get("sources", [])
        if isinstance(item, dict) and str(item.get("source_kind") or "") == "project_artifact"
    ]


def _official_sources(response: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in response.get("sources", [])
        if isinstance(item, dict) and str(item.get("source_kind") or "") == "official_doc"
    ]


def _item_role_set(item: dict[str, Any]) -> set[str]:
    roles = {str(item.get("instructional_role") or "")}
    source_roles = item.get("instructional_roles") if isinstance(item.get("instructional_roles"), list) else []
    roles.update(str(role) for role in source_roles if str(role).strip())
    return {role for role in roles if role}


def _route_chunk_ids(items: list[dict[str, Any]], role: str | None = None) -> list[str]:
    return [
        str(item.get("chunk_id") or "")
        for item in items
        if str(item.get("chunk_id") or "") and (role is None or str(item.get("role") or "") == role)
    ]


def _first_project_chunk_id(response: dict[str, Any]) -> str:
    sources = _project_sources(response)
    return str(sources[0].get("chunk_id") or "") if sources else ""


def _semantic_context_failures(
    case: dict[str, Any],
    response: dict[str, Any],
    *,
    source_ids: set[str],
    image_items: list[dict[str, Any]],
) -> list[str]:
    failures: list[str] = []
    category = str(case.get("category") or "")
    expected_chunks = [str(item) for item in case.get("expected_chunk_ids", []) if str(item).strip()]
    expected_chunk_set = set(expected_chunks)
    expected_kinds = {str(item) for item in case.get("expected_artifact_kinds", []) if str(item).strip()}
    project_sources = _project_sources(response)
    official_sources = _official_sources(response)
    route_items = _route_items(response)
    route_ids = _route_chunk_ids(route_items)
    official_items = _official_items(response)
    beginner_categories = {
        "beginner_guided_step",
        "beginner_concept",
        "beginner_verification",
        "beginner_troubleshooting",
        "beginner_performance",
    }

    if "course_chunk" in expected_kinds:
        if not project_sources:
            failures.append("semantic_missing_project_context")
        if expected_chunk_set and category in {"exact_anchor", "official_mapping"}:
            if _first_project_chunk_id(response) not in expected_chunk_set:
                failures.append("semantic_top_project_source_not_expected_chunk")
        elif expected_chunk_set and category == "guided_route_step":
            if not (expected_chunk_set & source_ids):
                failures.append("semantic_expected_chunk_missing_from_context")

    if "official_check" in expected_kinds and category in {"official_mapping", "official_mapping_broad"}:
        if not official_sources:
            failures.append("semantic_missing_official_context")
        if not official_items:
            failures.append("semantic_missing_official_card_items")
        if not project_sources or not official_sources:
            failures.append("semantic_missing_project_official_pair")

    if "course_guided_tour" in expected_kinds:
        current_ids = _route_chunk_ids(route_items, "current")
        next_ids = _route_chunk_ids(route_items, "next")
        if not route_items:
            failures.append("semantic_missing_guided_route_items")
        if category in {"guided_stage_route", "guided_route_sequence"}:
            route_chunk_ids = [
                str(item)
                for item in (case.get("source") if isinstance(case.get("source"), dict) else {}).get("route_chunk_ids", [])
                if str(item).strip()
            ]
            if category == "guided_route_sequence" and expected_chunks and expected_chunks[0] not in route_ids and expected_chunks[0] not in source_ids:
                failures.append("semantic_route_missing_start_chunk")
            if category == "guided_route_sequence" and route_chunk_ids:
                first_two_route_ids = [chunk_id for chunk_id in route_ids if chunk_id in set(route_chunk_ids[:3])][:2]
                if route_chunk_ids[0] not in first_two_route_ids:
                    failures.append("semantic_route_sequence_not_source_order")
            if not next_ids:
                failures.append("semantic_route_sequence_missing_next_step")
        if category == "guided_route_step":
            if expected_chunk_set and not (expected_chunk_set & set(current_ids)):
                failures.append("semantic_route_step_missing_current_chunk")
            if not next_ids:
                failures.append("semantic_route_step_missing_next_chunk")
            if expected_chunk_set and set(next_ids) <= expected_chunk_set:
                failures.append("semantic_route_step_next_repeats_current")
        if category in {"chunk_drilldown", "beginner_concept"} and not next_ids:
            failures.append("semantic_drilldown_missing_followup_card")

    expected_states = [str(item) for item in case.get("expected_state_signals", []) if str(item).strip()]
    if category in {"image_state_evidence", "beginner_verification", "beginner_troubleshooting"} and (category == "image_state_evidence" or expected_states):
        if not image_items:
            failures.append("semantic_missing_image_context")
        elif expected_states:
            top_states = {str(item.get("state_signal") or "") for item in image_items[:2]}
            if not (set(expected_states) & top_states):
                failures.append("semantic_top_image_state_not_query_state")

    expected_roles = [str(item) for item in case.get("expected_image_roles", []) if str(item).strip()]
    if category in {"image_role_evidence", "beginner_verification", "beginner_troubleshooting", "beginner_performance"} and (category == "image_role_evidence" or expected_roles):
        if not image_items:
            failures.append("semantic_missing_image_context")
        elif expected_roles:
            top_role_pool: set[str] = set()
            for item in image_items[:3]:
                top_role_pool.update(_item_role_set(item))
            if not (set(expected_roles) & top_role_pool):
                failures.append("semantic_top_images_do_not_match_query_role")

    if category == "chunk_drilldown" and expected_chunk_set and not project_sources:
        if not (expected_chunk_set & source_ids):
            failures.append("semantic_drilldown_missing_requested_chunk")

    return failures


def _answer_quality_failures(
    case: dict[str, Any],
    response: dict[str, Any],
    *,
    kinds: set[str],
    source_ids: set[str],
    image_items: list[dict[str, Any]],
) -> list[str]:
    answer = str(response.get("answer") or "").strip()
    failures: list[str] = []
    if len(answer) < 120:
        failures.append("answer_too_short")
    if any(marker in answer for marker in ANSWER_FALLBACK_MARKERS):
        failures.append("fallback_answer_text")

    expected_kinds = {str(item) for item in case.get("expected_artifact_kinds", []) if str(item).strip()}
    if "course_chunk" in expected_kinds:
        if not any(marker in answer for marker in ("실운영 Study-docs 기준", "Study-docs 기준", "원문 근거", "확인할 것")):
            failures.append("answer_missing_study_docs_section")
        project_sources = _project_sources(response)
        if not project_sources:
            failures.append("answer_missing_project_sources")

    if "official_check" in expected_kinds:
        if "공식문서 확인" not in answer:
            failures.append("answer_missing_official_section")
        if str(case.get("category") or "") == "official_mapping":
            if "신뢰 기준을 넘긴 공식문서 매핑이 없습니다" in answer:
                failures.append("answer_claims_no_official_mapping")
            official_sources = _official_sources(response)
            if not official_sources:
                failures.append("answer_missing_official_sources")

    if "course_guided_tour" in expected_kinds:
        if not any(marker in answer for marker in ("다음 Guided Tour", "다음에 볼 단계")):
            failures.append("answer_missing_guided_tour_section")
        if not any(marker in answer for marker in ("- 현재:", "- 다음:", "- 현재 단계:", "- 다음 단계:")):
            failures.append("answer_missing_guided_tour_step")

    if "course_image_evidence" in expected_kinds and str(case.get("category") or "") in {"image_state_evidence", "image_role_evidence", "beginner_verification", "beginner_troubleshooting"}:
        if not any(marker in answer for marker in ("이미지 증적", "화면 증적")):
            failures.append("answer_missing_image_evidence_section")
        if not image_items:
            failures.append("answer_missing_image_evidence_items")

    expected_chunks = {str(item) for item in case.get("expected_chunk_ids", []) if str(item).strip()}
    exact_chunk_categories = {"exact_anchor", "official_mapping"}
    if expected_chunks and str(case.get("category") or "") in exact_chunk_categories:
        matching_sources = [source for source in _project_sources(response) if str(source.get("chunk_id") or "") in expected_chunks]

    if str(case.get("category") or "") not in {"guided_stage_route", "beginner_guided_step", "beginner_concept", "beginner_verification", "beginner_troubleshooting", "beginner_performance"}:
        expected_terms = [
            str(item)
            for item in case.get("expected_terms", [])
            if str(item).strip() and not re.fullmatch(r"[A-Z]{2,}(?:-[A-Z0-9]+)+", str(item).strip().upper())
        ]
        if expected_terms and not any(_contains_text(answer, term) for term in expected_terms):
            failures.append("answer_missing_expected_term")

    expected_states = [str(item) for item in case.get("expected_state_signals", []) if str(item).strip()]
    if str(case.get("category") or "") == "image_state_evidence":
        for state in expected_states:
            if not _contains_text(answer, state):
                failures.append(f"answer_missing_state:{state}")

    expected_roles = [str(item) for item in case.get("expected_image_roles", []) if str(item).strip()]
    item_role_text = " ".join(str(item.get("instructional_role") or "") for item in image_items)
    for role in expected_roles if str(case.get("category") or "") == "image_role_evidence" else []:
        if not (_contains_text(answer, role) or _contains_text(item_role_text, role)):
            failures.append(f"answer_missing_image_role:{role}")

    return failures


def run_cases(cases: list[dict[str, Any]], *, root_dir: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for case in cases:
        response = _course_chat_payload(root_dir, {"message": case["query"], "stage_id": case.get("stage_id") or ""})
        kinds = _artifact_kinds(response)
        source_ids = _source_chunk_ids(response)
        image_items = _image_items(response)
        failures: list[str] = []
        for kind in case.get("expected_artifact_kinds", []):
            if kind == "course_image_evidence" and str(case.get("category") or "") == "beginner_performance":
                continue
            if kind not in kinds:
                failures.append(f"missing_artifact:{kind}")
        expected_chunks = [str(item) for item in case.get("expected_chunk_ids", []) if str(item).strip()]
        exact_chunk_categories = {"exact_anchor", "official_mapping"}
        if expected_chunks and str(case.get("category") or "") in exact_chunk_categories and not (set(expected_chunks) & source_ids):
            failures.append("expected_chunk_not_in_sources")
        expected_states = [str(item) for item in case.get("expected_state_signals", []) if str(item).strip()]
        if expected_states and str(case.get("category") or "") == "image_state_evidence":
            item_states = {str(item.get("state_signal") or "") for item in image_items}
            if not (set(expected_states) & item_states):
                failures.append("expected_state_not_in_image_evidence")
        expected_roles = [str(item) for item in case.get("expected_image_roles", []) if str(item).strip()]
        if expected_roles and str(case.get("category") or "") in {"image_role_evidence", "image_state_evidence"}:
            item_roles = {str(item.get("instructional_role") or "") for item in image_items}
            for item in image_items:
                roles = item.get("instructional_roles") if isinstance(item.get("instructional_roles"), list) else []
                item_roles.update(str(role) for role in roles if str(role).strip())
            if not (set(expected_roles) & item_roles):
                failures.append("expected_role_not_in_image_evidence")
        answer_failures = _answer_quality_failures(case, response, kinds=kinds, source_ids=source_ids, image_items=image_items)
        semantic_failures = _semantic_context_failures(case, response, source_ids=source_ids, image_items=image_items)
        failures.extend(answer_failures)
        failures.extend(semantic_failures)
        counts["passed" if not failures else "failed"] += 1
        counts[f"category:{case.get('category')}"] += 1
        counts["answer_quality_passed" if not answer_failures else "answer_quality_failed"] += 1
        counts["semantic_context_passed" if not semantic_failures else "semantic_context_failed"] += 1
        rows.append(
            {
                "id": case.get("id"),
                "category": case.get("category"),
                "passed": not failures,
                "failures": failures,
                "answer_quality_passed": not answer_failures,
                "semantic_context_passed": not semantic_failures,
                "semantic_failures": semantic_failures,
                "answer_char_count": len(str(response.get("answer") or "")),
                "answer_excerpt": _short(response.get("answer"), limit=180),
                "artifact_kinds": sorted(kinds),
                "source_chunk_ids": sorted(source_ids)[:8],
                "image_states": [str(item.get("state_signal") or "") for item in image_items[:5]],
                "image_roles": [str(item.get("instructional_role") or "") for item in image_items[:5]],
            }
        )
    total = len(rows)
    passed = int(counts.get("passed", 0))
    return {
        "schema": REPORT_SCHEMA,
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "counts": dict(counts),
        "failures": [row for row in rows if not row["passed"]],
        "results": rows,
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    path.write_text(f"{content}\n" if content else "", encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate and run quality-gated course chat QA cases.")
    parser.add_argument("--root-dir", type=Path, default=Path("."))
    parser.add_argument("--course-dir", type=Path, default=Path("data/course_pbs"))
    parser.add_argument("--cases-path", type=Path, default=Path("manifests/course_qa_cases.jsonl"))
    parser.add_argument("--accepted-path", type=Path, default=Path("manifests/course_qa_cases.accepted.jsonl"))
    parser.add_argument("--rejected-path", type=Path, default=Path("manifests/course_qa_cases.rejected.jsonl"))
    parser.add_argument("--report-path", type=Path, default=Path("data/course_pbs/manifests/course_qa_report.json"))
    parser.add_argument("--target-count", type=int, default=96)
    parser.add_argument("--min-accepted", type=int, default=None)
    parser.add_argument("--allow-rejected", action="store_true")
    parser.add_argument("--verbose-results", action="store_true")
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--run", action="store_true")
    return parser


def run_quality_eval(args: argparse.Namespace, *, default_root: Path | None = None) -> int:
    root_arg = getattr(args, "root_dir", None) or default_root or Path(".")
    root_dir = Path(root_arg).resolve()
    course_dir = (root_dir / args.course_dir).resolve() if not args.course_dir.is_absolute() else args.course_dir.resolve()
    cases_path = (root_dir / args.cases_path).resolve() if not args.cases_path.is_absolute() else args.cases_path.resolve()
    accepted_path = (root_dir / args.accepted_path).resolve() if not args.accepted_path.is_absolute() else args.accepted_path.resolve()
    rejected_path = (root_dir / args.rejected_path).resolve() if not args.rejected_path.is_absolute() else args.rejected_path.resolve()
    report_path = (root_dir / args.report_path).resolve() if not args.report_path.is_absolute() else args.report_path.resolve()

    cases = generate_cases(course_dir, target_count=max(1, int(args.target_count))) if args.generate else read_jsonl(cases_path)
    if args.generate:
        write_jsonl(cases_path, cases)
    accepted, rejected = validate_cases(cases, course_dir, root_dir=root_dir)
    write_jsonl(accepted_path, accepted)
    write_jsonl(rejected_path, rejected)

    report = {
        "schema": REPORT_SCHEMA,
        "generated": bool(args.generate),
        "case_count": len(cases),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "accepted_path": str(accepted_path),
        "rejected_path": str(rejected_path),
    }
    if args.run:
        report.update(run_cases(accepted, root_dir=root_dir))
    min_accepted = int(args.min_accepted) if args.min_accepted is not None else int(args.target_count)
    gate_failures: list[str] = []
    if len(accepted) < min_accepted:
        gate_failures.append(f"accepted_below_min:{len(accepted)}<{min_accepted}")
    if rejected and not bool(args.allow_rejected):
        gate_failures.append(f"rejected_cases_present:{len(rejected)}")
    if int(report.get("failed") or 0) > 0:
        gate_failures.append(f"runtime_failures_present:{report.get('failed')}")
    report["quality_gate"] = {
        "passed": not gate_failures,
        "failures": gate_failures,
        "min_accepted": min_accepted,
        "allow_rejected": bool(args.allow_rejected),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    console_report = report if bool(args.verbose_results) else {key: value for key, value in report.items() if key != "results"}
    print(json.dumps(console_report, ensure_ascii=False, indent=2))
    return 0 if report["quality_gate"]["passed"] else 1


def main() -> int:
    return run_quality_eval(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
