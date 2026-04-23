from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from play_book_studio.config.settings import Settings


_NUMERIC_HEADING_RE = re.compile(r"^(\d+(?:\.\d+){0,5}|(?:\d+\)))\.?\s+(.*?)\s*$")


def _resolve_unhwp_bin(*, settings: Settings | None = None) -> str:
    configured = ""
    if settings is not None and str(settings.unhwp_bin or "").strip():
        configured = str(settings.unhwp_bin or "").strip()
    if configured:
        return configured
    return shutil.which("unhwp") or ""


def _unhwp_timeout_seconds(*, settings: Settings | None = None) -> float:
    if settings is not None:
        return float(settings.unhwp_timeout_seconds or 30.0)
    return 30.0


def _load_unhwp_module():
    try:
        import unhwp  # type: ignore
    except Exception:  # noqa: BLE001
        return None
    return unhwp


def probe_unhwp(*, settings: Settings | None = None) -> dict[str, Any]:
    binary = _resolve_unhwp_bin(settings=settings)
    if binary:
        try:
            response = subprocess.run(
                [binary, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_unhwp_timeout_seconds(settings=settings),
                check=True,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "unreachable",
                "ready": False,
                "binary": binary,
                "reason": f"unhwp_probe_failed:{exc}",
            }
        return {
            "status": "ok",
            "ready": True,
            "binary": binary,
            "version": str((response.stdout or response.stderr or "").strip()),
            "runtime": "cli",
        }

    unhwp_module = _load_unhwp_module()
    if unhwp_module is None:
        return {
            "status": "not_configured",
            "ready": False,
            "binary": "",
            "reason": "unhwp_not_found",
        }
    try:
        version = str(unhwp_module.version())
        supported_formats = str(unhwp_module.supported_formats())
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "unreachable",
            "ready": False,
            "binary": "python:unhwp",
            "reason": f"unhwp_python_probe_failed:{exc}",
        }
    return {
        "status": "ok",
        "ready": True,
        "binary": "python:unhwp",
        "version": version,
        "supported_formats": supported_formats,
        "runtime": "python",
    }


def extract_hwp_markdown_with_unhwp(
    source: str | Path,
    *,
    settings: Settings | None = None,
) -> str:
    path = Path(source).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"captured artifact를 찾을 수 없습니다: {path}")

    with tempfile.TemporaryDirectory(prefix="pbs-unhwp-") as tmpdir:
        output_dir = Path(tmpdir) / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        _run_unhwp_convert(path, output_dir=output_dir, settings=settings)
        outputs = _read_unhwp_outputs(output_dir)

    markdown = str(outputs.get("markdown") or "").strip()
    if markdown:
        return markdown
    plain_text = str(outputs.get("plain_text") or "").strip()
    if plain_text:
        return f"# {path.stem}\n\n{plain_text}".strip()
    content = outputs.get("content")
    rendered = _render_unhwp_content_json(content, title=path.stem)
    if rendered:
        return rendered
    raise ValueError(f"unhwp produced no readable content for {path.name}")


def extract_hwp_rows_with_unhwp(
    source: str | Path,
    *,
    book_slug: str,
    book_title: str,
    source_url: str,
    viewer_path_base: str,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    path = Path(source).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"captured artifact를 찾을 수 없습니다: {path}")

    with tempfile.TemporaryDirectory(prefix="pbs-unhwp-rows-") as tmpdir:
        output_dir = Path(tmpdir) / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        _run_unhwp_convert(path, output_dir=output_dir, settings=settings)
        outputs = _read_unhwp_outputs(output_dir)

    rows = _rows_from_unhwp_content_json(
        outputs.get("content"),
        book_slug=book_slug,
        book_title=book_title,
        source_url=source_url,
        viewer_path_base=viewer_path_base,
    )
    if rows:
        return rows
    return []


def _run_unhwp_convert(path: Path, *, output_dir: Path, settings: Settings | None = None) -> None:
    binary = _resolve_unhwp_bin(settings=settings)
    if binary:
        subprocess.run(
            [binary, "convert", str(path), "-o", str(output_dir)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_unhwp_timeout_seconds(settings=settings),
            check=True,
        )
        return
    _run_unhwp_python_convert(path, output_dir=output_dir)


def _run_unhwp_python_convert(path: Path, *, output_dir: Path) -> None:
    unhwp_module = _load_unhwp_module()
    if unhwp_module is None:
        raise RuntimeError("unhwp_not_found")
    output_dir.mkdir(parents=True, exist_ok=True)
    with unhwp_module.parse(path) as result:
        markdown = _read_unhwp_result_text(result, "markdown")
        plain_text = _read_unhwp_result_text(result, "plain_text") or _read_unhwp_result_text(result, "text")
        content_json = _read_unhwp_result_text(result, "json")
    if markdown:
        (output_dir / "extract.md").write_text(markdown, encoding="utf-8")
    if plain_text:
        (output_dir / "extract.txt").write_text(plain_text, encoding="utf-8")
    if content_json:
        try:
            normalized_json = json.dumps(json.loads(content_json), ensure_ascii=False, indent=2)
        except Exception:  # noqa: BLE001
            normalized_json = content_json
        (output_dir / "content.json").write_text(normalized_json, encoding="utf-8")


def _read_unhwp_result_text(result: Any, attribute: str) -> str:
    try:
        value = getattr(result, attribute)
    except Exception:  # noqa: BLE001
        return ""
    return str(value or "").strip()


def _read_unhwp_outputs(output_dir: Path) -> dict[str, Any]:
    markdown_path = output_dir / "extract.md"
    plain_text_path = output_dir / "extract.txt"
    content_json_path = output_dir / "content.json"
    content: dict[str, Any] | None = None
    if content_json_path.exists():
        try:
            content = json.loads(content_json_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            content = None
    return {
        "markdown": markdown_path.read_text(encoding="utf-8") if markdown_path.exists() else "",
        "plain_text": plain_text_path.read_text(encoding="utf-8") if plain_text_path.exists() else "",
        "content": content,
    }


def _render_unhwp_content_json(content: Any, *, title: str) -> str:
    if not isinstance(content, dict):
        return ""
    lines: list[str] = [f"# {title}"]
    sections = content.get("sections")
    if isinstance(sections, list):
        for section_index, section in enumerate(sections, start=1):
            rendered = _render_unhwp_section(section, ordinal=section_index)
            if rendered:
                lines.extend(rendered)
    if len(lines) > 1:
        return "\n\n".join(line for line in lines if line).strip()
    return ""


def _rows_from_unhwp_content_json(
    content: Any,
    *,
    book_slug: str,
    book_title: str,
    source_url: str,
    viewer_path_base: str,
) -> list[dict[str, Any]]:
    if not isinstance(content, dict):
        return []
    sections = content.get("sections")
    if not isinstance(sections, list) or not sections:
        return []

    rows: list[dict[str, Any]] = []
    current_heading = book_title.strip() or book_slug.strip() or "Uploaded HWP"
    current_level = 1
    current_body: list[str] = []
    path_stack: list[str] = [current_heading]

    def flush() -> None:
        ordinal = len(rows) + 1
        heading = current_heading.strip() or f"Section {ordinal}"
        body = "\n".join(line for line in current_body if str(line).strip()).strip()
        if not body:
            return
        anchor = _slug_anchor(heading, ordinal=ordinal)
        section_path = tuple(path_stack[:current_level]) if path_stack else (heading,)
        rows.append(
            {
                "book_slug": book_slug,
                "book_title": book_title,
                "heading": heading,
                "section_level": current_level,
                "section_path": list(section_path),
                "anchor": anchor,
                "source_url": source_url,
                "viewer_path": f"{viewer_path_base}#{anchor}",
                "text": body,
            }
        )

    for section in sections:
        if not isinstance(section, dict):
            continue
        for item in section.get("content") or []:
            block = _unhwp_block_to_text(item)
            if not block:
                continue
            heading = _detect_unhwp_heading(item, block)
            if heading:
                flush()
                current_level, current_heading = heading
                path_stack = path_stack[: max(current_level - 1, 0)]
                path_stack.append(current_heading)
                current_body = []
                continue
            current_body.append(block)

    flush()
    return rows


def _render_unhwp_section(section: Any, *, ordinal: int) -> list[str]:
    if not isinstance(section, dict):
        return []
    lines: list[str] = []
    heading = str(section.get("title") or section.get("heading") or section.get("name") or "").strip()
    if heading:
        lines.append(f"## {heading}")
    paragraphs = section.get("paragraphs")
    if isinstance(paragraphs, list):
        for item in paragraphs:
            rendered = _render_unhwp_paragraph(item)
            if rendered:
                lines.append(rendered)
    tables = section.get("tables")
    if isinstance(tables, list):
        for table in tables:
            rendered = _render_unhwp_table(table)
            if rendered:
                lines.append(rendered)
    if not lines:
        flat_text = str(section.get("text") or "").strip()
        if flat_text:
            lines.append(f"## Section {ordinal}")
            lines.append(flat_text)
    return lines


def _unhwp_block_to_text(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    if "Paragraph" in item:
        return _render_unhwp_paragraph(item["Paragraph"])
    if "Table" in item:
        return _render_unhwp_table(item["Table"])
    return ""


def _detect_unhwp_heading(item: Any, text: str) -> tuple[int, str] | None:
    stripped = str(text or "").strip()
    if not stripped:
        return None
    if isinstance(item, dict):
        paragraph = item.get("Paragraph")
        if isinstance(paragraph, dict):
            style = paragraph.get("style")
            if isinstance(style, dict):
                level = int(style.get("heading_level") or 0)
                if level > 0:
                    return min(level, 6), stripped
    match = _NUMERIC_HEADING_RE.match(stripped)
    if match:
        number = str(match.group(1) or "").strip()
        if number.endswith(")"):
            return 2, stripped
        return number.count(".") + 1, stripped
    return None


def _render_unhwp_paragraph(paragraph: Any) -> str:
    if isinstance(paragraph, str):
        return paragraph.strip()
    if not isinstance(paragraph, dict):
        return ""
    text = str(paragraph.get("text") or "").strip()
    if text:
        return text
    lines: list[str] = []
    for block in paragraph.get("content") or []:
        line = _render_unhwp_inline_block(block)
        if line:
            lines.append(line)
    if lines:
        list_style = paragraph.get("style") if isinstance(paragraph.get("style"), dict) else {}
        prefix = ""
        if isinstance(list_style, dict) and list_style.get("list_style"):
            indent_level = int(list_style.get("indent_level") or 0)
            prefix = f"{'  ' * indent_level}- "
        return prefix + " ".join(lines).strip()
    runs = paragraph.get("runs")
    if isinstance(runs, list):
        tokens = []
        for run in runs:
            if isinstance(run, dict):
                token = str(run.get("text") or "").strip()
                if token:
                    tokens.append(token)
        return " ".join(tokens).strip()
    return ""


def _render_unhwp_inline_block(block: Any) -> str:
    if isinstance(block, str):
        return block.strip()
    if not isinstance(block, dict):
        return ""
    if "Text" in block and isinstance(block["Text"], dict):
        return str(block["Text"].get("text") or "").strip()
    style = block.get("style")
    content = block.get("content")
    if isinstance(content, list):
        rendered = " ".join(
            part
            for part in (_render_unhwp_inline_block(item) for item in content)
            if part
        ).strip()
        if rendered and isinstance(style, dict) and style.get("list_style"):
            indent_level = int(style.get("indent_level") or 0)
            return f"{'  ' * indent_level}- {rendered}".strip()
        return rendered
    return str(block.get("text") or "").strip()


def _render_unhwp_table(table: Any) -> str:
    if not isinstance(table, dict):
        return ""
    rendered_rows = _render_unhwp_table_rows(table)
    if not rendered_rows:
        return ""
    return "[TABLE]\n" + "\n".join(rendered_rows) + "\n[/TABLE]"


def _render_unhwp_table_rows(table: Any) -> list[str]:
    rows = table.get("rows")
    if not isinstance(rows, list):
        return []
    rendered_rows: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        cells: list[str] = []
        for cell in row.get("cells") or []:
            cells.append(_render_unhwp_table_cell(cell) or "-")
        if cells:
            rendered_rows.append(" | ".join(cells))
    return rendered_rows


def _render_unhwp_table_cell(cell: Any) -> str:
    if isinstance(cell, str):
        return cell.strip()
    if not isinstance(cell, dict):
        return ""
    text = str(cell.get("text") or "").strip()
    if text:
        return text
    lines: list[str] = []
    for block in cell.get("content") or []:
        if isinstance(block, dict) and "Text" in block and isinstance(block["Text"], dict):
            token = str(block["Text"].get("text") or "").strip()
            if token:
                lines.append(token)
                continue
        line = _render_unhwp_paragraph(block)
        if line:
            lines.append(line)
    return " ".join(lines).strip()


def _slug_anchor(value: str, *, ordinal: int) -> str:
    cleaned = re.sub(r"[^a-z0-9가-힣]+", "-", value.strip().lower())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned or f"section-{ordinal}"


__all__ = [
    "extract_hwp_markdown_with_unhwp",
    "extract_hwp_rows_with_unhwp",
    "probe_unhwp",
]
