from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from play_book_studio.config.settings import Settings

from .topic_playbooks import DERIVED_PLAYBOOK_SOURCE_TYPES

_TOKEN_RE = re.compile(r"[A-Za-z0-9가-힣][A-Za-z0-9가-힣_\-/]{1,}")


def _read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _source_type(row: dict[str, Any]) -> str:
    metadata = row.get("source_metadata") if isinstance(row.get("source_metadata"), dict) else {}
    return str(metadata.get("source_type") or "official_doc").strip() or "official_doc"


def _source_slug(row: dict[str, Any]) -> str:
    metadata = row.get("source_metadata") if isinstance(row.get("source_metadata"), dict) else {}
    derived_from = str(metadata.get("derived_from_book_slug") or "").strip()
    if derived_from:
        return derived_from
    return str(row.get("book_slug") or "").strip()


def _row_text(row: dict[str, Any]) -> str:
    parts = [str(row.get("title") or "")]
    for section in row.get("sections") or []:
        if not isinstance(section, dict):
            continue
        parts.append(str(section.get("heading") or ""))
        parts.append(str(section.get("section_path_label") or ""))
        for block in section.get("blocks") or []:
            if isinstance(block, dict):
                parts.append(str(block.get("text") or ""))
    return "\n".join(part for part in parts if part)


def _tokenize(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(text)}


def _heading_tokens(row: dict[str, Any]) -> set[str]:
    tokens: set[str] = set()
    for section in row.get("sections") or []:
        if isinstance(section, dict):
            tokens.update(_tokenize(str(section.get("heading") or "")))
    return tokens


def _is_approved_runtime_row(row: dict[str, Any]) -> bool:
    return (
        str(row.get("translation_status") or "").strip() == "approved_ko"
        and str(row.get("review_status") or "").strip() == "approved"
    )


def _build_family_scores(
    source_row: dict[str, Any],
    family_rows: dict[str, dict[str, Any]],
) -> dict[str, dict[str, float | int]]:
    source_tokens = _tokenize(_row_text(source_row))
    source_heading_tokens = _heading_tokens(source_row)
    source_section_count = max(int(source_row.get("section_count") or 0), 1)
    scores: dict[str, dict[str, float | int]] = {}
    for family, row in sorted(family_rows.items()):
        derived_tokens = _tokenize(_row_text(row))
        derived_heading_tokens = _heading_tokens(row)
        overlap = source_tokens & derived_tokens
        recall = len(overlap) / len(source_tokens) if source_tokens else 0.0
        precision = len(overlap) / len(derived_tokens) if derived_tokens else 0.0
        heading_recall = (
            len(source_heading_tokens & derived_heading_tokens) / len(source_heading_tokens)
            if source_heading_tokens
            else 0.0
        )
        section_ratio = min((int(row.get("section_count") or 0) / source_section_count), 1.0)
        score = (
            0.55 * recall
            + 0.20 * precision
            + 0.15 * heading_recall
            + 0.10 * section_ratio
        )
        scores[family] = {
            "score": round(score, 6),
            "recall": round(recall, 6),
            "precision": round(precision, 6),
            "heading_recall": round(heading_recall, 6),
            "section_ratio": round(section_ratio, 6),
            "section_count": int(row.get("section_count") or 0),
        }
    return scores


def _winner_payload(
    source_slug: str,
    source_row: dict[str, Any],
    family_scores: dict[str, dict[str, float | int]],
) -> dict[str, Any]:
    ranked = sorted(
        family_scores.items(),
        key=lambda item: float(item[1].get("score") or 0.0),
        reverse=True,
    )
    winner_family, winner_scores = ranked[0]
    runner_up_family, runner_up_scores = ranked[1] if len(ranked) > 1 else (None, {"score": 0.0})
    return {
        "source_slug": source_slug,
        "source_type": _source_type(source_row),
        "source_title": str(source_row.get("title") or "").strip(),
        "source_section_count": int(source_row.get("section_count") or 0),
        "winner_family": winner_family,
        "winner_score": float(winner_scores.get("score") or 0.0),
        "runner_up_family": runner_up_family,
        "runner_up_score": float(runner_up_scores.get("score") or 0.0),
        "winner_margin": round(
            float(winner_scores.get("score") or 0.0) - float(runner_up_scores.get("score") or 0.0),
            6,
        ),
        "family_scores": family_scores,
    }


def _selection_summary(winners: Iterable[dict[str, Any]]) -> dict[str, Any]:
    winner_rows = list(winners)
    family_counts: Counter[str] = Counter()
    family_score_totals: defaultdict[str, float] = defaultdict(float)
    family_score_counts: Counter[str] = Counter()
    margins: list[float] = []
    for row in winner_rows:
        family = str(row.get("winner_family") or "").strip()
        if family:
            family_counts[family] += 1
        margins.append(float(row.get("winner_margin") or 0.0))
        for family_name, score_payload in dict(row.get("family_scores") or {}).items():
            family_score_totals[family_name] += float(score_payload.get("score") or 0.0)
            family_score_counts[family_name] += 1
    average_scores = {
        family: round(family_score_totals[family] / family_score_counts[family], 6)
        for family in sorted(family_score_totals)
        if family_score_counts[family] > 0
    }
    overall_winner_family = ""
    if average_scores:
        overall_winner_family = max(
            average_scores.items(),
            key=lambda item: item[1],
        )[0]
    ordered_averages = sorted(average_scores.items(), key=lambda item: item[1], reverse=True)
    average_margin = 0.0
    if len(ordered_averages) >= 2:
        average_margin = round(ordered_averages[0][1] - ordered_averages[1][1], 6)
    winner_share = 0.0
    if winner_rows and overall_winner_family:
        winner_share = round(family_counts.get(overall_winner_family, 0) / len(winner_rows), 6)
    selection_ready = bool(
        overall_winner_family
        and winner_rows
        and winner_share >= 0.6
        and average_margin >= 0.01
    )
    return {
        "source_count": len(winner_rows),
        "winner_family_counts": dict(sorted(family_counts.items())),
        "family_average_scores": average_scores,
        "overall_winner_family": overall_winner_family,
        "winner_share": winner_share,
        "average_margin_vs_runner_up": average_margin,
        "average_winner_margin_per_source": round(sum(margins) / len(margins), 6) if margins else 0.0,
        "selection_ready": selection_ready,
    }


def build_playbook_family_selection_report_from_rows(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    source_truth_rows: dict[str, dict[str, Any]] = {}
    derived_rows: defaultdict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        if not isinstance(row, dict) or not _is_approved_runtime_row(row):
            continue
        source_type = _source_type(row)
        if source_type in DERIVED_PLAYBOOK_SOURCE_TYPES:
            derived_rows[_source_slug(row)][source_type] = row
        else:
            source_truth_rows[str(row.get("book_slug") or "").strip()] = row

    per_source_winners: list[dict[str, Any]] = []
    official_doc_winners: list[dict[str, Any]] = []
    manual_synthesis_winners: list[dict[str, Any]] = []
    for source_slug, source_row in sorted(source_truth_rows.items()):
        family_rows = derived_rows.get(source_slug) or {}
        if not family_rows:
            continue
        family_scores = _build_family_scores(source_row, family_rows)
        if not family_scores:
            continue
        winner = _winner_payload(source_slug, source_row, family_scores)
        per_source_winners.append(winner)
        if winner["source_type"] == "official_doc":
            official_doc_winners.append(winner)
        elif winner["source_type"] == "manual_synthesis":
            manual_synthesis_winners.append(winner)

    official_summary = _selection_summary(official_doc_winners)
    source_truth_summary = _selection_summary(per_source_winners)
    convergence_source = official_summary if official_summary.get("source_count") else source_truth_summary
    overall_winner_family = str(convergence_source.get("overall_winner_family") or "").strip()
    return {
        "source_truth_count": len(source_truth_rows),
        "derived_family_count": len(DERIVED_PLAYBOOK_SOURCE_TYPES),
        "per_source_winners": per_source_winners,
        "official_doc_summary": official_summary,
        "manual_synthesis_summary": _selection_summary(manual_synthesis_winners),
        "source_truth_summary": source_truth_summary,
        "convergence": {
            "ready": bool(convergence_source.get("selection_ready")),
            "publish_default": "source_truth_only",
            "single_derived_family": overall_winner_family,
            "selection_basis": (
                "official_doc_roots"
                if official_summary.get("source_count")
                else "all_source_truth_roots"
            ),
            "notes": [
                "source truth rows remain the primary PlayBook surface",
                "manual_synthesis roots are already condensed source truth and do not override official_doc family policy",
                "single_derived_family only applies when one derived variant is still needed on the product surface",
            ],
        },
    }


def build_playbook_family_selection_report(settings: Settings) -> dict[str, Any]:
    return build_playbook_family_selection_report_from_rows(
        _read_jsonl_rows(settings.playbook_documents_path)
    )
