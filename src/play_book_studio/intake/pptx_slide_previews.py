from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


_RENDERER_PACKAGE_JSON = """{
  "type": "module"
}
"""

_RENDERER_SCRIPT = """import { FileBlob, PresentationFile } from "@oai/artifact-tool";
import fs from "node:fs/promises";
import path from "node:path";

const inputPath = process.argv[2];
const outputDir = process.argv[3];

if (!inputPath || !outputDir) {
  console.error(JSON.stringify({ error: "missing_args" }));
  process.exit(1);
}

await fs.mkdir(outputDir, { recursive: true });

const file = await FileBlob.load(inputPath);
const presentation = await PresentationFile.importPptx(file);
const slides = presentation?.slides?.items ?? [];
const previews = [];

for (let index = 0; index < slides.length; index += 1) {
  const render = await presentation.export({
    slide: slides[index],
    format: "png",
    scale: 1,
  });
  const fileName = `slide-${String(index + 1).padStart(3, "0")}-preview.png`;
  const targetPath = path.join(outputDir, fileName);

  if (render?.save) {
    await render.save(targetPath);
  } else if (render?.arrayBuffer) {
    const buffer = Buffer.from(await render.arrayBuffer());
    await fs.writeFile(targetPath, buffer);
  } else if (render instanceof Uint8Array) {
    await fs.writeFile(targetPath, render);
  } else {
    continue;
  }

  const stat = await fs.stat(targetPath);
  previews.push({
    ordinal: index + 1,
    file_name: fileName,
    byte_size: stat.size,
  });
}

console.log(JSON.stringify({
  slide_count: slides.length,
  preview_count: previews.length,
  previews,
}));
"""


def render_pptx_slide_preview_assets(
    *,
    capture_path: Path,
    books_dir: Path,
    asset_slug: str,
    slide_width: int,
    slide_height: int,
    slide_count: int,
) -> list[dict[str, Any]]:
    if slide_count <= 0:
        return []
    node_bin = _resolve_node_bin()
    node_modules_dir = _resolve_node_modules_dir(node_bin)
    if node_bin is None or node_modules_dir is None:
        return []

    runtime_dir = books_dir / ".pptx-slide-preview-tool"
    output_dir = books_dir / f"{asset_slug}.slide-assets"
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale_path in output_dir.glob("slide-*-preview.png"):
        stale_path.unlink(missing_ok=True)

    try:
        script_path = _ensure_renderer_workspace(runtime_dir, node_modules_dir)
        completed = subprocess.run(
            [str(node_bin), str(script_path), str(capture_path), str(output_dir)],
            cwd=str(runtime_dir),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except Exception:  # noqa: BLE001
        completed = None

    preview_assets = _collect_rendered_slide_preview_assets(
        output_dir=output_dir,
        asset_slug=asset_slug,
        slide_width=slide_width,
        slide_height=slide_height,
        slide_count=slide_count,
    )
    if preview_assets:
        return preview_assets

    if completed is None:
        return []

    payload = _parse_renderer_stdout(completed.stdout)
    expected_count = int(payload.get("preview_count") or 0)
    if expected_count <= 0:
        return []
    return _collect_rendered_slide_preview_assets(
        output_dir=output_dir,
        asset_slug=asset_slug,
        slide_width=slide_width,
        slide_height=slide_height,
        slide_count=slide_count,
    )


def _parse_renderer_stdout(stdout: str) -> dict[str, Any]:
    lines = [line.strip() for line in str(stdout or "").splitlines() if line.strip()]
    for line in reversed(lines):
        try:
            payload = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _collect_rendered_slide_preview_assets(
    *,
    output_dir: Path,
    asset_slug: str,
    slide_width: int,
    slide_height: int,
    slide_count: int,
) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for ordinal in range(1, slide_count + 1):
        file_name = f"slide-{ordinal:03d}-preview.png"
        preview_path = output_dir / file_name
        if not preview_path.is_file():
            continue
        slide_id = f"{asset_slug}::slide-{ordinal:03d}"
        storage_relpath = f"{asset_slug}.slide-assets/{file_name}"
        assets.append(
            {
                "asset_ref": f"{asset_slug}::slide-{ordinal:03d}-preview",
                "asset_name": f"slide-{ordinal:03d}-preview",
                "asset_kind": "slide_preview",
                "content_type": "image/png",
                "storage_relpath": storage_relpath,
                "slide_id": slide_id,
                "ordinal": ordinal,
                "bbox": {
                    "top": 0,
                    "left": 0,
                    "width": int(slide_width or 0),
                    "height": int(slide_height or 0),
                },
                "alt": f"Slide {ordinal} preview",
                "byte_size": int(preview_path.stat().st_size),
            }
        )
    return assets


def _resolve_node_bin() -> Path | None:
    candidates = [
        os.environ.get("PBS_SLIDE_PREVIEW_NODE_BIN", "").strip(),
        os.environ.get("PBS_NODE_BIN", "").strip(),
        shutil.which("node") or "",
        str(_codex_runtime_node_bin()),
    ]
    for candidate in candidates:
        path = Path(candidate).expanduser() if candidate else None
        if path and path.is_file():
            return path
    return None


def _resolve_node_modules_dir(node_bin: Path | None) -> Path | None:
    candidates = [
        os.environ.get("PBS_SLIDE_PREVIEW_NODE_MODULES", "").strip(),
        os.environ.get("PBS_NODE_MODULES", "").strip(),
    ]
    if node_bin is not None:
        candidates.append(str(node_bin.resolve().parents[2] / "node_modules"))
    candidates.append(str(_codex_runtime_node_modules_dir()))
    for candidate in candidates:
        path = Path(candidate).expanduser() if candidate else None
        if path and (path / "@oai" / "artifact-tool").exists():
            return path
    return None


def _codex_runtime_node_bin() -> Path:
    return Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "bin" / (
        "node.exe" if os.name == "nt" else "node"
    )


def _codex_runtime_node_modules_dir() -> Path:
    return Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "node_modules"


def _ensure_renderer_workspace(runtime_dir: Path, node_modules_dir: Path) -> Path:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    package_json_path = runtime_dir / "package.json"
    script_path = runtime_dir / "render_previews.mjs"
    package_json_text = package_json_path.read_text(encoding="utf-8") if package_json_path.exists() else ""
    script_text = script_path.read_text(encoding="utf-8") if script_path.exists() else ""
    if package_json_text != _RENDERER_PACKAGE_JSON:
        package_json_path.write_text(_RENDERER_PACKAGE_JSON, encoding="utf-8")
    if script_text != _RENDERER_SCRIPT:
        script_path.write_text(_RENDERER_SCRIPT, encoding="utf-8")
    _ensure_node_modules_link(runtime_dir / "node_modules", node_modules_dir)
    return script_path


def _ensure_node_modules_link(link_path: Path, node_modules_dir: Path) -> None:
    expected_target = str(node_modules_dir.resolve())
    if link_path.exists():
        try:
            if str(link_path.resolve()) == expected_target:
                return
        except Exception:  # noqa: BLE001
            pass
        if link_path.is_symlink():
            link_path.unlink(missing_ok=True)
        else:
            shutil.rmtree(link_path, ignore_errors=True)
    try:
        link_path.symlink_to(node_modules_dir, target_is_directory=True)
        return
    except Exception:  # noqa: BLE001
        if os.name != "nt":
            raise
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link_path), str(node_modules_dir)],
        check=True,
        capture_output=True,
        text=True,
    )


__all__ = ["render_pptx_slide_preview_assets"]
