"""Object-storage helpers for parsed document assets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from play_book_studio.ingestion.document_parsing import ParsedUploadDocument


@dataclass(frozen=True, slots=True)
class StoredAssetFile:
    storage_key: str
    path: Path
    byte_size: int


def store_parsed_asset_files(storage_root: Path, parsed: ParsedUploadDocument) -> tuple[StoredAssetFile, ...]:
    """Write runtime-only asset bytes to object storage before DB rows reference them."""

    if not parsed.assets:
        return ()
    resolved_root = storage_root.resolve()
    stored: list[StoredAssetFile] = []
    for asset in parsed.assets:
        content = bytes(getattr(asset, "content", b"") or b"")
        if not content or not asset.storage_key:
            continue
        target = (resolved_root / asset.storage_key).resolve()
        if resolved_root not in target.parents:
            raise ValueError("invalid asset storage path")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        stored.append(StoredAssetFile(storage_key=asset.storage_key, path=target, byte_size=len(content)))
    return tuple(stored)


def remove_stored_asset_files(stored: tuple[StoredAssetFile, ...]) -> None:
    for item in stored:
        try:
            item.path.unlink(missing_ok=True)
        except OSError:
            continue
