from __future__ import annotations

from pathlib import Path

import pytest

from play_book_studio.ingestion.asset_storage import remove_stored_asset_files, store_parsed_asset_files
from play_book_studio.ingestion.document_parsing import DocumentAsset, ParsedUploadDocument


def _parsed_with_asset(asset: DocumentAsset) -> ParsedUploadDocument:
    return ParsedUploadDocument(
        document_id="doc-1",
        filename="source.pdf",
        document_format="pdf",
        mime_type="application/pdf",
        sha256="source-sha",
        markdown=f"![{asset.filename}](asset://{asset.asset_id})",
        assets=(asset,),
        metadata={"byte_size": 10},
    )


def test_store_parsed_asset_files_writes_runtime_asset_bytes(tmp_path: Path):
    asset = DocumentAsset(
        asset_id="asset-1",
        asset_type="image",
        filename="page-001.png",
        mime_type="image/png",
        sha256="asset-sha",
        storage_key="uploads/assets/asset-1.png",
        content=b"\x89PNG\r\n\x1a\nbody",
    )

    stored = store_parsed_asset_files(tmp_path, _parsed_with_asset(asset))

    assert len(stored) == 1
    assert stored[0].storage_key == "uploads/assets/asset-1.png"
    assert stored[0].byte_size == len(asset.content)
    assert (tmp_path / "uploads/assets/asset-1.png").read_bytes() == asset.content


def test_store_parsed_asset_files_rejects_path_traversal(tmp_path: Path):
    asset = DocumentAsset(
        asset_id="asset-1",
        asset_type="image",
        filename="bad.png",
        mime_type="image/png",
        sha256="asset-sha",
        storage_key="../bad.png",
        content=b"body",
    )

    with pytest.raises(ValueError, match="invalid asset storage path"):
        store_parsed_asset_files(tmp_path, _parsed_with_asset(asset))


def test_remove_stored_asset_files_cleans_written_files(tmp_path: Path):
    asset = DocumentAsset(
        asset_id="asset-1",
        asset_type="image",
        filename="page-001.png",
        mime_type="image/png",
        sha256="asset-sha",
        storage_key="uploads/assets/asset-1.png",
        content=b"body",
    )
    stored = store_parsed_asset_files(tmp_path, _parsed_with_asset(asset))

    remove_stored_asset_files(stored)

    assert not (tmp_path / "uploads/assets/asset-1.png").exists()
