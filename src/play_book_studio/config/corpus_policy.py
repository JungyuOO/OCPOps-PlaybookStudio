# 코퍼스 승인, reference-heavy 분리, 번역 우선순위 같은 정책 상수를 둔다.
from __future__ import annotations

REFERENCE_HEAVY_EXPLICIT_SLUGS = {
    "api_overview",
    "common_object_reference",
}

TRANSLATION_PRIORITY_SLUGS = (
    "machine_configuration",
    "monitoring",
    "backup_and_restore",
    "installing_on_any_platform",
)

MANUAL_REVIEW_PRIORITY_SLUGS = (
    "etcd",
    "operators",
)


def is_reference_heavy_book_slug(book_slug: str) -> bool:
    slug = str(book_slug or "").strip()
    return slug.endswith("_apis") or slug in REFERENCE_HEAVY_EXPLICIT_SLUGS


def chunk_profile_for_book_slug(
    book_slug: str,
    *,
    default_chunk_size: int,
    default_chunk_overlap: int,
) -> tuple[int, int]:
    slug = str(book_slug or "").strip()
    if slug == "common_object_reference":
        return 320, 0
    if is_reference_heavy_book_slug(slug):
        return 240, 0
    return default_chunk_size, default_chunk_overlap
