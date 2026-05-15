from __future__ import annotations

import zipfile
from pathlib import Path

from play_book_studio.ingestion.document_parsing import DocumentAsset
from play_book_studio.ingestion.vision import load_asset_image_bytes


def test_load_asset_image_bytes_prefers_runtime_content_for_rendered_pdf_assets(tmp_path: Path):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.7")
    asset = DocumentAsset(
        asset_id="asset-1",
        asset_type="image",
        filename="page-001.png",
        mime_type="image/png",
        sha256="asset-sha",
        storage_key="uploads/assets/asset-1.png",
        content=b"\x89PNG\r\n\x1a\npage",
        metadata={"source_member": "pdf:rendered:page:1"},
    )

    assert load_asset_image_bytes(source, asset) == asset.content


def test_load_asset_image_bytes_reads_archive_members_when_no_runtime_content(tmp_path: Path):
    source = tmp_path / "deck.pptx"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("ppt/media/image1.png", b"\x89PNG\r\n\x1a\nslide")
    asset = DocumentAsset(
        asset_id="asset-1",
        asset_type="image",
        filename="image1.png",
        mime_type="image/png",
        sha256="asset-sha",
        storage_key="uploads/assets/asset-1.png",
        metadata={"source_member": "ppt/media/image1.png"},
    )

    assert load_asset_image_bytes(source, asset) == b"\x89PNG\r\n\x1a\nslide"
