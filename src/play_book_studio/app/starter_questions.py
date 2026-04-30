"""Studio starter question payloads derived from runtime manifests."""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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
    {"key": "faq", "title": "자주 묻는 질문", "description": "공식 문서 fast path"},
    {"key": "learning", "title": "학습용 단계별 질문", "description": "Install부터 순서대로"},
    {"key": "operations", "title": "실운영 질문", "description": "Study-docs 기준"},
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
    return payload


def _official_faq_questions(root_dir: Path) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    entries_by_slug = {
        str(entry.get("book_slug") or "").strip(): entry
        for entry in _manifest_entries(root_dir)
        if str(entry.get("book_slug") or "").strip()
    }
    for path in (
        root_dir / "manifests" / "pbs_chat_quality_cases.jsonl",
        root_dir / "manifests" / "answer_eval_cases.jsonl",
        root_dir / "manifests" / "answer_eval_realworld_cases.jsonl",
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
    for path in (
        root_dir / "manifests" / "ocp420_repo_wide_source_manifest.json",
        root_dir / "manifests" / "ocp420_source_first_full_rebuild_manifest.json",
    ):
        payload = _safe_read_json(path)
        entries = payload.get("entries")
        if isinstance(entries, list) and entries:
            return [entry for entry in entries if isinstance(entry, dict)]
    return []


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
            )
        )
    return questions


def _operations_questions(root_dir: Path) -> list[dict[str, Any]]:
    payload = _safe_read_json(root_dir / "data" / "course_pbs" / "manifests" / "ops_learning_guides_v1.json")
    guides = payload.get("guides")
    candidates: list[dict[str, Any]] = []
    if not isinstance(guides, list):
        return candidates
    for guide in guides:
        if not isinstance(guide, dict):
            continue
        steps = guide.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            query = str(step.get("user_query") or "").strip()
            if not query:
                continue
            candidates.append(
                _starter_question(
                    lane="operations",
                    question=query,
                    route_kind="course",
                    source="ops_learning_guides_v1",
                    category_key=str(guide.get("stage_id") or ""),
                    category_label=str(guide.get("title") or ""),
                )
            )
    return candidates


def build_studio_starter_questions(root_dir: Path, *, seed: str = "") -> dict[str, Any]:
    root = Path(root_dir)
    official = _stable_sample(_official_faq_questions(root), count=2, seed=f"{seed}:faq")
    operations = _stable_sample(_operations_questions(root), count=2, seed=f"{seed}:operations")
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
            "faq": "manifests/pbs_chat_quality_cases*.jsonl",
            "learning": "manifests/ocp420_repo_wide_source_manifest.json",
            "operations": "data/course_pbs/manifests/ops_learning_guides_v1.json",
        },
    }


def handle_studio_starter_questions(handler: Any, query: str, *, root_dir: Path) -> None:
    del query
    owner = getattr(handler, "_session_owner", lambda: None)()
    seed = getattr(owner, "owner_hash", "") or getattr(owner, "raw_owner", "") or ""
    handler._send_json(build_studio_starter_questions(root_dir, seed=seed))


__all__ = ["build_studio_starter_questions", "handle_studio_starter_questions"]
