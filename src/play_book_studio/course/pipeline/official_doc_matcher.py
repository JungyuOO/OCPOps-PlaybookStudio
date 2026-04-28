from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import requests

from play_book_studio.config.settings import load_settings
from play_book_studio.ingestion.embedding import EmbeddingClient

from .common import tokenize_korean_english

GENERIC_TOKENS = {
    "openshift",
    "container",
    "platform",
    "단계",
    "청크",
    "확인",
    "구성",
    "사용",
    "서비스",
    "테스트",
    "관리",
    "결과",
    "방법",
    "주요",
    "기술",
    "상세",
    "작업",
    "정보",
    "단계의",
    "service",
    "data",
    "api",
    "web",
    "ocp",
    "기본",
    "고급",
    "전체",
    "개요",
    "정의",
    "내부",
    "외부",
    "네트워크",
    "영역",
    "서버",
    "포트",
    "또는",
    "출력",
    "구성된",
    "설정",
    "발생",
    "따라",
    "시간",
}

STAGE_BOOK_PRIORS = {
    "architecture": {
        "architecture",
        "overview",
        "nodes",
        "networking_overview",
        "advanced_networking",
        "ingress_and_load_balancing",
        "storage",
        "monitoring",
        "logging",
        "operators",
        "registry",
        "machine_configuration",
    },
    "unit_test": {
        "nodes",
        "networking_overview",
        "ingress_and_load_balancing",
        "storage",
        "monitoring",
        "logging",
        "backup_and_restore",
        "etcd",
        "web_console",
        "cli_tools",
        "authentication_and_authorization",
        "registry",
    },
    "integration_test": {
        "networking_overview",
        "ingress_and_load_balancing",
        "advanced_networking",
        "operators",
        "web_console",
        "monitoring",
        "validation_and_troubleshooting",
    },
    "perf_test": {
        "monitoring",
        "observability_overview",
        "nodes",
        "logging",
        "networking_overview",
        "validation_and_troubleshooting",
    },
    "completion": {
        "overview",
        "architecture",
        "support",
        "installation_overview",
        "postinstallation_configuration",
        "validation_and_troubleshooting",
    },
}

TOPIC_BOOK_RULES = [
    (("etcd", "cluster-backup", "백업", "backup", "snapshot"), {"etcd", "backup_and_restore"}),
    (("haproxy", "ingress", "router", "route", "routes", "envoy", "istio", "gateway"), {"ingress_and_load_balancing", "networking_overview", "advanced_networking"}),
    (("odf", "storage", "pvc", "pv", "ceph", "nfs", "noobaa", "object"), {"storage"}),
    (("prometheus", "monitoring", "grafana", "alertmanager", "thanos", "metrics", "metric"), {"monitoring", "observability_overview"}),
    (("logging", "loki", "efk", "filebeat", "log"), {"logging", "observability_overview"}),
    (("quay", "registry", "image", "이미지"), {"registry", "images"}),
    (("tekton", "pipeline", "pipelines", "argocd", "gitops", "operator"), {"operators"}),
    (("node", "worker", "master", "control plane", "machineconfig", "mco"), {"nodes", "machine_management", "machine_configuration", "architecture"}),
    (("rbac", "rolebinding", "권한", "user", "사용자", "auth", "인증"), {"authentication_and_authorization"}),
    (("web console", "console", "cli", "oc "), {"web_console", "cli_tools"}),
    (("network", "ovn", "dmz", "mtu", "service network", "storage network", "mgmt"), {"networking_overview", "advanced_networking"}),
    (("install", "installation", "설치"), {"installation_overview", "installing_on_any_platform", "postinstallation_configuration"}),
]


def _meaningful_tokens(text: str) -> set[str]:
    tokens = set(tokenize_korean_english(text))
    return {
        token
        for token in tokens
        if token not in GENERIC_TOKENS
        and not token.isdigit()
        and not re.fullmatch(r"\d+(?:[./-]\d+)*\.?", token)
    }


def _topic_books_for_text(text: str, stage_id: str) -> set[str]:
    lowered = str(text or "").lower()
    books = set(STAGE_BOOK_PRIORS.get(stage_id, set()))
    for terms, targets in TOPIC_BOOK_RULES:
        if any(term in lowered for term in terms):
            books.update(targets)
    return books


def _iter_official_corpus_chunks(root_dir: Path) -> list[dict[str, Any]]:
    path = root_dir / "data" / "gold_corpus_ko" / "chunks.jsonl"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        text = str(payload.get("text") or "")
        book_slug = str(payload.get("book_slug") or "")
        book_title = str(payload.get("book_title") or book_slug)
        section_title = str(payload.get("section") or payload.get("chapter") or "")
        rows.append(
            {
                "book_slug": book_slug,
                "book_title": book_title,
                "section_id": str(payload.get("section_id") or payload.get("anchor_id") or ""),
                "heading": section_title,
                "snippet": re.sub(r"\s+", " ", text).strip()[:260],
                "viewer_path": str(payload.get("viewer_path") or ""),
                "chunk_type": str(payload.get("chunk_type") or ""),
                "ordinal": int(payload.get("ordinal") or 0),
                "token_set": _meaningful_tokens(f"{book_title} {section_title} {text}"),
            }
        )
    return rows


def _iter_official_sections(root_dir: Path) -> list[dict[str, Any]]:
    corpus_rows = _iter_official_corpus_chunks(root_dir)
    if corpus_rows:
        return corpus_rows
    rows: list[dict[str, Any]] = []
    playbooks_dir = root_dir / "data" / "gold_manualbook_ko" / "playbooks"
    for path in sorted(playbooks_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        title = str(payload.get("title") or path.stem)
        book_slug = str(payload.get("book_slug") or path.stem)
        sections = payload.get("sections") if isinstance(payload.get("sections"), list) else []
        for section in sections:
            if not isinstance(section, dict):
                continue
            heading = str(section.get("heading") or "")
            snippet = ""
            blocks = section.get("blocks") if isinstance(section.get("blocks"), list) else []
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                snippet = str(block.get("text") or block.get("caption") or block.get("code") or "").strip()
                if snippet:
                    break
            rows.append(
                {
                    "book_slug": book_slug,
                    "book_title": title,
                    "section_id": str(section.get("section_id") or ""),
                    "heading": heading,
                    "snippet": snippet[:240],
                    "viewer_path": str(section.get("viewer_path") or ""),
                    "token_set": _meaningful_tokens(f"{title} {heading} {snippet}"),
                }
            )
    return rows


def _query_official_qdrant(root_dir: Path, text: str, *, top_k: int) -> list[dict[str, Any]]:
    settings = load_settings(root_dir)
    client = EmbeddingClient(settings)
    vector = client.embed_texts([text])[0]
    response = requests.post(
        f"{settings.qdrant_url}/collections/{settings.qdrant_collection}/points/query",
        json={
            "query": vector,
            "limit": top_k,
            "with_payload": True,
            "with_vector": False,
        },
        timeout=max(settings.request_timeout_seconds, 30),
    )
    response.raise_for_status()
    result = response.json().get("result") or {}
    points = result.get("points") if isinstance(result, dict) else result
    matches: list[dict[str, Any]] = []
    for point in points or []:
        payload = point.get("payload") if isinstance(point, dict) else None
        if not isinstance(payload, dict):
            continue
        matches.append(
            {
                "book_slug": str(payload.get("book_slug") or ""),
                "section_id": str(payload.get("section_id") or ""),
                "score": round(float(point.get("score") or 0.0), 3),
                "snippet": str(payload.get("text") or "")[:240],
                "title": str(payload.get("book_title") or payload.get("book_slug") or ""),
                "section_title": str(payload.get("section") or ""),
                "viewer_path": str(payload.get("viewer_path") or ""),
                "match_reason": "vector similarity from official collection",
            }
        )
    return matches


def _lexical_official_matches(
    official_rows: list[dict[str, Any]],
    chunk: dict[str, Any],
    *,
    top_k: int,
    min_overlap: int,
    min_score: float,
) -> list[dict[str, Any]]:
    search_text = str(chunk.get("search_text") or chunk.get("body_md") or chunk.get("title") or "")
    stage_id = str(chunk.get("stage_id") or "")
    token_set = _meaningful_tokens(search_text)
    topic_books = _topic_books_for_text(search_text, stage_id)
    if not token_set and not topic_books:
        return []

    scored: list[tuple[float, int, dict[str, Any], list[str]]] = []
    for row in official_rows:
        book_slug = str(row.get("book_slug") or "")
        row_tokens = row.get("token_set") if isinstance(row.get("token_set"), set) else set()
        overlap = token_set & row_tokens
        stage_prior = book_slug in STAGE_BOOK_PRIORS.get(stage_id, set())
        topic_prior = book_slug in topic_books
        if len(overlap) < min_overlap:
            continue
        lexical = len(overlap) / max(min(len(token_set), 36), 1)
        score = min(0.56, 0.32 + lexical)
        reasons: list[str] = []
        if overlap:
            sample = ", ".join(sorted(overlap)[:6])
            reasons.append(f"shared terms: {sample}")
        if stage_prior:
            score += 0.03
            reasons.append(f"stage prior: {stage_id}->{book_slug}")
        if topic_prior:
            score += 0.1
            reasons.append(f"topic prior: {book_slug}")
        if len(overlap) >= 5:
            score += 0.05
        if row.get("chunk_type") in {"reference", "concept"} and int(row.get("ordinal") or 0) == 0:
            score += 0.02
        score = round(min(score, 0.84), 3)
        if score < min_score:
            continue
        scored.append((score, len(overlap), row, reasons))
    scored.sort(key=lambda item: (-item[0], -item[1], str(item[2].get("book_slug") or ""), str(item[2].get("section_id") or "")))

    matches: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for score, overlap_count, row, reasons in scored:
        key = (str(row.get("book_slug") or ""), str(row.get("section_id") or ""))
        if key in seen:
            continue
        seen.add(key)
        matches.append(
            {
                "book_slug": str(row.get("book_slug") or ""),
                "section_id": str(row.get("section_id") or ""),
                "score": score,
                "snippet": str(row.get("snippet") or ""),
                "title": str(row.get("book_title") or row.get("book_slug") or ""),
                "section_title": str(row.get("heading") or ""),
                "viewer_path": str(row.get("viewer_path") or ""),
                "match_reason": "; ".join([*reasons, f"lexical_overlap={overlap_count}"]),
            }
        )
        if len(matches) >= top_k:
            break
    return matches


def _merge_matches(*groups: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for group in groups:
        for match in group:
            key = (str(match.get("book_slug") or match.get("title") or ""), str(match.get("section_id") or ""))
            if not key[0] and not key[1]:
                continue
            existing = merged.get(key)
            if existing is None or float(match.get("score") or 0.0) > float(existing.get("score") or 0.0):
                merged[key] = dict(match)
    return sorted(merged.values(), key=lambda item: (-float(item.get("score") or 0.0), str(item.get("book_slug") or "")))[:top_k]


def match_official_docs(
    root_dir: Path,
    chunks: list[dict[str, Any]],
    *,
    top_k: int = 3,
    min_overlap: int = 2,
    min_score: float = 0.65,
) -> list[dict[str, Any]]:
    official_rows = _iter_official_sections(root_dir)
    for chunk in chunks:
        search_text = str(chunk.get("search_text") or chunk.get("body_md") or chunk.get("title") or "")
        vector_matches: list[dict[str, Any]] = []
        try:
            vector_matches = [
                match
                for match in _query_official_qdrant(root_dir, search_text, top_k=top_k)
                if float(match.get("score") or 0.0) >= min_score
            ]
        except Exception:  # noqa: BLE001
            vector_matches = []
        lexical_matches = _lexical_official_matches(
            official_rows,
            chunk,
            top_k=top_k,
            min_overlap=min_overlap,
            min_score=min_score,
        )
        chunk["related_official_docs"] = _merge_matches(vector_matches, lexical_matches, top_k=top_k)
    return chunks


__all__ = ["match_official_docs"]
