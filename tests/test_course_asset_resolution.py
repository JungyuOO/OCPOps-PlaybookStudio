from __future__ import annotations

from pathlib import Path

from play_book_studio.cli import _resolve_course_asset_file


def test_resolve_course_asset_file_supports_root_relative_asset(tmp_path: Path):
    root_dir = tmp_path / "workspace"
    course_dir = root_dir / "corpus" / "sources" / "kmsc" / "parsed-preview" / "course_pbs"
    asset_file = root_dir / "data" / "course_pbs" / "assets" / "slide.png"
    asset_file.parent.mkdir(parents=True)
    asset_file.write_bytes(b"png")

    resolved = _resolve_course_asset_file(root_dir, course_dir, "data/course_pbs/assets/slide.png")

    assert resolved == asset_file.resolve()


def test_resolve_course_asset_file_falls_back_to_embedded_course_assets(tmp_path: Path):
    root_dir = tmp_path / "workspace"
    course_dir = root_dir / "corpus" / "sources" / "kmsc" / "parsed-preview" / "course_pbs"
    asset_file = course_dir / "assets" / "slide.png"
    asset_file.parent.mkdir(parents=True)
    asset_file.write_bytes(b"png")

    resolved = _resolve_course_asset_file(root_dir, course_dir, "data/course_pbs/assets/slide.png")

    assert resolved == asset_file.resolve()


def test_resolve_course_asset_file_returns_none_for_missing_assets(tmp_path: Path):
    root_dir = tmp_path / "workspace"
    course_dir = root_dir / "corpus" / "sources" / "kmsc" / "parsed-preview" / "course_pbs"

    resolved = _resolve_course_asset_file(root_dir, course_dir, "data/course_pbs/assets/missing.png")

    assert resolved is None
