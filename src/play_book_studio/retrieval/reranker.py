"""선택형 2차 reranker.

제품 기본값은 reranker off를 유지하되, 실험은 쉽게 켜고 비교할 수 있게
분리해 둔 파일이다.
"""

from __future__ import annotations

import copy
from functools import lru_cache

from sentence_transformers import CrossEncoder

from play_book_studio.config.settings import Settings

from .models import RetrievalHit


DEFAULT_RERANKER_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"


def _resolve_device(device: str) -> str:
    normalized = (device or "").strip().lower()
    if normalized and normalized != "auto":
        return normalized
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:  # noqa: BLE001
        return "cpu"


@lru_cache(maxsize=2)
def _load_cross_encoder(model_name: str, device: str) -> CrossEncoder:
    return CrossEncoder(model_name, device=device)


def _build_rerank_document(hit: RetrievalHit) -> str:
    parts = [
        hit.chapter.strip(),
        hit.section.strip(),
        hit.text.strip(),
    ]
    return "\n".join(part for part in parts if part)


class CrossEncoderReranker:
    """상위 N개 후보만 다시 읽는 cross-encoder 래퍼."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model_name = settings.reranker_model or DEFAULT_RERANKER_MODEL
        self.device = _resolve_device(settings.reranker_device)
        self.top_n = max(2, settings.reranker_top_n)
        self.batch_size = max(1, settings.reranker_batch_size)
        self._model: CrossEncoder | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.settings.reranker_enabled)

    def warmup(self) -> bool:
        if not self.enabled:
            return False
        self._model_instance()
        return True

    def _model_instance(self) -> CrossEncoder:
        if self._model is None:
            self._model = _load_cross_encoder(self.model_name, self.device)
        return self._model

    def rerank(
        self,
        query: str,
        hits: list[RetrievalHit],
        *,
        top_k: int,
        top_n_override: int | None = None,
    ) -> list[RetrievalHit]:
        if not hits:
            return []

        rerank_limit = top_n_override if top_n_override is not None else self.top_n
        rerank_count = min(len(hits), max(top_k, rerank_limit))
        primary_candidates = [copy.deepcopy(hit) for hit in hits[:rerank_count]]
        remainder = [copy.deepcopy(hit) for hit in hits[rerank_count:]]

        pairs = [(query, _build_rerank_document(hit)) for hit in primary_candidates]
        scores = self._model_instance().predict(
            pairs,
            batch_size=self.batch_size,
            show_progress_bar=False,
            convert_to_numpy=False,
        )

        for hit, score in zip(primary_candidates, scores, strict=True):
            hit.component_scores["pre_rerank_fused_score"] = float(hit.fused_score)
            hit.component_scores["reranker_score"] = float(score)
            hit.fused_score = float(score)
            hit.raw_score = float(score)
            hit.source = "hybrid_reranked"

        primary_candidates.sort(
            key=lambda item: (
                -item.component_scores.get("reranker_score", item.fused_score),
                -item.component_scores.get("pre_rerank_fused_score", 0.0),
                item.book_slug,
                item.chunk_id,
            )
        )

        return primary_candidates + remainder
