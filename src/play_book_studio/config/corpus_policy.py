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


def chunk_profile_for_section(
    book_slug: str,
    *,
    semantic_role: str = "",
    has_cli_commands: bool = False,
    has_error_strings: bool = False,
    block_kinds: tuple[str, ...] | list[str] = (),
    default_chunk_size: int,
    default_chunk_overlap: int,
) -> tuple[int, int]:
    """Return a retrieval-oriented chunk profile for an official section."""

    role = str(semantic_role or "").strip().lower()
    kinds = {str(kind).strip().lower() for kind in block_kinds if str(kind).strip()}
    if has_error_strings or role == "troubleshooting":
        return min(default_chunk_size, 128), min(default_chunk_overlap, 16)
    if has_cli_commands or role == "procedure" or "code" in kinds:
        return min(default_chunk_size, 128), min(default_chunk_overlap, 16)
    if role in {"concept", "overview"}:
        return max(default_chunk_size, 192), default_chunk_overlap
    return chunk_profile_for_book_slug(
        book_slug,
        default_chunk_size=default_chunk_size,
        default_chunk_overlap=default_chunk_overlap,
    )
