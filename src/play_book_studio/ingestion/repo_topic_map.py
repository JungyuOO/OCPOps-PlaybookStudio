from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import yaml

from .source_first import SOURCE_BRANCH, SOURCE_REPO_URL, source_mirror_root

TOPIC_MAP_RELATIVE_PATH = Path("_topic_maps") / "_topic_map.yml"
TARGET_DISTRO = "openshift-enterprise"


@dataclass(frozen=True, slots=True)
class TopicMapEntry:
    slug: str
    title: str
    source_relative_path: str
    source_repo: str
    source_branch: str
    topic_path: tuple[str, ...]
    section_family: tuple[str, ...]


def _distros_allow(node: dict[str, Any], *, target_distro: str = TARGET_DISTRO) -> bool:
    raw = str(node.get("Distros") or "").strip()
    if not raw:
        return True
    allowed = {item.strip() for item in raw.split(",") if item.strip()}
    return target_distro in allowed


def _source_file_relative_path(group_dir: str, file_stem: str) -> str:
    normalized_dir = str(group_dir or "").strip().strip("/\\")
    normalized_file = str(file_stem or "").strip().strip("/\\")
    if normalized_file.endswith(".adoc"):
        relative = Path(normalized_dir) / normalized_file
    else:
        relative = Path(normalized_dir) / f"{normalized_file}.adoc"
    return str(relative).replace("\\", "/")


def _slug_from_relative_path(relative_path: str) -> str:
    stem = Path(relative_path).with_suffix("")
    tokens = [part.strip().lower() for part in stem.parts if part.strip()]
    raw = "__".join(tokens)
    return re.sub(r"[^a-z0-9_]+", "_", raw).strip("_")


def _join_group_dir(parent_dir: str, child_dir: str) -> str:
    normalized_parent = str(parent_dir or "").strip().strip("/\\")
    normalized_child = str(child_dir or "").strip().strip("/\\")
    if not normalized_parent:
        return normalized_child
    if not normalized_child:
        return normalized_parent
    return str(Path(normalized_parent) / normalized_child).replace("\\", "/")


def _walk_topics(
    *,
    source_root: Path,
    group_dir: str,
    topics: list[dict[str, Any]],
    section_family: tuple[str, ...],
    topic_path: tuple[str, ...],
    sink: list[TopicMapEntry],
    seen_relative_paths: set[str],
) -> None:
    for topic in topics:
        if not isinstance(topic, dict) or not _distros_allow(topic):
            continue
        topic_name = str(topic.get("Name") or "").strip()
        current_dir = _join_group_dir(group_dir, str(topic.get("Dir") or "").strip())
        if not current_dir:
            current_dir = str(group_dir or "").strip()
        current_topic_path = topic_path + ((topic_name,) if topic_name else ())
        file_stem = str(topic.get("File") or "").strip()
        if file_stem:
            relative_path = _source_file_relative_path(current_dir, file_stem)
            source_file = source_root / relative_path
            if source_file.exists() and source_file.is_file() and relative_path not in seen_relative_paths:
                seen_relative_paths.add(relative_path)
                sink.append(
                    TopicMapEntry(
                        slug=_slug_from_relative_path(relative_path),
                        title=topic_name or Path(relative_path).stem,
                        source_relative_path=relative_path,
                        source_repo=SOURCE_REPO_URL,
                        source_branch=SOURCE_BRANCH,
                        topic_path=current_topic_path,
                        section_family=section_family,
                    )
                )
        nested_topics = topic.get("Topics")
        if isinstance(nested_topics, list) and nested_topics:
            _walk_topics(
                source_root=source_root,
                group_dir=current_dir,
                topics=nested_topics,
                section_family=section_family,
                topic_path=current_topic_path,
                sink=sink,
                seen_relative_paths=seen_relative_paths,
            )


def discover_enterprise_topic_map_entries(root_dir: Path) -> list[TopicMapEntry]:
    mirror_root = source_mirror_root(root_dir)
    topic_map_path = mirror_root / TOPIC_MAP_RELATIVE_PATH
    records = list(yaml.safe_load_all(topic_map_path.read_text(encoding="utf-8")))
    entries: list[TopicMapEntry] = []
    seen_relative_paths: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or not _distros_allow(record):
            continue
        group_name = str(record.get("Name") or "").strip()
        group_dir = str(record.get("Dir") or "").strip()
        topics = record.get("Topics")
        if not isinstance(topics, list) or not group_dir:
            continue
        _walk_topics(
            source_root=mirror_root,
            group_dir=group_dir,
            topics=topics,
            section_family=((group_name,) if group_name else ()),
            topic_path=((group_name,) if group_name else ()),
            sink=entries,
            seen_relative_paths=seen_relative_paths,
        )
    return entries


__all__ = [
    "TOPIC_MAP_RELATIVE_PATH",
    "TARGET_DISTRO",
    "TopicMapEntry",
    "discover_enterprise_topic_map_entries",
]
