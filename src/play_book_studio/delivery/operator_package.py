from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

PACKAGE_ID = "ocp-4-20-operator-playbook-package"
PACKAGE_TITLE = "OpenShift 4.20 Operator Playbook Package"
PRIMARY_BOOK_SLUG = "operators"
SUPPORTING_BOOK_SLUGS = ("cli_tools", "web_console")
BRANCH_BOOK_SLUGS = ("disconnected_environments",)
OPERATORS_ENTITY_HUB = "operators-and-tooling"
PACKAGE_DIRNAME = "ocp_operator_package"
PACKAGE_ZIP_NAME = "ocp_operator_package.zip"
PACKAGE_MARKDOWN_NAME = "operator_package.md"
PACKAGE_MANIFEST_NAME = "package_manifest.json"
REPORT_JSON_NAME = "ocp_operator_package_report.json"
REPORT_MD_NAME = "ocp_operator_package_report.md"
OPERATOR_PACKET_ID = "ocp-operator-package"
OPERATOR_PACKET_TITLE = "OCP Operator Package"
OPERATOR_PACKET_PURPOSE = "현재 OpenShift 4.20 operator customer order delivery package"
OPERATOR_PACKET_JSON_NAME = "ocp_operator_package_packet.json"
OPERATOR_PACKET_MD_NAME = "ocp_operator_package_packet.md"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _relative_to_root(root_dir: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root_dir.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _book_entry(active_manifest: dict, slug: str) -> dict:
    entries = active_manifest.get("entries")
    if not isinstance(entries, list):
        raise ValueError("active runtime manifest entries are missing")
    for entry in entries:
        if isinstance(entry, dict) and str(entry.get("slug") or "") == slug:
            return entry
    raise ValueError(f"required runtime book is missing from active manifest: {slug}")


def _book_payload(*, root_dir: Path, active_group: str, entry: dict, role: str) -> dict:
    slug = str(entry["slug"])
    runtime_path = Path(str(entry["runtime_path"])).resolve()
    return {
        "slug": slug,
        "title": str(entry.get("title") or slug),
        "role": role,
        "runtime_markdown_path": _relative_to_root(root_dir, runtime_path),
        "runtime_viewer_path": f"/playbooks/wiki-runtime/active/{slug}/index.html",
        "package_book_path": f"books/{slug}.md",
        "promotion_strategy": str(entry.get("promotion_strategy") or ""),
        "active_group": active_group,
    }


def _build_package_markdown(*, payload: dict) -> str:
    lines: list[str] = [
        f"# {payload['title']}",
        "",
        f"- package_id: `{payload['package_id']}`",
        f"- generated_at_utc: `{payload['generated_at_utc']}`",
        f"- commercial_truth: `{payload['commercial_truth']}`",
        f"- source_runtime_group: `{payload['source_runtime_group']}`",
        "",
        "## Package Scope",
        "",
    ]

    for book in payload["books"]:
        lines.append(
            f"- `{book['role']}` · `{book['slug']}` · `{book['title']}` · viewer `{book['runtime_viewer_path']}`"
        )

    lines.extend(
        [
            "",
            "## Reading Sequence",
            "",
        ]
    )
    for index, item in enumerate(payload["reading_sequence"], start=1):
        lines.append(f"{index}. `{item['label']}` -> `{item['href']}`")

    lines.extend(
        [
            "",
            "## Key Runtime Sections",
            "",
        ]
    )
    for section in payload["key_runtime_sections"]:
        lines.append(f"- `{section['label']}` -> `{section['href']}`")

    lines.extend(
        [
            "",
            "## Key Figures",
            "",
        ]
    )
    for figure in payload["key_figures"]:
        lines.append(
            f"- `{figure['caption']}` -> `{figure['viewer_path']}` · section `{figure['section_href']}`"
        )

    lines.extend(
        [
            "",
            "## Included Files",
            "",
        ]
    )
    for artifact in payload["package_files"]:
        lines.append(f"- `{artifact}`")

    return "\n".join(lines) + "\n"


def _build_report_markdown(report: dict) -> str:
    lines = [
        "# OCP Operator Package Report",
        "",
        f"- status: `{report['status']}`",
        f"- package_id: `{report['package_id']}`",
        f"- output_dir: `{report['output_dir']}`",
        f"- zip_path: `{report['zip_path']}`",
        f"- book_count: `{report['book_count']}`",
        f"- key_section_count: `{report['key_section_count']}`",
        f"- key_figure_count: `{report['key_figure_count']}`",
        "",
        "## Included Books",
        "",
    ]
    for slug in report["book_slugs"]:
        lines.append(f"- `{slug}`")
    return "\n".join(lines) + "\n"


def _build_operator_packet_markdown(packet: dict) -> str:
    lines = [
        f"# {packet['title']}",
        "",
        f"- packet_id: `{packet['id']}`",
        f"- purpose: `{packet['purpose']}`",
        f"- commercial_truth: `{packet['commercial_truth']}`",
        f"- package_id: `{packet['package_id']}`",
        f"- package_manifest_path: `{packet['package_manifest_path']}`",
        f"- package_markdown_path: `{packet['package_markdown_path']}`",
        f"- package_zip_path: `{packet['package_zip_path']}`",
        f"- book_count: `{packet['book_count']}`",
        f"- key_section_count: `{packet['key_section_count']}`",
        f"- key_figure_count: `{packet['key_figure_count']}`",
        "",
        "## Included Books",
        "",
    ]
    for slug in packet["book_slugs"]:
        lines.append(f"- `{slug}`")
    lines.extend(
        [
            "",
            "## Reading Sequence",
            "",
        ]
    )
    for item in packet["reading_sequence"]:
        lines.append(f"- `{item['label']}` -> `{item['href']}`")
    return "\n".join(lines) + "\n"


def _build_buyer_bundle_markdown(bundle: dict) -> str:
    lines = [
        "# Buyer Packet Bundle Index",
        "",
        f"- current_stage: `{bundle['current_stage']}`",
        f"- commercial_truth: `{bundle['commercial_truth']}`",
        f"- packet_count: `{bundle['packet_count']}`",
        f"- all_ready: `{bundle['all_ready']}`",
        "",
        "## Recommended Order",
        "",
    ]
    for title in bundle.get("recommended_order") or []:
        lines.append(f"- {title}")
    lines.extend(["", "## Packets", ""])
    for packet in bundle.get("packets") or []:
        lines.extend(
            [
                f"### {packet['title']}",
                "",
                f"- purpose: {packet['purpose']}",
                f"- status: `{packet['status']}`",
                f"- json_path: `{packet['json_path']}`",
                f"- markdown_path: `{packet['markdown_path']}`",
                "",
            ]
        )
    lines.extend(["## Close", "", str(bundle.get("close") or "")])
    return "\n".join(lines) + "\n"


def _build_release_freeze_markdown(freeze: dict) -> str:
    runtime_snapshot = freeze.get("runtime_snapshot") if isinstance(freeze.get("runtime_snapshot"), dict) else {}
    product_gate = freeze.get("product_gate") if isinstance(freeze.get("product_gate"), dict) else {}
    release_gate = freeze.get("release_gate") if isinstance(freeze.get("release_gate"), dict) else {}
    lines = [
        "# Release Candidate Freeze Packet",
        "",
        f"- freeze_id: `{freeze['freeze_id']}`",
        f"- freeze_date: `{freeze['freeze_date']}`",
        f"- current_stage: `{freeze['current_stage']}`",
        f"- current_scope: `{freeze['current_scope']}`",
        f"- commercial_truth: `{freeze['commercial_truth']}`",
        f"- active_group: `{runtime_snapshot.get('active_group') or ''}`",
        f"- runtime_count: `{runtime_snapshot.get('runtime_count') or 0}`",
        "",
        "## Product Gate Snapshot",
        "",
        f"- scenario_count: `{product_gate.get('scenario_count') or 0}`",
        f"- pass_count: `{product_gate.get('pass_count') or 0}`",
        f"- pass_rate: `{product_gate.get('pass_rate')}`",
        f"- blockers: `{product_gate.get('blockers') or []}`",
        "",
        "## Release Gate Snapshot",
        "",
        f"- sell_now: `{release_gate.get('sell_now') or ''}`",
        f"- do_not_sell_yet: `{release_gate.get('do_not_sell_yet') or ''}`",
        f"- promotion_gate_count: `{release_gate.get('promotion_gate_count') or 0}`",
        f"- release_blocker_count: `{release_gate.get('release_blocker_count') or 0}`",
        "",
        "## Live Entry Points",
        "",
    ]
    for entry in freeze.get("live_entry_points") or []:
        lines.append(f"- {entry['label']}: `{entry['route']}`")
    lines.extend(["", "## Tomorrow Start Here", ""])
    for item in freeze.get("tomorrow_start_here") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Supporting Packets", ""])
    supporting_packets = freeze.get("supporting_packets") or []
    if not supporting_packets:
        lines.append("- none")
    else:
        for packet in supporting_packets:
            lines.append(
                f"- `{packet['title']}` · status=`{packet['status']}` · markdown=`{packet['markdown_path']}`"
            )
    lines.extend(["", "## Close", "", str(freeze.get("close") or "")])
    return "\n".join(lines) + "\n"


def _upsert_packet(packets: list[dict], packet: dict) -> list[dict]:
    filtered = [
        existing
        for existing in packets
        if isinstance(existing, dict) and str(existing.get("id") or "").strip() != packet["id"]
    ]
    filtered.append(packet)
    order = {
        "release-candidate-freeze": 0,
        OPERATOR_PACKET_ID: 1,
    }
    return sorted(
        filtered,
        key=lambda item: (
            order.get(str(item.get("id") or "").strip(), 99),
            str(item.get("title") or ""),
        ),
    )


def _sync_release_packets(
    root_dir: Path,
    *,
    package_payload: dict,
    report: dict,
    report_dir: Path,
) -> dict[str, str]:
    operator_packet_json_path = report_dir / OPERATOR_PACKET_JSON_NAME
    operator_packet_md_path = report_dir / OPERATOR_PACKET_MD_NAME
    buyer_bundle_json_path = report_dir / "buyer_packet_bundle_index.json"
    buyer_bundle_md_path = report_dir / "buyer_packet_bundle_index.md"
    freeze_json_path = report_dir / "release_candidate_freeze_packet.json"
    freeze_md_path = report_dir / "release_candidate_freeze_packet.md"

    operator_packet = {
        "id": OPERATOR_PACKET_ID,
        "title": OPERATOR_PACKET_TITLE,
        "purpose": OPERATOR_PACKET_PURPOSE,
        "status": "ok",
        "commercial_truth": package_payload["commercial_truth"],
        "package_id": package_payload["package_id"],
        "package_manifest_path": f"{package_payload['package_dir']}/{PACKAGE_MANIFEST_NAME}",
        "package_markdown_path": f"{package_payload['package_dir']}/{PACKAGE_MARKDOWN_NAME}",
        "package_zip_path": f"{package_payload['package_dir']}/{PACKAGE_ZIP_NAME}",
        "book_count": report["book_count"],
        "book_slugs": report["book_slugs"],
        "key_section_count": report["key_section_count"],
        "key_figure_count": report["key_figure_count"],
        "reading_sequence": package_payload["reading_sequence"],
        "json_path": _relative_to_root(root_dir, operator_packet_json_path),
        "markdown_path": _relative_to_root(root_dir, operator_packet_md_path),
    }
    _write_json(operator_packet_json_path, operator_packet)
    operator_packet_md_path.write_text(_build_operator_packet_markdown(operator_packet), encoding="utf-8")

    buyer_bundle = _read_json(buyer_bundle_json_path) if buyer_bundle_json_path.exists() else {}
    packets = buyer_bundle.get("packets") if isinstance(buyer_bundle.get("packets"), list) else []
    packets = _upsert_packet(packets, {
        "id": operator_packet["id"],
        "title": operator_packet["title"],
        "purpose": operator_packet["purpose"],
        "json_path": operator_packet["json_path"],
        "markdown_path": operator_packet["markdown_path"],
        "status": "ok",
    })
    buyer_bundle.update(
        {
            "status": "ok",
            "title": "Buyer Packet Bundle Index",
            "current_stage": str(buyer_bundle.get("current_stage") or "renewal_hardening_validation"),
            "commercial_truth": package_payload["commercial_truth"],
            "packet_count": len(packets),
            "all_ready": all(str(packet.get("status") or "") == "ok" for packet in packets),
            "recommended_order": [str(packet.get("title") or "") for packet in packets],
            "packets": packets,
            "close": "현재 active release packet 은 freeze packet과 OCP operator package packet이다. 추가 supporting packet은 실제 산출물이 다시 생길 때만 bundle에 포함한다.",
        }
    )
    _write_json(buyer_bundle_json_path, buyer_bundle)
    buyer_bundle_md_path.write_text(_build_buyer_bundle_markdown(buyer_bundle), encoding="utf-8")

    freeze = _read_json(freeze_json_path) if freeze_json_path.exists() else {}
    supporting_packets = freeze.get("supporting_packets") if isinstance(freeze.get("supporting_packets"), list) else []
    supporting_packets = _upsert_packet(
        supporting_packets,
        {
            "id": operator_packet["id"],
            "title": operator_packet["title"],
            "purpose": operator_packet["purpose"],
            "json_path": operator_packet["json_path"],
            "markdown_path": operator_packet["markdown_path"],
            "status": "ok",
        },
    )
    inputs = [
        str(item)
        for item in (freeze.get("inputs") or [])
        if str(item).strip()
    ]
    package_manifest_input = f"{package_payload['package_dir']}/{PACKAGE_MANIFEST_NAME}"
    if package_manifest_input not in inputs:
        inputs.append(package_manifest_input)
    tomorrow_start_here = [
        str(item)
        for item in (freeze.get("tomorrow_start_here") or [])
        if str(item).strip()
    ]
    package_tomorrow_line = "OCP Operator Package Packet 으로 현재 주문용 납품 범위와 zip 산출물을 확인한다."
    if package_tomorrow_line not in tomorrow_start_here:
        tomorrow_start_here.append(package_tomorrow_line)
    freeze["supporting_packets"] = supporting_packets
    freeze["inputs"] = inputs
    freeze["tomorrow_start_here"] = tomorrow_start_here
    _write_json(freeze_json_path, freeze)
    freeze_md_path.write_text(_build_release_freeze_markdown(freeze), encoding="utf-8")

    return {
        "operator_packet_json_path": _relative_to_root(root_dir, operator_packet_json_path),
        "operator_packet_markdown_path": _relative_to_root(root_dir, operator_packet_md_path),
        "buyer_bundle_json_path": _relative_to_root(root_dir, buyer_bundle_json_path),
        "freeze_json_path": _relative_to_root(root_dir, freeze_json_path),
    }


def build_operator_package(
    root_dir: Path,
    *,
    output_dir: Path | None = None,
    report_dir: Path | None = None,
    sync_release_packets: bool = False,
) -> dict[str, object]:
    root_dir = root_dir.resolve()
    active_manifest = _read_json(root_dir / "data" / "wiki_runtime_books" / "active_manifest.json")
    entity_hubs = _read_json(root_dir / "data" / "wiki_relations" / "entity_hubs.json")
    section_relation_index = _read_json(root_dir / "data" / "wiki_relations" / "section_relation_index.json")
    figure_section_index = _read_json(root_dir / "data" / "wiki_relations" / "figure_section_index.json")
    buyer_packet_bundle = _read_json(root_dir / "reports" / "build_logs" / "buyer_packet_bundle_index.json")

    selected_slugs = (
        PRIMARY_BOOK_SLUG,
        *SUPPORTING_BOOK_SLUGS,
        *BRANCH_BOOK_SLUGS,
    )
    active_group = str(active_manifest.get("active_group") or "active")
    books: list[dict] = []
    for slug in selected_slugs:
        role = "primary" if slug == PRIMARY_BOOK_SLUG else ("supporting" if slug in SUPPORTING_BOOK_SLUGS else "branch")
        books.append(
            _book_payload(
                root_dir=root_dir,
                active_group=active_group,
                entry=_book_entry(active_manifest, slug),
                role=role,
            )
        )

    hub_payload = entity_hubs.get(OPERATORS_ENTITY_HUB)
    if not isinstance(hub_payload, dict):
        raise ValueError(f"missing entity hub payload: {OPERATORS_ENTITY_HUB}")

    related_book_summaries: dict[str, str] = {}
    for item in hub_payload.get("related_books") or []:
        if isinstance(item, dict):
            related_book_summaries[str(item.get("href") or "")] = str(item.get("summary") or "")

    reading_sequence = []
    for index, book in enumerate(books, start=1):
        summary = related_book_summaries.get(book["runtime_viewer_path"], "")
        if book["slug"] == "disconnected_environments":
            summary = summary or "custom catalog 및 제한된 네트워크 운영 분기"
        reading_sequence.append(
            {
                "label": f"{index}. {book['title']}",
                "href": book["runtime_viewer_path"],
                "summary": summary,
            }
        )

    key_runtime_sections = []
    seen_section_hrefs: set[str] = set()
    for item in section_relation_index.get("by_entity", {}).get(OPERATORS_ENTITY_HUB) or []:
        if not isinstance(item, dict):
            continue
        href = str(item.get("href") or "")
        if not any(f"/{slug}/" in href for slug in selected_slugs):
            continue
        if href in seen_section_hrefs:
            continue
        seen_section_hrefs.add(href)
        key_runtime_sections.append(
            {
                "label": str(item.get("label") or href),
                "href": href,
                "summary": str(item.get("summary") or ""),
            }
        )

    key_figures = []
    for item in figure_section_index.get("by_slug", {}).get(PRIMARY_BOOK_SLUG) or []:
        if not isinstance(item, dict):
            continue
        key_figures.append(
            {
                "asset_name": str(item.get("asset_name") or ""),
                "caption": str(item.get("caption") or ""),
                "viewer_path": str(item.get("viewer_path") or ""),
                "section_href": str(item.get("section_href") or ""),
            }
        )

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    output_dir = (output_dir or root_dir / "artifacts" / "delivery" / PACKAGE_DIRNAME).resolve()
    report_dir = (report_dir or root_dir / "reports" / "build_logs").resolve()
    books_dir = output_dir / "books"
    output_dir.mkdir(parents=True, exist_ok=True)
    books_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = output_dir / PACKAGE_MANIFEST_NAME
    markdown_path = output_dir / PACKAGE_MARKDOWN_NAME
    zip_path = output_dir / PACKAGE_ZIP_NAME
    report_json_path = report_dir / REPORT_JSON_NAME
    report_md_path = report_dir / REPORT_MD_NAME

    for book in books:
        source_path = root_dir / book["runtime_markdown_path"]
        target_path = output_dir / book["package_book_path"]
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")

    package_files = [
        PACKAGE_MANIFEST_NAME,
        PACKAGE_MARKDOWN_NAME,
        *[book["package_book_path"] for book in books],
    ]
    payload = {
        "package_id": PACKAGE_ID,
        "title": PACKAGE_TITLE,
        "generated_at_utc": generated_at,
        "commercial_truth": str(buyer_packet_bundle.get("commercial_truth") or ""),
        "source_runtime_group": active_group,
        "source_runtime_manifest": "data/wiki_runtime_books/active_manifest.json",
        "package_dir": _relative_to_root(root_dir, output_dir),
        "books": books,
        "reading_sequence": reading_sequence,
        "key_runtime_sections": key_runtime_sections,
        "key_figures": key_figures,
        "package_files": package_files,
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_build_package_markdown(payload=payload), encoding="utf-8")

    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as archive:
        for relative_path in package_files:
            archive.write(output_dir / relative_path, arcname=relative_path)

    report: dict[str, object] = {
        "status": "ok",
        "package_id": PACKAGE_ID,
        "generated_at_utc": generated_at,
        "output_dir": _relative_to_root(root_dir, output_dir),
        "manifest_path": _relative_to_root(root_dir, manifest_path),
        "markdown_path": _relative_to_root(root_dir, markdown_path),
        "zip_path": _relative_to_root(root_dir, zip_path),
        "book_count": len(books),
        "book_slugs": [book["slug"] for book in books],
        "key_section_count": len(key_runtime_sections),
        "key_figure_count": len(key_figures),
    }
    if sync_release_packets:
        report["packet_sync"] = _sync_release_packets(
            root_dir,
            package_payload=payload,
            report=report,
            report_dir=report_dir,
        )
    report_json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report_md_path.write_text(_build_report_markdown(report), encoding="utf-8")
    return report
