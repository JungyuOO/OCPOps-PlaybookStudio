# BM25 인덱스 생성과 키워드 검색을 담당하는 retrieval 하위 모듈.
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .models import RetrievalHit


TOKEN_RE = re.compile(r"[\uac00-\ud7a3]+|[A-Za-z0-9_.-]+")


def tokenize_text(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text or "")]


def _row_to_hit(row: dict, score: float) -> RetrievalHit:
    return RetrievalHit(
        chunk_id=str(row["chunk_id"]),
        book_slug=str(row["book_slug"]),
        chapter=str(row.get("chapter", "")),
        section=str(row.get("section", "")),
        section_id=str(row.get("section_id", "")),
        anchor=str(row.get("anchor", "")),
        source_url=str(row.get("source_url", "")),
        viewer_path=str(row.get("viewer_path", "")),
        text=str(row.get("text", "")),
        source="bm25",
        raw_score=float(score),
        fused_score=float(score),
        section_path=tuple(str(item) for item in (row.get("section_path") or []) if str(item).strip()),
        chunk_type=str(row.get("chunk_type", "reference")),
        source_id=str(row.get("source_id", "")),
        source_lane=str(row.get("source_lane", "official_ko")),
        source_type=str(row.get("source_type", "official_doc")),
        source_collection=str(row.get("source_collection", "core")),
        review_status=str(row.get("review_status", "unreviewed")),
        trust_score=float(row.get("trust_score", 1.0) or 1.0),
        parsed_artifact_id=str(row.get("parsed_artifact_id", "")),
        semantic_role=str(row.get("semantic_role", "unknown")),
        block_kinds=tuple(str(item) for item in (row.get("block_kinds") or []) if str(item).strip()),
        cli_commands=tuple(str(item) for item in (row.get("cli_commands") or []) if str(item).strip()),
        error_strings=tuple(str(item) for item in (row.get("error_strings") or []) if str(item).strip()),
        k8s_objects=tuple(str(item) for item in (row.get("k8s_objects") or []) if str(item).strip()),
        operator_names=tuple(str(item) for item in (row.get("operator_names") or []) if str(item).strip()),
        verification_hints=tuple(
            str(item) for item in (row.get("verification_hints") or []) if str(item).strip()
        ),
    )


@dataclass(slots=True)
class BM25Index:
    rows: list[dict]
    term_frequencies: list[Counter[str]]
    doc_lengths: list[int]
    doc_frequencies: Counter[str]
    avg_doc_length: float
    k1: float = 1.5
    b: float = 0.75

    @classmethod
    def from_rows(cls, rows: list[dict]) -> "BM25Index":
        term_frequencies: list[Counter[str]] = []
        doc_lengths: list[int] = []
        doc_frequencies: Counter[str] = Counter()

        for row in rows:
            tokens = tokenize_text(str(row.get("text", "")))
            frequencies = Counter(tokens)
            term_frequencies.append(frequencies)
            doc_lengths.append(len(tokens))
            for token in frequencies:
                doc_frequencies[token] += 1

        avg_doc_length = sum(doc_lengths) / max(len(doc_lengths), 1)
        return cls(
            rows=rows,
            term_frequencies=term_frequencies,
            doc_lengths=doc_lengths,
            doc_frequencies=doc_frequencies,
            avg_doc_length=avg_doc_length,
        )

    @classmethod
    def from_jsonl(cls, path: Path) -> "BM25Index":
        rows: list[dict] = []
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return cls.from_rows(rows)

    def _idf(self, token: str) -> float:
        total_docs = len(self.rows)
        doc_freq = self.doc_frequencies.get(token, 0)
        return math.log(1 + (total_docs - doc_freq + 0.5) / (doc_freq + 0.5))

    def search(self, query: str, top_k: int = 10) -> list[RetrievalHit]:
        query_terms = tokenize_text(query)
        if not query_terms:
            return []

        scores: list[tuple[int, float]] = []
        unique_terms = set(query_terms)
        for index, frequencies in enumerate(self.term_frequencies):
            doc_length = self.doc_lengths[index]
            score = 0.0
            for term in unique_terms:
                term_freq = frequencies.get(term, 0)
                if term_freq == 0:
                    continue
                numerator = term_freq * (self.k1 + 1)
                denominator = term_freq + self.k1 * (
                    1 - self.b + self.b * doc_length / max(self.avg_doc_length, 1.0)
                )
                score += self._idf(term) * numerator / denominator
            if score > 0:
                scores.append((index, score))

        scores.sort(key=lambda item: item[1], reverse=True)
        return [_row_to_hit(self.rows[index], score) for index, score in scores[:top_k]]
