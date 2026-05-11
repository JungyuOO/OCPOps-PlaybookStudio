"""Studio starter question payloads derived from runtime manifests."""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from play_book_studio.config.corpus_paths import (
    ANSWER_EVAL_CASES_PATH,
    ANSWER_EVAL_REALWORLD_CASES_PATH,
    OCP420_REPO_WIDE_SOURCE_MANIFEST_PATH,
    OCP420_SOURCE_FIRST_FULL_REBUILD_MANIFEST_PATH,
    OPS_LEARNING_CHUNKS_PATH,
    OPS_LEARNING_GUIDES_PATH,
    PBS_CHAT_QUALITY_CASES_PATH,
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

    candidates: list[dict[str, Any]] = []
    entries_by_slug = {
        str(entry.get("book_slug") or "").strip(): entry
        for entry in _manifest_entries(root_dir)
        if str(entry.get("book_slug") or "").strip()
    }
    for path in (
        root_dir / PBS_CHAT_QUALITY_CASES_PATH,
        root_dir / ANSWER_EVAL_CASES_PATH,
        root_dir / ANSWER_EVAL_REALWORLD_CASES_PATH,
    ):
        for row in _iter_jsonl(path):
            query = str(row.get("query") or "").strip()
            query_type = str(row.get("query_type") or "").strip().lower()
            if not query:
                continue
            if query_type not in {"ops_command", "ops_procedure", "ops_troubleshooting"}:
                continue
            if bool(row.get("clarification_expected")) or bool(row.get("no_answer_expected")):
                continue
            expected_books = row.get("expected_book_slugs")
            if not isinstance(expected_books, list) or not expected_books:
                continue
            target_book_slug = str(expected_books[0] or "").strip()
            target_entry = entries_by_slug.get(target_book_slug, {})
            candidates.append(
                _starter_question(
                    lane="faq",
                    question=query,
                    route_kind="official",
                    source=path.name,
                    target_book_slug=target_book_slug,
                    target_title=str(target_entry.get("title") or target_book_slug.replace("_", " ").title()),
                    target_viewer_path=str(target_entry.get("viewer_path") or ""),
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
    entries = _official_manifest_entries_from_db(database_url)
    questions: list[dict[str, Any]] = []
    for rule in STARTER_CATEGORY_RULES:
        if rule.key not in {"day2", "operations", "storage", "security", "networking", "troubleshooting"}:
            continue
        entry = _best_entry_for_category(entries, rule)
        if not entry:
            continue
        title = _clean_title(str(entry.get("title") or rule.label))
        book_slug = str(entry.get("book_slug") or "").strip()
        questions.append(
            _starter_question(
                lane="faq",
                question=_official_faq_query(rule, title),
                route_kind="official",
                source="postgres.official_docs",
                category_key=rule.key,
                category_label=rule.label,
                target_book_slug=book_slug,
                target_title=title,
                target_viewer_path=str(entry.get("viewer_path") or ""),
            )
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


def _official_faq_query(rule: StarterCategoryRule, title: str) -> str:
    clean_title = _clean_title(title)
    templates = {
        "day2": "{title} 문서를 기준으로 설치 후 구성에서 먼저 확인할 설정과 명령어는 뭐야?",
        "operations": "{title} 문서를 기준으로 운영 상태를 볼 때 먼저 확인할 리소스와 명령어는 뭐야?",
        "storage": "{title} 문서를 기준으로 스토리지나 백업 문제를 확인할 때 어떤 상태값과 명령어부터 보면 돼?",
        "security": "{title} 문서를 기준으로 권한, 인증, 보안 설정에서 먼저 확인할 항목은 뭐야?",
        "networking": "{title} 문서를 기준으로 Route, Ingress, DNS 연결 문제를 어떤 순서로 보면 돼?",
        "troubleshooting": "{title} 문서를 기준으로 장애를 좁힐 때 먼저 확인할 증상, 로그, 명령어는 뭐야?",
    }
    template = templates.get(rule.key, "{title} 문서를 기준으로 먼저 확인할 항목과 명령어는 뭐야?")
    return template.format(title=clean_title)

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
        if rule.key == "install":
            question = f"OCP를 처음 시작할 때 {title} 문서는 무엇부터 이해하면 돼?"
        else:
            question = f"{rule.label} 단계에서는 {title} 기준으로 무엇을 순서대로 학습하면 돼?"
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
    if terms:
        return f"{title}에서 {', '.join(terms[:2])} 기준으로 먼저 확인할 것은 뭐야?"
    if goal:
        return f"{title}에서 {goal} 기준으로 먼저 확인할 것은 뭐야?"
    return f"{title}에서 먼저 확인할 운영 기준은 뭐야?"

def _operations_questions(root_dir: Path) -> tuple[list[dict[str, Any]], str]:
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
    learning = learning_sequence[:2]
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
            "faq": "corpus/manifests/eval/pbs_chat_quality_cases*.jsonl",
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
