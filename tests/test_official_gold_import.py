from __future__ import annotations

import json
from pathlib import Path

from play_book_studio.cli import build_parser
from play_book_studio.ingestion.official_gold_import import (
    _chunk_metadata,
    _heading_title,
    _learning_by_book_slug,
    _normalized_chunk_text,
    _official_chunk_metadata,
    _section_number,
    _section_path,
    _source_metadata,
    _source_anchor,
    _toc_path,
    build_official_gold_import_plan,
    write_official_embedding_chunks,
    write_official_text_layers,
)
from play_book_studio.ingestion.official_embedding_qdrant import build_official_embedding_qdrant_candidates

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_TMP = REPO_ROOT / "tmp" / "official_gold_import_tests"


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_build_official_gold_import_plan_groups_chunks_by_source():
    chunks_path = TEST_TMP / "chunks.jsonl"
    _write_jsonl(
        chunks_path,
        [
            {
                "chunk_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "book_slug": "architecture",
                "book_title": "Architecture",
                "source_id": "openshift:architecture",
                "text": "Architecture overview",
            },
            {
                "chunk_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "book_slug": "architecture",
                "book_title": "Architecture",
                "source_id": "openshift:architecture",
                "text": "Control plane",
            },
            {
                "chunk_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                "book_slug": "networking",
                "book_title": "Networking",
                "source_id": "openshift:networking",
                "text": "Routes",
            },
        ],
    )

    plan = build_official_gold_import_plan(chunks_path)

    assert plan["source_count"] == 2
    assert plan["chunk_count"] == 3
    assert plan["repository_slug"] == "official-docs"
    assert plan["visibility"] == "global_shared"
    assert plan["source_scope"] == "official_docs"
    assert [item["chunk_count"] for item in plan["sources"]] == [2, 1]
    architecture = next(item for item in plan["sources"] if item["book_slug"] == "architecture")
    assert architecture["category_key"] == "wiki"
    assert architecture["next_refs"]


def test_official_gold_import_parser_accepts_args():
    args = build_parser().parse_args(
        [
            "official-gold-import",
            "--root-dir",
            str(REPO_ROOT),
            "--chunks-path",
            "corpus/sources/official/imported-gold/gold_corpus_ko/chunks.jsonl",
            "--limit",
            "25",
            "--index",
            "--index-limit",
            "30000",
            "--refresh-qdrant-payloads",
            "--collection",
            "openshift_docs",
            "--refresh-limit",
            "30000",
            "--refresh-batch-size",
            "128",
            "--embedding-chunks-path",
            "corpus/sources/official/imported-gold/gold_corpus_ko/embeddings/embedding_chunks.jsonl",
            "--text-layers-path",
            "corpus/sources/official/imported-gold/gold_corpus_ko/text-layers/text_layers.jsonl",
            "--dry-run",
        ]
    )

    assert args.command == "official-gold-import"
    assert args.chunks_path == Path("corpus/sources/official/imported-gold/gold_corpus_ko/chunks.jsonl")
    assert args.limit == 25
    assert args.index is True
    assert args.index_limit == 30000
    assert args.refresh_qdrant_payloads is True
    assert args.collection == "openshift_docs"
    assert args.refresh_limit == 30000
    assert args.refresh_batch_size == 128
    assert args.embedding_chunks_path == Path(
        "corpus/sources/official/imported-gold/gold_corpus_ko/embeddings/embedding_chunks.jsonl"
    )
    assert args.text_layers_path == Path(
        "corpus/sources/official/imported-gold/gold_corpus_ko/text-layers/text_layers.jsonl"
    )
    assert args.dry_run is True


def test_official_embedding_qdrant_parser_accepts_args():
    args = build_parser().parse_args(
        [
            "official-embedding-qdrant-upsert",
            "--root-dir",
            str(REPO_ROOT),
            "--chunks-path",
            "corpus/sources/official/imported-gold/gold_corpus_ko/chunks.jsonl",
            "--embedding-chunks-path",
            "corpus/sources/official/imported-gold/gold_corpus_ko/embeddings/embedding_chunks.jsonl",
            "--collection",
            "openshift_docs",
            "--delete-skipped",
            "--sync-db",
            "--dry-run",
        ]
    )

    assert args.command == "official-embedding-qdrant-upsert"
    assert args.collection == "openshift_docs"
    assert args.delete_skipped is True
    assert args.sync_db is True
    assert args.dry_run is True


def test_official_gold_import_derives_section_metadata_without_body_prefixes():
    row = {
        "book_slug": "architecture",
        "book_title": "Architecture",
        "chapter": "1 Networking",
        "section": "1.1 Routes and services",
        "section_path": ["1 Networking", "1.1 Routes and services"],
        "anchor": "routes",
        "text": "Architecture\n1 Networking > 1.1 Routes and services\n\nRoute body text.",
    }
    section_path = _section_path(row)

    assert section_path == ["Networking", "Routes and services"]
    assert _section_number(row) == "1.1"
    assert _heading_title(row, section_path) == "Routes and services"
    assert _source_anchor(row) == "routes"
    assert _toc_path(row) == ["1 Networking", "1.1 Routes and services"]
    assert _normalized_chunk_text(row) == "Route body text."


def test_official_gold_import_normalizes_internal_code_markup():
    row = {
        "book_slug": "cli_tools",
        "book_title": "CLI tools",
        "section": "1.1 Check namespaces",
        "text": 'CLI tools\n\n[CODE language="shell-session"]\n$ oc get ns\n[/CODE]',
    }

    normalized = _normalized_chunk_text(row)

    assert "[CODE" not in normalized
    assert "[/CODE]" not in normalized
    assert "```shell" in normalized
    assert "$ oc get ns" in normalized


def test_official_gold_import_adds_learning_metadata_to_source_and_chunks():
    grouped = {
        "openshift:overview": [
            {"book_slug": "overview", "book_title": "Overview", "source_id": "openshift:overview"}
        ],
        "openshift:installation_overview": [
            {
                "book_slug": "installation_overview",
                "book_title": "Installation overview",
                "source_id": "openshift:installation_overview",
                "section": "1.1 Verify install",
                "cli_commands": ["oc get co"],
            }
        ],
    }
    learning_by_book = _learning_by_book_slug(grouped)

    source_metadata = _source_metadata(
        "openshift:overview",
        grouped["openshift:overview"],
        TEST_TMP / "chunks.jsonl",
        learning_by_book=learning_by_book,
    )
    chunk_metadata = _official_chunk_metadata(
        grouped["openshift:installation_overview"][0],
        ordinal=0,
        learning_by_book=learning_by_book,
    )

    assert source_metadata["learning"]["track"] == "ocp-foundation"
    assert source_metadata["learning"]["next_refs"][0]["book_slug"] == "installation_overview"
    assert source_metadata["category_key"] == "wiki"
    assert chunk_metadata["book_slug"] == "installation_overview"
    assert chunk_metadata["learning"]["section_role"] == "step"
    assert chunk_metadata["learning"]["command_hints"] == ["oc get co"]


def test_write_official_embedding_chunks_creates_clean_embedding_projection():
    chunks_path = TEST_TMP / "embedding-source.jsonl"
    output_path = TEST_TMP / "embeddings" / "embedding_chunks.jsonl"
    _write_jsonl(
        chunks_path,
        [
            {
                "chunk_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
                "book_slug": "storage",
                "book_title": "스토리지",
                "chapter": "1장. 스토리지 개요",
                "section": "1.1. PVC 확인",
                "section_path": ["1장. 스토리지 개요", "1.1. PVC 확인"],
                "source_url": "https://docs.redhat.com/example",
                "viewer_path": "/docs/ocp/4.20/ko/storage/index.html#pvc",
                "text": (
                    "스토리지\n"
                    "1장. 스토리지 개요 > 1.1. PVC 확인\n\n"
                    "PVC가 Pending이면 먼저 이벤트를 확인합니다.\n\n"
                    "[CODE language=\"shell-session\"]\n"
                    "$ oc describe pvc <pvc-name> -n <namespace>\n"
                    "[/CODE]\n\n"
                    "[TABLE]\n"
                    "상태 | 의미\n"
                    "Pending | 바인딩 실패\n"
                    "[/TABLE]\n"
                    "<a href=\"/docs/ocp/4.20/ko/storage/index.html#pvc\">Expand</a>"
                ),
                "chunk_type": "troubleshooting",
                "source_id": "openshift:storage",
                "source_lane": "official_ko",
                "source_type": "official_doc",
                "source_collection": "core",
                "product": "openshift",
                "version": "4.20",
                "locale": "ko",
            }
        ],
    )

    result = write_official_embedding_chunks(chunks_path, output_path)
    row = json.loads(output_path.read_text(encoding="utf-8").strip())

    assert result["input_chunk_count"] == 1
    assert result["embedding_chunk_count"] == 1
    assert row["text"] == row["embedding_text"]
    assert row["embedding_text"] == (
        "PVC가 Pending이면 먼저 이벤트를 확인합니다 "
        "$ oc describe pvc <pvc-name> -n <namespace> 상태 의미 Pending 바인딩 실패"
    )
    assert row["normalized_text"] == (
        "PVC가 Pending이면 먼저 이벤트를 확인합니다 "
        "oc describe pvc pvc name n namespace 상태 의미 Pending 바인딩 실패"
    )
    assert row["book_title"] == "스토리지"
    assert row["section_path"] == ["1장. 스토리지 개요", "PVC 확인"]
    assert row["section_number"] == "1.1"
    assert row["heading_title"] == "PVC 확인"
    assert row["breadcrumb"] == "1장. 스토리지 개요 > 1.1 PVC 확인"
    assert row["source_url"] == "https://docs.redhat.com/example"
    assert row["viewer_path"] == "/docs/ocp/4.20/ko/storage/index.html#pvc"
    assert "[CODE" not in row["embedding_text"]
    assert "[TABLE" not in row["embedding_text"]
    assert "```" not in row["embedding_text"]
    assert "<a href" not in row["embedding_text"]
    assert "/docs/ocp" not in row["embedding_text"]
    assert "|" not in row["embedding_text"]
    assert "\n" not in row["embedding_text"]
    assert "\n" not in row["normalized_text"]
    assert "|" not in row["normalized_text"]


def test_write_official_text_layers_exports_four_layer_contract():
    chunks_path = TEST_TMP / "text-layers-source.jsonl"
    output_path = TEST_TMP / "text-layers" / "text_layers.jsonl"
    _write_jsonl(
        chunks_path,
        [
            {
                "chunk_id": "12121212-1212-1212-1212-121212121212",
                "book_slug": "storage",
                "book_title": "스토리지",
                "chapter": "1장. 스토리지 개요",
                "section": "1.1. PVC 확인",
                "section_path": ["1장. 스토리지 개요", "1.1. PVC 확인"],
                "source_url": "https://docs.redhat.com/example",
                "viewer_path": "/docs/ocp/4.20/ko/storage/index.html#pvc",
                "text": (
                    "스토리지\n"
                    "1장. 스토리지 개요 > 1.1. PVC 확인\n\n"
                    "PVC가 Pending이면 먼저 이벤트를 확인합니다.\n\n"
                    "[CODE language=\"shell-session\"]\n"
                    "$ oc describe pvc <pvc-name> -n <namespace>\n"
                    "[/CODE]"
                ),
            }
        ],
    )

    result = write_official_text_layers(chunks_path, output_path)
    row = json.loads(output_path.read_text(encoding="utf-8").strip())

    assert result["text_layer_row_count"] == 1
    assert row["schema_version"] == "official_text_layers_v1"
    assert row["raw_text"].startswith("스토리지\n1장. 스토리지 개요")
    assert "[CODE" in row["raw_text"]
    assert row["markdown"].startswith("PVC가 Pending이면")
    assert "```shell" in row["markdown"]
    assert "$ oc describe pvc <pvc-name> -n <namespace>" in row["markdown"]
    assert row["normalized_text"] == "PVC가 Pending이면 먼저 이벤트를 확인합니다 oc describe pvc pvc name n namespace"
    assert row["embedding_text"] == "PVC가 Pending이면 먼저 이벤트를 확인합니다 $ oc describe pvc <pvc-name> -n <namespace>"


def test_write_official_embedding_chunks_skips_navigation_only_rows():
    chunks_path = TEST_TMP / "embedding-navigation-only-source.jsonl"
    output_path = TEST_TMP / "embeddings" / "embedding_navigation_only_chunks.jsonl"
    _write_jsonl(
        chunks_path,
        [
            {
                "chunk_id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
                "book_slug": "overview",
                "book_title": "개요",
                "chapter": "OpenShift Container Platform 소개",
                "section": "OpenShift Container Platform 소개",
                "section_path": ["OpenShift Container Platform 소개"],
                "text": "개요\nOpenShift Container Platform 소개",
            },
            {
                "chunk_id": "ffffffff-ffff-ffff-ffff-ffffffffffff",
                "book_slug": "overview",
                "book_title": "개요",
                "section": "OpenShift Container Platform 소개",
                "section_path": ["OpenShift Container Platform 소개"],
                "text": "개요\nOpenShift Container Platform 소개\n\n클러스터 관리를 설명합니다.",
            },
        ],
    )

    result = write_official_embedding_chunks(chunks_path, output_path)
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert result["input_chunk_count"] == 2
    assert result["embedding_chunk_count"] == 1
    assert result["skipped_empty_embedding_count"] == 1
    assert rows[0]["embedding_text"] == "클러스터 관리를 설명합니다"


def test_write_official_embedding_chunks_repairs_placeholder_artifacts():
    chunks_path = TEST_TMP / "embedding-placeholder-source.jsonl"
    output_path = TEST_TMP / "embeddings" / "embedding_placeholder_chunks.jsonl"
    _write_jsonl(
        chunks_path,
        [
            {
                "chunk_id": "11111111-1111-1111-1111-111111111111",
                "book_slug": "advanced_networking",
                "book_title": "고급 네트워킹",
                "section": "1.1. MTU",
                "section_path": ["1장. MTU", "1.1. MTU"],
                "text": (
                    "고급 네트워킹\n"
                    "1장. MTU > 1.1. MTU\n\n"
                    "interface>-mtu.conf 파일을 생성합니다. "
                    "<. overlay_to>로 지정합니다. "
                    "1. & lt;namespace_name& gt;을 설정합니다. "
                    "1. & `lt;node_name` >을 설정합니다. "
                    "< UUID&gt;의 값입니다. "
                    "2. < account_ key>에 대한 값을 제공합니다. "
                    "3. < 접미사 -rg 로 구성됩니다. resource_group_prefix> "
                    "component: () => <>Home</> "
                    "$ oc adm must-gather \\// <.> --timeout 30s "
                    "값은 <.\n<overlay_to>입니다. "
                    "세트는 <.\n<cluster-<id>-worker-<aws-region-az> 형식입니다."
                ),
            }
        ],
    )

    write_official_embedding_chunks(chunks_path, output_path)
    row = json.loads(output_path.read_text(encoding="utf-8").strip())

    assert row["embedding_text"] == (
        "interface mtu conf 파일을 생성합니다 overlay to 로 지정합니다 "
        "1 namespace name 을 설정합니다 1 node name 을 설정합니다 UUID 의 값입니다 "
        "2 account key 에 대한 값을 제공합니다 3 resource group prefix rg 로 구성됩니다 "
        "component Home $ oc adm must-gather --timeout 30s 값은 overlay to 입니다 "
        "세트는 cluster id worker aws region az 형식입니다"
    )


def test_write_official_embedding_chunks_suppresses_file_integrity_tail_only_rows():
    chunks_path = TEST_TMP / "embedding-file-integrity-tail-source.jsonl"
    output_path = TEST_TMP / "embeddings" / "embedding_file_integrity_tail_chunks.jsonl"
    _write_jsonl(
        chunks_path,
        [
            {
                "chunk_id": "33333333-3333-3333-3333-333333333333",
                "book_slug": "security_and_compliance",
                "book_title": "보안 및 컴플라이언스",
                "section": "6.6.5.2 FileIntegrityNodeStatus CR 실패 상태의 예",
                "section_path": ["6장. File Integrity Operator", "FileIntegrityNodeStatus CR 실패 상태의 예"],
                "text": "nIHMaRlS+so61EN8VOpg Events: <none> [/CODE]",
            }
        ],
    )

    result = write_official_embedding_chunks(chunks_path, output_path)
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert result["input_chunk_count"] == 1
    assert result["embedding_chunk_count"] == 0
    assert result["skipped_empty_embedding_count"] == 1
    assert rows == []


def test_write_official_embedding_chunks_removes_file_integrity_tail_prefix_and_sha_tail():
    chunks_path = TEST_TMP / "embedding-file-integrity-noise-source.jsonl"
    output_path = TEST_TMP / "embeddings" / "embedding_file_integrity_noise_chunks.jsonl"
    _write_jsonl(
        chunks_path,
        [
            {
                "chunk_id": "44444444-4444-4444-4444-444444444444",
                "book_slug": "security_and_compliance",
                "book_title": "보안 및 컴플라이언스",
                "section": "6.6.5.2 FileIntegrityNodeStatus CR 실패 상태의 예",
                "section_path": ["6장. File Integrity Operator", "FileIntegrityNodeStatus CR 실패 상태의 예"],
                "text": (
                    "nIHMaRlS+so61EN8VOpg Events: <none> [/CODE]\n\n"
                    "구성 맵 데이터 크기 제한으로 인해 1MB 이상의 AIDE 로그가 실패 구성 맵에 base64로 인코딩된 gzip 아카이브로 추가됩니다.\n"
                    "[CODE language=\"shell\"]\n"
                    "$ oc get cm <failure-cm-name> -o json | jq -r '.data.integritylog' | base64 -d | gunzip\n"
                    "[/CODE]"
                ),
            },
            {
                "chunk_id": "55555555-5555-5555-5555-555555555555",
                "book_slug": "security_and_compliance",
                "book_title": "보안 및 컴플라이언스",
                "section": "6.6.5.2 FileIntegrityNodeStatus CR 실패 상태의 예",
                "section_path": ["6장. File Integrity Operator", "FileIntegrityNodeStatus CR 실패 상태의 예"],
                "text": (
                    "openshift.io/files-removed: 0 Data integritylog: ------ AIDE 0.15.1 found differences "
                    "between database and filesystem!! Start timestamp: 2020-09-15 12:58:15 Summary: "
                    "Total number of files: 31553 Added files: 0 Removed files: 0 Changed files: 1 "
                    "File: /hostroot/etc/resolv.conf SHA512 : sTQYpB/AL7FeoGtu/1g7opv6C+KT1CBJ, qAeM+a8yTgHP"
                ),
            },
        ],
    )

    write_official_embedding_chunks(chunks_path, output_path)
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert len(rows) == 2
    assert "nIHMaRlS" not in rows[0]["embedding_text"]
    assert "Events none" not in rows[0]["embedding_text"]
    assert "oc get cm" in rows[0]["embedding_text"]
    assert "integritylog" in rows[0]["embedding_text"]
    assert "base64" in rows[0]["embedding_text"]
    assert "gunzip" in rows[0]["embedding_text"]
    assert "openshift io files removed" not in rows[1]["embedding_text"]
    assert "Data integritylog AIDE" in rows[1]["embedding_text"]
    assert "SHA512" not in rows[1]["embedding_text"]
    assert "sTQYpB" not in rows[1]["embedding_text"]


def test_build_official_embedding_qdrant_candidates_uses_clean_text_without_raw_payload():
    chunks_path = TEST_TMP / "qdrant-source.jsonl"
    embedding_path = TEST_TMP / "embeddings" / "qdrant-embedding.jsonl"
    source_row = {
        "chunk_id": "22222222-2222-2222-2222-222222222222",
        "book_slug": "storage",
        "book_title": "스토리지",
        "chapter": "1장. 스토리지",
        "section": "1.1 PVC Pending",
        "section_path": ["1장. 스토리지", "1.1 PVC Pending"],
        "section_id": "storage:pvc-pending",
        "anchor": "pvc-pending",
        "source_url": "https://docs.redhat.com/example",
        "viewer_path": "/docs/ocp/4.20/ko/storage/index.html#pvc-pending",
        "source_id": "openshift:storage",
        "source_lane": "official_ko",
        "source_type": "official_doc",
        "source_collection": "core",
        "review_status": "approved",
        "citation_eligible": True,
        "product": "openshift",
        "version": "4.20",
        "locale": "ko",
        "text": "스토리지\n1장. 스토리지 > 1.1 PVC Pending\n\n$ oc describe pvc <pvc-name>",
    }
    _write_jsonl(chunks_path, [source_row])
    write_official_embedding_chunks(chunks_path, embedding_path)

    candidates = build_official_embedding_qdrant_candidates(
        chunks_path=chunks_path,
        embedding_chunks_path=embedding_path,
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.embedding_text == "$ oc describe pvc <pvc-name>"
    assert candidate.payload["text"] == "$ oc describe pvc <pvc-name>"
    assert candidate.payload["text_fields"]["embedding_text"] == "$ oc describe pvc <pvc-name>"
    assert candidate.payload["text_fields"]["normalized_text"] == "oc describe pvc pvc name"
    assert candidate.payload["text"] == candidate.payload["text_fields"]["embedding_text"]
    assert candidate.payload["chunk_metadata"]["text_layers"]["embedding_text"] == "$ oc describe pvc <pvc-name>"
    assert candidate.payload["chunk_metadata"]["text_layers"]["normalized_text"] == "oc describe pvc pvc name"
    assert "raw_text" not in json.dumps(candidate.payload, ensure_ascii=False)
    assert candidate.payload["source"]["corpus_scope"] == "official_docs"
