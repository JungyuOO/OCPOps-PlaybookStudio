"""Studio starter question payloads derived from runtime manifests."""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from play_book_studio.config.corpus_paths import (
    OCP420_REPO_WIDE_SOURCE_MANIFEST_PATH,
    OCP420_SOURCE_FIRST_FULL_REBUILD_MANIFEST_PATH,
    OPS_LEARNING_CHUNKS_PATH,
    OPS_LEARNING_GUIDES_PATH,
)
from play_book_studio.config.settings import load_settings
from play_book_studio.db.official_documents import load_official_manifest_entries


@dataclass(frozen=True)
class StarterCategoryRule:
    key: str
    label: str
    description: str
    patterns: tuple[str, ...]


STARTER_CATEGORY_RULES: tuple[StarterCategoryRule, ...] = (
    StarterCategoryRule("install", "Install", "클러스터 설치와 Day-1 경로", ("install", "installation", "day-1", "cluster installation")),
    StarterCategoryRule("day2", "Day-2", "운영 전환과 후속 구성", ("day-2", "day 2", "postinstall", "post-install", "post installation", "day two")),
    StarterCategoryRule("operations", "Operations", "일상 운영과 변경 관리", ("machine config", "operator", "control plane", "node", "configuration", "operations")),
    StarterCategoryRule("storage", "Storage", "스토리지, 백업, 복구", ("storage", "backup", "restore", "etcd", "registry", "image")),
    StarterCategoryRule("observability", "Observability", "모니터링과 진단", ("monitor", "observab", "alert", "logging", "telemetry")),
    StarterCategoryRule("security", "Security", "권한, 인증, 보안 운영", ("security", "auth", "authorization", "rbac", "certificate", "compliance")),
    StarterCategoryRule("networking", "Networking", "네트워크와 연결 경로", ("network", "ingress", "egress", "dns", "route")),
    StarterCategoryRule("troubleshooting", "Troubleshooting", "문제 해결과 복구 경로", ("troubleshoot", "issue", "failure", "debug", "problem")),
)

STARTER_GROUPS = (
    {"key": "faq", "title": "자주 묻는 질문", "description": "공식 문서 기반 시작 질문"},
    {"key": "learning", "title": "단계별 학습 질문", "description": "OCP를 처음 익히는 흐름"},
    {"key": "operations", "title": "실운영 문서 질문", "description": "KMSC 운영 문서 기반 질문"},
)

LEARNING_TARGET_BOOK_SLUGS: dict[str, str] = {
    "install": "installation_overview",
    "day2": "postinstallation_configuration",
    "operations": "machine_configuration",
    "storage": "etcd",
    "observability": "monitoring",
    "security": "security_and_compliance",
    "networking": "networking_overview",
    "troubleshooting": "validation_and_troubleshooting",
}


def _safe_read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return payload if isinstance(payload, dict) else {}


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:  # noqa: BLE001
        return rows
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _stable_sample(items: list[dict[str, Any]], *, count: int, seed: str) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        key = str(item.get("question") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    rng = random.Random(seed)
    rng.shuffle(unique)
    return unique[:count]


def _starter_question(
    *,
    lane: str,
    question: str,
    route_kind: str,
    source: str,
    learning_index: int | None = None,
    category_key: str = "",
    category_label: str = "",
    target_book_slug: str = "",
    target_title: str = "",
    target_viewer_path: str = "",
    learning_path_id: str = "",
    learning_step_id: str = "",
    lab_task_id: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "lane": lane,
        "question": question,
        "route_kind": route_kind,
        "source": source,
    }
    if learning_index is not None:
        payload["learning_index"] = learning_index
    if category_key:
        payload["category_key"] = category_key
    if category_label:
        payload["category_label"] = category_label
    if target_book_slug:
        payload["target_book_slug"] = target_book_slug
    if target_title:
        payload["target_title"] = target_title
    if target_viewer_path:
        payload["target_viewer_path"] = target_viewer_path
    if learning_path_id:
        payload["learning_path_id"] = learning_path_id
    if learning_step_id:
        payload["learning_step_id"] = learning_step_id
    if lab_task_id:
        payload["lab_task_id"] = lab_task_id
    return payload


def _official_faq_questions(root_dir: Path) -> list[dict[str, Any]]:
    settings = load_settings(root_dir)
    database_url = settings.database_url.strip()
    if database_url:
        return _official_faq_questions_from_db(database_url)

    return _official_faq_questions_from_entries(
        _manifest_entries(root_dir),
        source="official.source_manifest",
    )


def _official_faq_questions_from_entries(entries: list[dict[str, Any]], *, source: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for rule in STARTER_CATEGORY_RULES:
        entry = _best_entry_for_category(entries, rule)
        if not entry:
            continue
        title = _clean_title(str(entry.get("title") or rule.label))
        book_slug = str(entry.get("book_slug") or "").strip()
        candidates.append(
            _starter_question(
                lane="faq",
                question=_official_faq_query(rule, title),
                route_kind="official",
                source=source,
                category_key=rule.key,
                category_label=rule.label,
                target_book_slug=book_slug,
                target_title=title,
                target_viewer_path=str(entry.get("viewer_path") or ""),
            )
        )
    return candidates


def _manifest_entries(root_dir: Path) -> list[dict[str, Any]]:
    settings = load_settings(root_dir)
    database_url = settings.database_url.strip()
    if database_url:
        return _official_manifest_entries_from_db(database_url)

    for path in (
        root_dir / OCP420_REPO_WIDE_SOURCE_MANIFEST_PATH,
        root_dir / OCP420_SOURCE_FIRST_FULL_REBUILD_MANIFEST_PATH,
    ):
        payload = _safe_read_json(path)
        entries = payload.get("entries")
        if isinstance(entries, list) and entries:
            return [entry for entry in entries if isinstance(entry, dict)]
    return []


def _official_manifest_entries_from_db(database_url: str) -> list[dict[str, Any]]:
    return load_official_manifest_entries(database_url)


def _official_faq_questions_from_db(database_url: str) -> list[dict[str, Any]]:
    chunk_questions = _chunk_candidate_questions_from_db(
        database_url,
        source_scope="official_docs",
        lane="faq",
        route_kind="official",
        source_label="postgres.document_chunks",
        limit=24,
    )
    if chunk_questions:
        return chunk_questions
    questions = _official_faq_questions_from_entries(
        _official_manifest_entries_from_db(database_url),
        source="postgres.official_docs",
    )
    if questions:
        return questions
    return [
        _starter_question(
            lane="faq",
            question="OpenShift 문제를 공식 문서 기준으로 진단할 때 어떤 문서와 확인 명령부터 보면 돼?",
            route_kind="official",
            source="postgres.official_docs",
        )
    ]


def _chunk_candidate_questions_from_db(
    database_url: str,
    *,
    source_scope: str,
    lane: str,
    route_kind: str,
    source_label: str,
    limit: int,
) -> list[dict[str, Any]]:
    try:
        import psycopg
    except Exception:  # noqa: BLE001
        return []

    try:
        with psycopg.connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        c.id::text AS chunk_id,
                        c.starter_question_candidates,
                        c.followup_question_candidates,
                        c.chunk_role,
                        c.heading_title,
                        c.section_path,
                        c.source_anchor,
                        c.repository_id::text AS repository_id,
                        c.source_scope,
                        c.ordinal,
                        m.book_slug,
                        m.viewer_path,
                        m.source_url,
                        m.category_key
                    FROM document_chunks c
                    CROSS JOIN LATERAL (
                        SELECT
                            c.metadata ->> 'book_slug' AS book_slug,
                            c.metadata ->> 'viewer_path' AS viewer_path,
                            c.metadata ->> 'source_url' AS source_url,
                            c.metadata ->> 'category_key' AS category_key
                    ) m
                    WHERE c.source_scope = %s
                        AND c.navigation_only = false
                        AND jsonb_array_length(c.starter_question_candidates) > 0
                    ORDER BY
                        CASE c.chunk_role WHEN 'parent' THEN 0 ELSE 1 END,
                        c.ordinal ASC
                    LIMIT %s
                    """,
                    (source_scope, int(limit)),
                )
                rows = cursor.fetchall()
                columns = [item.name for item in cursor.description]
    except Exception:  # noqa: BLE001
        return []

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        item = dict(zip(columns, row, strict=True))
        questions = _coerce_question_list(item.get("starter_question_candidates"))
        for question in questions:
            cleaned = _clean_title(question)
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            section_path = item.get("section_path") if isinstance(item.get("section_path"), list) else []
            candidates.append(
                _starter_question(
                    lane=lane,
                    question=cleaned,
                    route_kind=route_kind,
                    source=source_label,
                    category_key=str(item.get("category_key") or ""),
                    target_book_slug=str(item.get("book_slug") or ""),
                    target_viewer_path=str(item.get("viewer_path") or ""),
                    target_anchor=str(item.get("source_anchor") or ""),
                    target_title=_clean_title(
                        str(item.get("heading_title") or (section_path[-1] if section_path else ""))
                    ),
                )
            )
    return candidates


def _coerce_question_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return [value.strip()]
        if isinstance(loaded, list):
            return [str(item).strip() for item in loaded if str(item).strip()]
    return []


def _official_faq_query(rule: StarterCategoryRule, title: str) -> str:
    return _compose_beginner_question(
        lane="official",
        title=title,
        goal=rule.description,
        terms=list(rule.patterns),
    )

def _entry_haystack(entry: dict[str, Any]) -> str:
    values: list[str] = []
    for key in ("book_slug", "title", "source_relative_path"):
        values.append(str(entry.get(key) or ""))
    for key in ("topic_path", "section_family", "source_relative_paths"):
        value = entry.get(key)
        if isinstance(value, list):
            values.extend(str(item) for item in value)
    return " ".join(values).lower()


def _best_entry_for_category(entries: list[dict[str, Any]], rule: StarterCategoryRule) -> dict[str, Any] | None:
    best: tuple[int, dict[str, Any]] | None = None
    for entry in entries:
        haystack = _entry_haystack(entry)
        score = sum(1 for pattern in rule.patterns if pattern in haystack)
        if score <= 0:
            continue
        title = str(entry.get("title") or "").strip().lower()
        if not title or title in {"welcome", "legal notice", "release notes"}:
            score -= 2
        topic_path = entry.get("topic_path")
        if isinstance(topic_path, list) and topic_path:
            first_topic = str(topic_path[0] or "").lower()
            if any(pattern in first_topic for pattern in rule.patterns):
                score += 3
        if best is None or score > best[0]:
            best = (score, entry)
    return best[1] if best else None


def _clean_title(title: str) -> str:
    title = re.sub(r"\s+", " ", str(title or "").strip())
    return title or "공식 문서"


def _learning_questions(root_dir: Path) -> list[dict[str, Any]]:
    entries = _manifest_entries(root_dir)
    terminal_contexts = _learning_terminal_contexts(root_dir)
    questions: list[dict[str, Any]] = []
    for index, rule in enumerate(STARTER_CATEGORY_RULES):
        entry = _best_entry_for_category(entries, rule)
        title = _clean_title(str((entry or {}).get("title") or rule.label))
        book_slug = LEARNING_TARGET_BOOK_SLUGS.get(rule.key) or str((entry or {}).get("book_slug") or "").strip()
        viewer_path = str((entry or {}).get("viewer_path") or "").strip()
        question = _beginner_learning_question(rule, title)
        terminal_context = terminal_contexts[index] if index < len(terminal_contexts) else {}
        questions.append(
            _starter_question(
                lane="learning",
                question=question,
                route_kind="learning",
                source="ocp420_repo_wide_source_manifest",
                learning_index=index,
                category_key=rule.key,
                category_label=rule.label,
                target_book_slug=book_slug,
                target_title=title,
                target_viewer_path=viewer_path,
                learning_path_id=str(terminal_context.get("learning_path_id") or ""),
                learning_step_id=str(terminal_context.get("learning_step_id") or ""),
                lab_task_id=str(terminal_context.get("lab_task_id") or ""),
            )
        )
    return questions


def _beginner_learning_question(rule: StarterCategoryRule, title: str) -> str:
    return _compose_beginner_question(
        lane="learning",
        title=title,
        goal=rule.description,
        terms=list(rule.patterns),
    )


def _learning_terminal_contexts(root_dir: Path) -> list[dict[str, str]]:
    settings = load_settings(root_dir)
    database_url = settings.database_url.strip()
    if not database_url:
        return []
    try:
        import psycopg

        from play_book_studio.db.learning_repository import load_learning_path_catalog

        with psycopg.connect(database_url) as connection:
            catalog = load_learning_path_catalog(connection, workspace_slug="default", limit=1)
    except Exception:  # noqa: BLE001
        return []
    paths = catalog.get("paths") if isinstance(catalog, dict) else []
    if not isinstance(paths, list) or not paths:
        return []
    path = paths[0] if isinstance(paths[0], dict) else {}
    path_id = str(path.get("id") or "")
    steps = path.get("steps")
    if not isinstance(steps, list):
        return []
    contexts: list[dict[str, str]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        lab_task_id = ""
        lab_tasks = step.get("lab_tasks")
        if isinstance(lab_tasks, list):
            first_task = next((task for task in lab_tasks if isinstance(task, dict) and str(task.get("id") or "")), None)
            if isinstance(first_task, dict):
                lab_task_id = str(first_task.get("id") or "")
        contexts.append(
            {
                "learning_path_id": path_id,
                "learning_step_id": str(step.get("id") or ""),
                "lab_task_id": lab_task_id,
            }
        )
    return contexts


def _load_ops_learning_guides_payload(root_dir: Path) -> tuple[dict[str, Any], str]:
    settings = load_settings(root_dir)
    database_url = settings.database_url.strip()
    if database_url:
        try:
            import psycopg

            from play_book_studio.db.learning_repository import load_ops_learning_guides_payload

            with psycopg.connect(database_url) as connection:
                payload = load_ops_learning_guides_payload(connection, workspace_slug="default")
            return payload, "postgres.learning_paths"
        except Exception:  # noqa: BLE001
            return {"canonical_model": "ops_learning_guide_v1", "guides": []}, "postgres.learning_paths"
    return (
        _safe_read_json(root_dir / OPS_LEARNING_GUIDES_PATH),
        OPS_LEARNING_GUIDES_PATH.as_posix(),
    )


def _load_ops_learning_chunks_payload(root_dir: Path) -> tuple[list[dict[str, Any]], str]:
    settings = load_settings(root_dir)
    database_url = settings.database_url.strip()
    if database_url:
        try:
            import psycopg

            from play_book_studio.db.learning_repository import load_ops_learning_chunks_payload

            with psycopg.connect(database_url) as connection:
                rows = load_ops_learning_chunks_payload(connection, workspace_slug="default")
            return rows, "postgres.learning_steps"
        except Exception:  # noqa: BLE001
            return [], "postgres.learning_steps"
    return (
        _iter_jsonl(root_dir / OPS_LEARNING_CHUNKS_PATH),
        OPS_LEARNING_CHUNKS_PATH.as_posix(),
    )


def _ops_chunk_question(chunk: dict[str, Any]) -> str:
    title = _clean_title(str(chunk.get("title") or "운영 절차"))
    goal = _clean_title(str(chunk.get("learning_goal") or chunk.get("source_summary") or ""))
    terms = [
        _clean_title(str(item))
        for item in chunk.get("source_terms", [])
        if str(item).strip()
    ] if isinstance(chunk.get("source_terms"), list) else []
    return _compose_beginner_question(
        lane="operations",
        title=title,
        goal=goal,
        terms=terms,
    )


def _context_text(*parts: Any) -> str:
    return " ".join(
        " ".join(str(item) for item in part if str(item).strip())
        if isinstance(part, list)
        else str(part or "")
        for part in parts
    )


def _starter_topic_terms(*parts: Any) -> str:
    text = _context_text(*parts).lower()
    if any(token in text for token in ("postinstall", "post-install", "post installation", "day-2", "day 2", "day two")):
        return "postinstall"
    if any(token in text for token in ("troubleshoot", "issue", "failure", "debug", "problem", "장애", "문제", "오류")):
        return "troubleshooting"
    if any(token in text for token in ("install", "설치", "discovery", "bootstrap")):
        return "install"
    if any(token in text for token in ("node", "노드")):
        return "node"
    if any(token in text for token in ("namespace", "project", "네임스페이스", "프로젝트")):
        return "namespace"
    if any(token in text for token in ("pod", "파드", "container", "컨테이너")):
        return "pod"
    if any(token in text for token in ("service", "route", "ingress", "서비스", "라우트")):
        return "network"
    if any(token in text for token in ("secret", "configmap", "config", "시크릿", "컨피그")):
        return "config"
    if any(token in text for token in ("performance", "tps", "jmeter", "성능", "부하", "병목")):
        return "performance"
    if any(token in text for token in ("pipeline", "deploy", "배포", "파이프라인", "cicd", "ci/cd")):
        return "deploy"
    if any(token in text for token in ("storage", "pvc", "volume", "스토리지", "볼륨")):
        return "storage"
    if any(token in text for token in ("log", "metric", "monitor", "로그", "메트릭", "모니터")):
        return "observability"
    if any(token in text for token in ("권한", "rbac", "role", "auth", "user", "사용자")):
        return "security"
    return ""


def _beginner_subject_from_context(
    *,
    topic: str,
    title: str,
    goal: str = "",
    terms: list[str] | None = None,
) -> str:
    terms = terms or []
    text = _context_text(title, goal, terms).lower()
    if topic == "install":
        if "bootstrap" in text:
            return "설치 진행 상태"
        return "OCP 설치"
    if topic == "namespace":
        return "namespace"
    if topic == "pod":
        return "Pod 상태"
    if topic == "node":
        return "노드 상태"
    if topic == "network":
        if "overview" in text or "개요" in text:
            return "앱 접속 경로"
        if "route" in text or "라우트" in text:
            return "Service와 Route 연결"
        return "앱 접속 경로"
    if topic == "config":
        if "secret" in text or "시크릿" in text:
            return "Secret 설정"
        return "ConfigMap 설정"
    if topic == "performance":
        return "성능 테스트 결과"
    if topic == "deploy":
        return "앱 배포"
    if topic == "storage":
        return "PVC와 볼륨"
    if topic == "observability":
        if "metric" in text or "메트릭" in text:
            return "로그와 메트릭"
        return "로그와 이벤트"
    if topic == "security":
        return "권한 문제"
    if topic == "troubleshooting":
        return "문제 해결"
    if topic == "postinstall" or "postinstall" in text or "post-install" in text or "post installation" in text or "day-2" in text or "day 2" in text:
        return "설치 후 작업"
    cleaned_title = _clean_subject_title(title)
    if cleaned_title and cleaned_title.lower() not in {"operations", "troubleshooting", "day-2", "day 2"}:
        return cleaned_title
    for term in terms:
        cleaned = _clean_title(term)
        if cleaned:
            return cleaned
    return "처음 해야 할 일"


def _clean_subject_title(title: str) -> str:
    cleaned = _clean_title(title)
    for pattern in (
        r"\s*결과\s*확인하기$",
        r"\s*상태\s*검증부터\s*보기$",
        r"\s*검증부터\s*보기$",
        r"\s*먼저\s*보기$",
        r"\s*부터\s*보기$",
        r"\s*확인하기$",
        r"\s*보기$",
    ):
        cleaned = re.sub(pattern, "", cleaned).strip()
    return cleaned or _clean_title(title)


def _compose_beginner_question(
    *,
    lane: str,
    title: str,
    goal: str = "",
    terms: list[str] | None = None,
) -> str:
    terms = terms or []
    topic = _starter_topic_terms(title, goal, terms)
    subject = _beginner_subject_from_context(topic=topic, title=title, goal=goal, terms=terms)
    subject_topic = f"{subject}{_topic_particle(subject)}"
    text = _context_text(title, goal, terms).lower()

    if topic == "install":
        if "bootstrap" in text or "검증" in text or "validation" in text:
            return f"{subject}{_subject_particle(subject)} 정상인지 처음에 어디서 확인하면 돼?"
        return f"{subject_topic} 어떤 순서로 시작하면 돼?"
    if topic in {"namespace", "pod", "node", "network", "config", "storage", "observability", "security"}:
        if lane == "learning":
            return f"{subject_topic} 뭔지부터 알고 싶은데 어디서 확인하면 돼?"
        return f"{subject_topic} 처음에 어디서 확인하면 돼?"
    if topic == "performance":
        return f"{subject}{_object_particle(subject)} 받으면 목표와 조건은 어떻게 먼저 확인해?"
    if topic == "deploy":
        return f"{subject_topic} 처음에 어떤 순서로 진행하면 돼?"
    if topic == "postinstall" or "postinstall" in text or "post-install" in text or "post installation" in text or "day-2" in text or "day 2" in text:
        return f"{subject_topic} 무엇부터 이어서 진행하면 돼?"
    if topic == "troubleshooting" or "troubleshoot" in text or "failure" in text or "problem" in text or "장애" in text or "문제" in text:
        return f"{subject}{_subject_particle(subject)} 안 될 때 어디부터 확인하면 돼?"
    if lane == "learning":
        return f"{subject_topic} 처음에 어떤 순서로 배우면 돼?"
    return f"{subject_topic} 처음에 무엇부터 확인하면 돼?"


def _has_final_consonant(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    char = stripped[-1]
    code = ord(char)
    if 0xAC00 <= code <= 0xD7A3:
        return (code - 0xAC00) % 28 != 0
    return False


def _topic_particle(text: str) -> str:
    return "은" if _has_final_consonant(text) else "는"


def _subject_particle(text: str) -> str:
    return "이" if _has_final_consonant(text) else "가"


def _object_particle(text: str) -> str:
    return "을" if _has_final_consonant(text) else "를"

def _operations_questions(root_dir: Path) -> tuple[list[dict[str, Any]], str]:
    settings = load_settings(root_dir)
    database_url = settings.database_url.strip()
    if database_url:
        chunk_candidates = _chunk_candidate_questions_from_db(
            database_url,
            source_scope="study_docs",
            lane="operations",
            route_kind="course",
            source_label="postgres.study_docs_chunks",
            limit=24,
        )
        if chunk_candidates:
            return chunk_candidates, "postgres.study_docs_chunks"

    chunks, source_label = _load_ops_learning_chunks_payload(root_dir)
    candidates: list[dict[str, Any]] = []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        question = _ops_chunk_question(chunk).strip()
        if not question:
            continue
        candidates.append(
            _starter_question(
                lane="operations",
                question=question,
                route_kind="course",
                source=source_label,
                category_key=str(chunk.get("stage_id") or ""),
                category_label=str(chunk.get("course_title") or ""),
            )
        )
    return candidates, source_label


def build_studio_starter_questions(root_dir: Path, *, seed: str = "") -> dict[str, Any]:
    root = Path(root_dir)
    official = _stable_sample(_official_faq_questions(root), count=2, seed=f"{seed}:faq")
    operation_candidates, operations_source = _operations_questions(root)
    operations = _stable_sample(operation_candidates, count=2, seed=f"{seed}:operations")
    learning_sequence = _learning_questions(root)
    learning = _stable_sample(learning_sequence, count=2, seed=f"{seed}:learning")
    questions_by_group = {
        "faq": official,
        "learning": learning,
        "operations": operations,
    }
    return {
        "schema": "studio_starter_questions_v1",
        "groups": [
            {
                **group,
                "questions": questions_by_group.get(str(group["key"]), []),
            }
            for group in STARTER_GROUPS
        ],
        "learning_sequence": learning_sequence,
        "sources": {
            "faq": "official.source_manifest",
            "learning": "corpus/manifests/official/ocp420_repo_wide_source_manifest.json",
            "operations": operations_source,
        },
    }


def handle_studio_starter_questions(handler: Any, query: str, *, root_dir: Path) -> None:
    del query
    owner = getattr(handler, "_session_owner", lambda: None)()
    seed = getattr(owner, "owner_hash", "") or getattr(owner, "raw_owner", "") or ""
    handler._send_json(build_studio_starter_questions(root_dir, seed=seed))


__all__ = ["build_studio_starter_questions", "handle_studio_starter_questions"]
