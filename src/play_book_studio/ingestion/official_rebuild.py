from __future__ import annotations

import re
from pathlib import Path


ASCIIDOC_INCLUDE_RE = re.compile(r"^\s*include::(?P<target>[^\[]+)\[[^\]]*\]\s*$")
ASCIIDOC_HEADING_RE = re.compile(r"^(?P<marks>={1,6})\s+(?P<title>.+?)\s*$")
ASCIIDOC_ATTR_RE = re.compile(r"^:[^:]+:\s*.*$")
ASCIIDOC_ATTR_DEF_RE = re.compile(r"^:(?P<name>[A-Za-z0-9_-]+):\s*(?P<value>.*)$")
ASCIIDOC_DIRECTIVE_RE = re.compile(r"^(ifdef|ifndef|ifeval|endif|toc)::")
ASCIIDOC_IMAGE_RE = re.compile(r"^\s*image::")
ASCIIDOC_COMMENT_RE = re.compile(r"^\s*//")
SOURCE_BLOCK_ATTR_RE = re.compile(r"^\[(?P<body>[^\]]+)\]\s*$")
ATTRIBUTE_TOKEN_RE = re.compile(r"\{(?P<name>[A-Za-z0-9_-]+)\}")
LINK_RE = re.compile(r"link:(?P<url>\S+)\[(?P<label>[^\]]*)\]")
XREF_RE = re.compile(r"xref:[^\[]+\[(?P<label>[^\]]*)\]")

DEFAULT_ATTRIBUTES: dict[str, str] = {
    "product-title": "OpenShift Container Platform",
    "product-version": "4.20",
    "product-title-short": "OpenShift",
    "cluster-manager-first": "Red Hat OpenShift Cluster Manager",
    "red-hat-lightspeed": "Red Hat Lightspeed",
    "oke": "OpenShift Kubernetes Engine",
    "nbsp": " ",
}


def _source_repo_root(source_file: Path) -> Path | None:
    resolved = source_file.resolve()
    parent_chain = (resolved.parent, *resolved.parents)
    for parent in parent_chain:
        if (parent / "_topic_maps").exists():
            return parent
    attribute_roots = [parent for parent in parent_chain if (parent / "_attributes").exists()]
    if attribute_roots:
        return attribute_roots[-1]
    return None


def _resolve_include_path(source_file: Path, include_target: str) -> Path | None:
    normalized = include_target.strip()
    if not normalized or "{" in normalized or "}" in normalized:
        return None
    candidates = [(source_file.parent / normalized).resolve()]
    repo_root = _source_repo_root(source_file)
    if repo_root is not None:
        candidates.append((repo_root / normalized).resolve())
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _substitute_attributes(text: str, attributes: dict[str, str]) -> str:
    current = str(text or "")
    for _ in range(5):
        changed = False

        def replace(match: re.Match[str]) -> str:
            nonlocal changed
            name = str(match.group("name") or "").strip()
            if name in attributes:
                changed = True
                return attributes[name]
            return match.group(0)

        updated = ATTRIBUTE_TOKEN_RE.sub(replace, current)
        current = updated
        if not changed:
            break
    return current


def _normalize_inline_text(text: str, attributes: dict[str, str]) -> str:
    normalized = _substitute_attributes(text, attributes)
    normalized = LINK_RE.sub(lambda match: f"[{match.group('label') or match.group('url')}]({match.group('url')})", normalized)
    normalized = XREF_RE.sub(lambda match: str(match.group("label") or "").strip(), normalized)
    normalized = re.sub(r"pass:\[([^\]]+)\]", r"\1", normalized)
    return normalized


def normalize_inline_text_fragment(text: str) -> str:
    return _normalize_inline_text(text, dict(DEFAULT_ATTRIBUTES))


def _read_expanded_asciidoc(path: Path, seen: set[Path], attributes: dict[str, str]) -> str:
    resolved = path.resolve()
    if resolved in seen or not resolved.exists() or not resolved.is_file():
        return ""
    seen.add(resolved)
    output_lines: list[str] = []
    for raw_line in resolved.read_text(encoding="utf-8", errors="ignore").splitlines():
        include_match = ASCIIDOC_INCLUDE_RE.match(raw_line)
        if include_match is not None:
            include_path = _resolve_include_path(resolved, str(include_match.group("target") or ""))
            if include_path is not None:
                expanded = _read_expanded_asciidoc(include_path, seen, attributes)
                if expanded.strip():
                    output_lines.append(expanded.rstrip())
            continue
        stripped = raw_line.strip()
        if not stripped:
            output_lines.append("")
            continue
        attribute_match = ASCIIDOC_ATTR_DEF_RE.match(stripped)
        if attribute_match is not None:
            name = str(attribute_match.group("name") or "").strip()
            value = _normalize_inline_text(str(attribute_match.group("value") or "").strip(), attributes)
            if name:
                attributes[name] = value
            continue
        if ASCIIDOC_ATTR_RE.match(stripped):
            continue
        if ASCIIDOC_DIRECTIVE_RE.match(stripped):
            continue
        if ASCIIDOC_IMAGE_RE.match(stripped):
            continue
        if ASCIIDOC_COMMENT_RE.match(stripped):
            continue
        normalized = _normalize_inline_text(raw_line.rstrip(), attributes)
        if re.fullmatch(r"\{[^}]+\}", normalized.strip()):
            continue
        output_lines.append(normalized)
    return "\n".join(output_lines).strip()


def expand_asciidoc(path: Path) -> str:
    return _read_expanded_asciidoc(path, set(), dict(DEFAULT_ATTRIBUTES))


def primary_heading_from_path(path: Path) -> str:
    text = expand_asciidoc(path)
    for line in text.splitlines():
        match = ASCIIDOC_HEADING_RE.match(line.strip())
        if match is not None:
            return _clean_inline_asciidoc(str(match.group("title") or ""))
    return path.stem.replace("-", " ").replace("_", " ").strip()


def _clean_inline_asciidoc(text: str) -> str:
    cleaned = str(text or "").strip()
    cleaned = re.sub(r"link:[^\[]+\[([^\]]+)\]", r"\1", cleaned)
    cleaned = re.sub(r"xref:[^\[]+\[([^\]]+)\]", r"\1", cleaned)
    cleaned = re.sub(r"pass:\[[^\]]+\]", "", cleaned)
    return " ".join(cleaned.split()).strip()


def _parse_source_language(line: str) -> str | None:
    match = SOURCE_BLOCK_ATTR_RE.match(line.strip())
    if match is None:
        return None
    body = str(match.group("body") or "").strip()
    if not body:
        return None
    tokens = [token.strip() for token in body.split(",") if token.strip()]
    if not tokens:
        return None
    if not any(token.startswith("source") or token.startswith("listing") for token in tokens):
        return None
    for token in tokens[1:]:
        if token.startswith("%") or "=" in token:
            continue
        return token.lower()
    return "text"


def _render_table(table_lines: list[str]) -> list[str]:
    rows: list[list[str]] = []
    for line in table_lines:
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("|"):
            if rows and rows[-1]:
                rows[-1][-1] = f"{rows[-1][-1]} {stripped}".strip()
            continue
        cells = [cell.strip() for cell in stripped.split("|")[1:]]
        cells = [cell for cell in cells if cell]
        if cells:
            rows.append(cells)
    if not rows:
        return []
    width = max(len(row) for row in rows)
    padded_rows = [row + [""] * (width - len(row)) for row in rows]
    header = padded_rows[0]
    lines = [
        "| " + " | ".join(cell or "-" for cell in header) + " |",
        "| " + " | ".join("---" for _ in range(width)) + " |",
    ]
    for row in padded_rows[1:]:
        lines.append("| " + " | ".join(cell or "-" for cell in row) + " |")
    return lines


def _convert_asciidoc_to_markdown(
    text: str,
    *,
    base_heading_level: int,
    drop_document_title: bool,
) -> str:
    output: list[str] = []
    in_code_block = False
    code_language = "text"
    pending_source_language: str | None = None
    in_table = False
    table_lines: list[str] = []
    in_quote_block = False
    dropped_title = False

    for raw_line in text.splitlines():
        stripped = raw_line.strip()

        if in_table:
            if stripped == "|===":
                output.extend(_render_table(table_lines))
                output.append("")
                table_lines = []
                in_table = False
            else:
                table_lines.append(raw_line)
            continue

        if in_code_block:
            if stripped == "----":
                output.append("```")
                output.append("")
                in_code_block = False
                code_language = "text"
            else:
                output.append(raw_line.rstrip())
            continue

        parsed_language = _parse_source_language(raw_line)
        if parsed_language is not None:
            pending_source_language = parsed_language
            continue

        if stripped == "|===":
            in_table = True
            table_lines = []
            continue

        if stripped == "====":
            in_quote_block = not in_quote_block
            if not in_quote_block:
                output.append("")
            continue

        if stripped == "----" and pending_source_language is not None:
            code_language = pending_source_language or "text"
            output.append(f"```{code_language}")
            in_code_block = True
            pending_source_language = None
            continue
        pending_source_language = None

        heading_match = ASCIIDOC_HEADING_RE.match(stripped)
        if heading_match is not None:
            level = len(str(heading_match.group("marks") or ""))
            title = _clean_inline_asciidoc(str(heading_match.group("title") or ""))
            if drop_document_title and level == 1 and not dropped_title:
                dropped_title = True
                continue
            markdown_level = max(1, min(6, base_heading_level + level - 1))
            output.append(f"{'#' * markdown_level} {title}")
            output.append("")
            continue

        if ASCIIDOC_ATTR_RE.match(stripped):
            continue
        if ASCIIDOC_DIRECTIVE_RE.match(stripped):
            continue
        if stripped == "+":
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            continue
        if ASCIIDOC_IMAGE_RE.match(stripped):
            continue
        if stripped.startswith(".") and len(stripped) > 1 and not stripped.startswith(".."):
            raw_line = stripped[1:]
        if in_quote_block and raw_line.strip():
            output.append(f"> {raw_line.rstrip()}")
            continue

        output.append(raw_line.rstrip())

    lines: list[str] = []
    previous_blank = False
    for line in output:
        is_blank = not line.strip()
        if is_blank and previous_blank:
            continue
        lines.append(line)
        previous_blank = is_blank
    return "\n".join(lines).strip() + "\n"


def render_bound_markdown(
    *,
    title: str,
    source_paths: list[Path],
    binding_kind: str,
) -> str:
    if not source_paths:
        raise ValueError("repo source binding has no source paths")

    parts: list[str] = [f"# {title.strip() or source_paths[0].stem}"]
    if binding_kind == "collection":
        for source_path in source_paths:
            expanded = expand_asciidoc(source_path)
            if not expanded.strip():
                continue
            heading = primary_heading_from_path(source_path)
            parts.extend(
                [
                    "",
                    f"## {heading}",
                    "",
                    _convert_asciidoc_to_markdown(
                        expanded,
                        base_heading_level=3,
                        drop_document_title=True,
                    ).strip(),
                ]
            )
    else:
        expanded = expand_asciidoc(source_paths[0])
        converted = _convert_asciidoc_to_markdown(
            expanded,
            base_heading_level=2,
            drop_document_title=True,
        ).strip()
        if converted:
            parts.extend(["", converted])

    rendered = "\n".join(part for part in parts if part is not None).strip()
    if rendered == f"# {title.strip() or source_paths[0].stem}":
        raise ValueError("repo AsciiDoc binding produced empty markdown")
    return rendered + "\n"
