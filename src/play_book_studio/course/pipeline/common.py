from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any


def normalize_text(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def tokenize_korean_english(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9._/-]{1,}|[가-힣]{2,}", str(text or ""))
    return [token.lower() for token in tokens]


def slugify_fragment(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9가-힣]+", "-", str(value or "").strip())
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return normalized or "na"


def _short_slug(value: str, *, max_length: int = 28) -> str:
    slug = slugify_fragment(value)
    if len(slug) <= max_length:
        return slug
    digest = hashlib.sha1(slug.encode("utf-8")).hexdigest()[:6]
    keep = max(8, max_length - 7)
    return f"{slug[:keep]}-{digest}"


def deck_key_from_path(pptx_path: Path, source_dir: Path = Path("study-docs")) -> str:
    try:
        relative = pptx_path.resolve().relative_to(source_dir.resolve())
        raw = str(relative.with_suffix("")).replace("\\", "-").replace("/", "-")
    except Exception:  # noqa: BLE001
        raw = f"{pptx_path.parent.name}-{pptx_path.stem}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]


DOC_ID_RE = re.compile(r"(KMSC)[-_ ]+(COCP)[-_ ]+(RTER)[-_ ]+(\d{3})", re.IGNORECASE)


def document_front_matter_id(pptx_path: Path) -> str:
    stem = normalize_text(pptx_path.stem)
    match = DOC_ID_RE.search(stem)
    if match:
        doc_id = "-".join(part.upper() for part in match.groups())
    else:
        doc_id = f"DOC-{deck_key_from_path(pptx_path)}"
    scope = ""
    if "서비스" in stem:
        scope = "SERVICE"
    elif "OCP" in stem.upper():
        scope = "OCP"
    kind = "RESULT" if "결과" in stem else ("PLAN" if "계획" in stem else "DOC")
    return "-".join(part for part in [doc_id, scope, kind, "FRONT"] if part)


def slide_fingerprint(slide_rows: list[dict[str, Any]]) -> str:
    digest = hashlib.sha1()
    for slide in slide_rows:
        digest.update(str(slide.get("slide_no") or "").encode("utf-8"))
        digest.update(str(slide.get("title") or "").encode("utf-8"))
        digest.update(str(slide.get("text_blob") or "").encode("utf-8"))
    return digest.hexdigest()


def relative_project_path(path_like: str | Path, *, project_root: Path) -> str:
    raw = str(path_like or "").strip()
    if not raw:
        return ""
    candidate = Path(raw)
    if not candidate.is_absolute():
        return candidate.as_posix()
    try:
        return candidate.resolve().relative_to(project_root.resolve()).as_posix()
    except Exception:  # noqa: BLE001
        return candidate.name


def build_chunk_identity(
    *,
    family: str,
    native_id: str,
    chunk_kind: str,
    variant: str | None = None,
    part: str | None = None,
    local_key: str | None = None,
) -> dict[str, str]:
    variant_token = slugify_fragment(variant or "default")
    part_token = slugify_fragment(part or "none")
    local_token = slugify_fragment(local_key or "root")
    semantic_bundle_id = f"{family}:{native_id}:{variant_token}:{part_token}"
    semantic_chunk_id = f"{semantic_bundle_id}:{chunk_kind}:{local_token}"
    digest = hashlib.sha1(semantic_chunk_id.encode("utf-8")).hexdigest()[:8]
    compact = [
        _short_slug(family, max_length=12),
        _short_slug(native_id, max_length=34),
        _short_slug(variant_token, max_length=12),
        _short_slug(part_token, max_length=12),
        _short_slug(chunk_kind, max_length=20),
    ]
    if local_token != "root":
        compact.append(_short_slug(local_token, max_length=28))
    chunk_id = "--".join(compact + [digest])
    return {
        "chunk_id": chunk_id,
        "bundle_id": semantic_bundle_id,
        "semantic_chunk_id": semantic_chunk_id,
        "variant": variant_token,
        "part_token": part_token,
        "local_key": local_token,
    }


def apply_chunk_identity(
    chunk: dict[str, Any],
    *,
    family: str,
    native_id: str,
    chunk_kind: str,
    variant: str | None = None,
    part: str | None = None,
    local_key: str | None = None,
    root_chunk_id: str | None = None,
) -> dict[str, Any]:
    identity = build_chunk_identity(
        family=family,
        native_id=native_id,
        chunk_kind=chunk_kind,
        variant=variant,
        part=part,
        local_key=local_key,
    )
    chunk["chunk_id"] = identity["chunk_id"]
    chunk["native_id"] = str(native_id or chunk.get("native_id") or "").strip() or identity["semantic_chunk_id"]
    chunk["variant"] = identity["variant"]
    chunk["bundle_id"] = identity["bundle_id"]
    chunk["semantic_chunk_id"] = identity["semantic_chunk_id"]
    chunk["root_chunk_id"] = str(root_chunk_id or chunk.get("root_chunk_id") or identity["chunk_id"])
    chunk["chunk_kind"] = str(chunk_kind or chunk.get("chunk_kind") or "summary")
    return chunk


def deck_metadata(*, pptx_path: Path, template_family: str, slide_rows: list[dict[str, Any]], chunk_count: int) -> dict[str, Any]:
    stat = pptx_path.stat()
    return {
        "source_pptx": str(pptx_path),
        "template_family": template_family,
        "slide_count": len(slide_rows),
        "chunk_count": chunk_count,
        "source_mtime_ns": stat.st_mtime_ns,
        "source_size_bytes": stat.st_size,
        "deck_fingerprint": slide_fingerprint(slide_rows),
    }


def chunk_stub(
    *,
    chunk_id: str,
    stage_id: str,
    title: str,
    body_md: str,
    source_pptx: Path,
    slide_no: int,
    png_path: str = "",
    structured: dict[str, Any] | None = None,
    variant: str | None = None,
) -> dict[str, Any]:
    return {
        "canonical_model": "course_chunk_v1",
        "chunk_id": chunk_id,
        "stage_id": stage_id,
        "title": title,
        "native_id": chunk_id,
        "variant": variant,
        "chunk_kind": "summary",
        "parent_chunk_id": None,
        "root_chunk_id": chunk_id,
        "bundle_id": "",
        "semantic_chunk_id": "",
        "child_chunk_ids": [],
        "body_md": body_md,
        "search_text": f"{title}\n{body_md}".strip(),
        "visual_text": "",
        "structured": structured or {},
        "facets": {},
        "slide_refs": [
            {
                "pptx": str(source_pptx),
                "slide_no": slide_no,
                "png_path": png_path,
                "caption": "",
            }
        ],
        "image_attachments": [],
        "visual_summary": None,
        "semantic_zones": [],
        "zone_relations": [],
        "related_official_docs": [],
        "source_pptx": str(source_pptx),
        "source_slide_range": [slide_no, slide_no],
    }


def collect_image_attachments(slide: dict[str, Any], *, source_pptx: Path) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    slide_no = int(slide.get("slide_no") or 0)
    for shape in slide.get("shapes", []):
        if not isinstance(shape, dict):
            continue
        if str(shape.get("shape_type") or "") != "picture":
            continue
        blob = shape.get("image_blob")
        if not isinstance(blob, (bytes, bytearray)):
            continue
        ext = str(shape.get("image_ext") or "png").strip().lower() or "png"
        attachments.append(
            {
                "source_pptx": str(source_pptx),
                "slide_no": slide_no,
                "shape_index": int(shape.get("shape_index") or 0),
                "ext": ext,
                "asset_path": "",
                "kind": "slide_image",
                "_blob": bytes(blob),
            }
        )
    return attachments


def finalize_chunk(
    chunk: dict[str, Any],
    *,
    native_id: str = "",
    visual_text: str = "",
) -> dict[str, Any]:
    normalized_native_id = str(native_id or chunk.get("native_id") or "").strip()
    body_text = str(chunk.get("body_md") or "").strip()
    title = str(chunk.get("title") or "").strip()
    visual_part = str(visual_text or chunk.get("visual_text") or "").strip()
    chunk["native_id"] = normalized_native_id or str(chunk.get("chunk_id") or "")
    chunk["visual_text"] = visual_part
    search_parts = [title, chunk["native_id"], body_text, visual_part]
    chunk["search_text"] = "\n".join(part for part in search_parts if part).strip()
    chunk["schema_version"] = str(chunk.get("schema_version") or "ppt_chunk_v1")
    chunk["source_kind"] = str(chunk.get("source_kind") or "project_artifact")
    chunk["root_chunk_id"] = str(chunk.get("root_chunk_id") or chunk.get("chunk_id") or "").strip() or None
    chunk["bundle_id"] = str(chunk.get("bundle_id") or "").strip()
    chunk["semantic_chunk_id"] = str(chunk.get("semantic_chunk_id") or "").strip()
    chunk["facets"] = chunk.get("facets") if isinstance(chunk.get("facets"), dict) else {}
    facet_terms: list[str] = []
    for value in chunk["facets"].values():
        if isinstance(value, list):
            facet_terms.extend(str(item).strip() for item in value if str(item).strip())
        elif str(value or "").strip():
            facet_terms.append(str(value).strip())
    chunk["index_texts"] = {
        "dense_text": "\n".join(part for part in [title, body_text, visual_part] if part).strip(),
        "sparse_text": "\n".join(dict.fromkeys(part for part in [chunk["native_id"], *facet_terms, title] if part)).strip(),
        "title_text": title,
        "visual_text": visual_part,
    }
    return chunk


__all__ = [
    "apply_chunk_identity",
    "build_chunk_identity",
    "chunk_stub",
    "collect_image_attachments",
    "deck_key_from_path",
    "deck_metadata",
    "document_front_matter_id",
    "finalize_chunk",
    "normalize_text",
    "relative_project_path",
    "slide_fingerprint",
    "slugify_fragment",
    "tokenize_korean_english",
]
