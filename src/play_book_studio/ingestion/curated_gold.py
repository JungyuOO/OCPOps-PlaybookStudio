"""수동 검토를 거쳐 승격한 curated gold 산출물을 active silver/gold에 주입한다."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from play_book_studio.canonical import (
    AstProvenance,
    CanonicalDocumentAst,
    CanonicalSectionAst,
    CodeBlock,
    NoteBlock,
    ParagraphBlock,
    PrerequisiteBlock,
    ProcedureBlock,
    ProcedureStep,
    project_playbook_document,
)
from play_book_studio.config.settings import Settings
from play_book_studio.config.validation import read_jsonl
from play_book_studio.contextual_enrichment import enrich_contextual_row

from .chunking import chunk_sections
from .graph_sidecar import (
    graph_sidecar_compact_artifact_status,
    refresh_active_runtime_graph_artifacts,
)
from .manifest import read_manifest, write_manifest
from .models import SOURCE_STATE_BLOCKED, SourceManifestEntry
from .normalize import project_normalized_sections
from .synthesis_lane import synthesis_lane_report_path, write_synthesis_lane_outputs


CURATED_ETCD_BOOK_SLUG = "etcd"
CURATED_ETCD_TITLE = "etcd 백업 및 복구 플레이북"
CURATED_ETCD_SOURCE_URL = (
    "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/"
    "html-single/etcd/index"
)
CURATED_ETCD_TRANSLATION_SOURCE_URL = (
    "https://docs.redhat.com/en/documentation/openshift_container_platform/4.20/"
    "html-single/etcd/index"
)
CURATED_ETCD_INDEX_URL = (
    "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/"
)
CURATED_ETCD_VIEWER_BASE_PATH = "/docs/ocp/4.20/ko/etcd/index.html"
CURATED_ETCD_SOURCE_ID = "openshift_container_platform:4.20:ko:etcd:curated_gold_v1"
CURATED_ETCD_UPDATED_AT = "2026-04-10T00:00:00Z"
CURATED_ETCD_LICENSE = "OpenShift documentation is licensed under the Apache License 2.0."
CURATED_PUBLIC_PACK_VERSION = "4.20"
CURATED_PUBLIC_PACK_ID = "openshift_container_platform-4.20-core"
CURATED_PUBLIC_PACK_LABEL = "OpenShift 4.20 Gold Dataset"


@dataclass(frozen=True)
class CuratedGoldSpec:
    book_slug: str
    title: str
    source_url: str
    translation_source_url: str
    index_url: str
    viewer_base_path: str
    source_id: str
    updated_at: str
    license_or_terms: str
    original_title: str
    vendor_title: str
    approval_notes: str
    notes: tuple[str, ...]
    trust_score: float = 0.97
    source_state_reason: str = "curated_manual_review_promoted_from_bronze_bundle"


def _provenance_notes() -> tuple[str, ...]:
    return (
        "curated_etcd_gold_v1",
        "manual_review_promoted_from_source_bundle",
        "official_ko_en_and_repo_sidecars_reviewed",
    )


CURATED_ETCD_SPEC = CuratedGoldSpec(
    book_slug=CURATED_ETCD_BOOK_SLUG,
    title=CURATED_ETCD_TITLE,
    source_url=CURATED_ETCD_SOURCE_URL,
    translation_source_url=CURATED_ETCD_TRANSLATION_SOURCE_URL,
    index_url=CURATED_ETCD_INDEX_URL,
    viewer_base_path=CURATED_ETCD_VIEWER_BASE_PATH,
    source_id=CURATED_ETCD_SOURCE_ID,
    updated_at=CURATED_ETCD_UPDATED_AT,
    license_or_terms=CURATED_ETCD_LICENSE,
    original_title="Backing up and restoring etcd data / Disaster recovery",
    vendor_title="etcd",
    approval_notes="curated etcd gold sample from official KO/EN docs and repo sidecars",
    notes=_provenance_notes(),
    trust_score=0.98,
)


def _curated_public_provenance_defaults(source_id: str) -> dict[str, object]:
    return {
        "parsed_artifact_id": f"parsed:{source_id}",
        "tenant_id": "public",
        "workspace_id": "core",
        "pack_id": CURATED_PUBLIC_PACK_ID,
        "pack_version": CURATED_PUBLIC_PACK_VERSION,
        "bundle_scope": "official",
        "classification": "public",
        "access_groups": ("public",),
        "provider_egress_policy": "unspecified",
        "approval_state": "approved",
        "publication_state": "published",
        "redaction_state": "not_required",
        "citation_eligible": True,
        "citation_block_reason": "",
    }


def _curated_provenance_fingerprint(spec: CuratedGoldSpec) -> str:
    return hashlib.sha256(
        "|".join(
            (
                spec.source_id,
                spec.source_url,
                spec.translation_source_url,
                "curated_gold_v1",
            )
        ).encode("utf-8")
    ).hexdigest()


def _curated_translation_fingerprint(spec: CuratedGoldSpec) -> str:
    return hashlib.sha256(spec.translation_source_url.encode("utf-8")).hexdigest()


def _build_curated_provenance(spec: CuratedGoldSpec) -> AstProvenance:
    return AstProvenance(
        source_id=spec.source_id,
        source_lane="applied_playbook",
        source_type="manual_synthesis",
        source_collection="core",
        product="openshift",
        version="4.20",
        locale="ko",
        original_title=spec.original_title,
        legal_notice_url="",
        license_or_terms=spec.license_or_terms,
        review_status="approved",
        trust_score=spec.trust_score,
        verifiability="anchor_backed",
        updated_at=spec.updated_at,
        capture_uri=spec.source_url,
        source_fingerprint=_curated_provenance_fingerprint(spec),
        parser_name="curated_gold",
        parser_version="v1",
        source_state=SOURCE_STATE_BLOCKED,
        content_status="approved_ko",
        translation_stage="approved_ko",
        translation_source_language="en",
        translation_target_language="ko",
        translation_source_url=spec.translation_source_url,
        translation_source_fingerprint=_curated_translation_fingerprint(spec),
        **_curated_public_provenance_defaults(spec.source_id),
        notes=spec.notes,
    )


def _section_for(
    spec: CuratedGoldSpec,
    *,
    ordinal: int,
    heading: str,
    anchor: str,
    semantic_role: str,
    blocks: tuple[object, ...],
    path: tuple[str, ...] | None = None,
    level: int = 2,
) -> CanonicalSectionAst:
    resolved_path = path or (heading,)
    return CanonicalSectionAst(
        section_id=f"{spec.book_slug}:{anchor}",
        ordinal=ordinal,
        heading=heading,
        level=level,
        path=resolved_path,
        anchor=anchor,
        source_url=spec.source_url,
        viewer_path=f"{spec.viewer_base_path}#{anchor}",
        semantic_role=semantic_role,
        blocks=blocks,
    )


def _build_curated_document(
    spec: CuratedGoldSpec,
    sections: tuple[CanonicalSectionAst, ...],
) -> CanonicalDocumentAst:
    return CanonicalDocumentAst(
        doc_id=spec.source_id,
        book_slug=spec.book_slug,
        title=spec.title,
        source_type="web",
        source_url=spec.source_url,
        viewer_base_path=spec.viewer_base_path,
        source_language="ko",
        display_language="ko",
        translation_status="approved_ko",
        pack_id="openshift-4-20-core",
        pack_label=CURATED_PUBLIC_PACK_LABEL,
        inferred_product="openshift",
        inferred_version="4.20",
        sections=sections,
        notes=(),
        provenance=_build_curated_provenance(spec),
    )


def _curated_manifest_source_fingerprint(spec: CuratedGoldSpec) -> str:
    return hashlib.sha256(
        "|".join(
            (
                spec.book_slug,
                spec.source_url,
                spec.translation_source_url,
                spec.source_id,
            )
        ).encode("utf-8")
    ).hexdigest()


def _curated_manifest_entry(spec: CuratedGoldSpec) -> SourceManifestEntry:
    return SourceManifestEntry(
        product_slug="openshift_container_platform",
        ocp_version="4.20",
        docs_language="ko",
        source_kind="html-single",
        book_slug=spec.book_slug,
        title=spec.title,
        index_url=spec.index_url,
        source_url=spec.source_url,
        resolved_source_url=spec.source_url,
        resolved_language="ko",
        source_state=SOURCE_STATE_BLOCKED,
        source_state_reason=spec.source_state_reason,
        catalog_source_label="curated gold manual synthesis",
        viewer_path=spec.viewer_base_path,
        high_value=True,
        vendor_title=spec.vendor_title,
        content_status="approved_ko",
        citation_eligible=True,
        citation_block_reason="",
        viewer_strategy="internal_text",
        body_language_guess="ko",
        hangul_section_ratio=1.0,
        hangul_chunk_ratio=1.0,
        fallback_detected=False,
        source_fingerprint=_curated_manifest_source_fingerprint(spec),
        approval_status="approved",
        approval_notes=spec.approval_notes,
        source_id=spec.source_id,
        source_lane="applied_playbook",
        source_type="manual_synthesis",
        source_collection="core",
        legal_notice_url="",
        original_title=spec.original_title,
        license_or_terms=spec.license_or_terms,
        review_status="approved",
        trust_score=spec.trust_score,
        verifiability="anchor_backed",
        updated_at=spec.updated_at,
        translation_source_language="en",
        translation_target_language="ko",
        translation_source_url=spec.translation_source_url,
        translation_source_fingerprint=_curated_translation_fingerprint(spec),
        translation_stage="approved_ko",
    )


def _build_etcd_provenance() -> AstProvenance:
    return _build_curated_provenance(CURATED_ETCD_SPEC)


def _section(
    *,
    ordinal: int,
    heading: str,
    anchor: str,
    semantic_role: str,
    blocks: tuple[object, ...],
    path: tuple[str, ...] | None = None,
    level: int = 2,
) -> CanonicalSectionAst:
    return _section_for(
        CURATED_ETCD_SPEC,
        ordinal=ordinal,
        heading=heading,
        anchor=anchor,
        semantic_role=semantic_role,
        blocks=blocks,
        path=path,
        level=level,
    )


def build_curated_etcd_document() -> CanonicalDocumentAst:
    sections = (
        _section(
            ordinal=1,
            heading="etcd 운영 개요",
            anchor="etcd-operations-overview",
            semantic_role="overview",
            blocks=(
                ParagraphBlock(
                    "etcd는 OpenShift 클러스터의 리소스 상태를 저장하는 키-값 저장소입니다. "
                    "이 플레이북은 운영자가 실제로 자주 수행하는 백업, 복원, 쿼럼 손실 복구를 "
                    "한 화면에서 따라갈 수 있도록 정리한 curated gold 수동서입니다."
                ),
                ParagraphBlock(
                    "핵심 원칙은 세 가지입니다. 백업은 단일 컨트롤 플레인 노드에서 한 번만 수행하고, "
                    "복원은 마지막 수단으로만 사용하며, 복구 후에는 반드시 클러스터 안정화까지 확인합니다."
                ),
            ),
        ),
        _section(
            ordinal=2,
            heading="백업 전에 확인할 것",
            anchor="etcd-backup-prerequisites",
            semantic_role="concept",
            blocks=(
                PrerequisiteBlock(
                    items=(
                        "컨트롤 플레인 노드에 SSH로 접속할 수 있어야 합니다.",
                        "백업 파일을 클러스터 외부의 안전한 위치에 보관할 계획이 있어야 합니다.",
                        "가능하면 I/O 영향이 적은 시간대에 수행합니다.",
                    )
                ),
                ParagraphBlock(
                    "etcd 백업은 설치 후 첫 인증서 회전이 끝나기 전에는 수행하면 안 됩니다. "
                    "인증서 회전은 일반적으로 설치 후 24시간 뒤에 완료됩니다."
                ),
                ParagraphBlock(
                    "클러스터 업데이트 전에 반드시 백업을 보관해야 합니다. 복원할 때는 "
                    "반드시 같은 z-stream 릴리스에서 만든 백업을 사용해야 합니다."
                ),
                NoteBlock(
                    title="중요",
                    variant="important",
                    text=(
                        "백업 스크립트는 컨트롤 플레인 호스트 한 곳에서 한 번만 실행합니다. "
                        "모든 컨트롤 플레인 노드에서 각각 백업하면 안 됩니다."
                    ),
                ),
            ),
        ),
        _section(
            ordinal=3,
            heading="etcd 백업 절차",
            anchor="etcd-backup-procedure",
            semantic_role="procedure",
            blocks=(
                ProcedureBlock(
                    steps=(
                        ProcedureStep(1, "백업을 수행할 컨트롤 플레인 노드 하나에 SSH로 접속합니다."),
                        ProcedureStep(2, "`oc debug --as-root node/<control-plane-node>`로 호스트 디버그 셸을 엽니다."),
                        ProcedureStep(3, "`chroot /host`로 호스트 파일시스템으로 전환합니다."),
                        ProcedureStep(
                            4,
                            "`cluster-backup.sh` 스크립트를 실행하여 백업 디렉터리에 snapshot과 정적 pod 리소스를 생성합니다.",
                        ),
                    )
                ),
                CodeBlock(
                    language="bash",
                    caption="etcd 백업 핵심 명령",
                    code=(
                        "oc debug --as-root node/<control-plane-node>\n"
                        "chroot /host\n"
                        "/usr/local/bin/cluster-backup.sh /home/core/assets/backup"
                    ),
                ),
                NoteBlock(
                    title="작은 정보",
                    variant="tip",
                    text=(
                        "`cluster-backup.sh`는 `etcdctl snapshot save`를 감싼 스크립트이며, "
                        "스냅샷과 정적 pod 리소스를 함께 보관합니다."
                    ),
                ),
            ),
        ),
        _section(
            ordinal=4,
            heading="백업 결과 검증",
            anchor="etcd-backup-verification",
            semantic_role="procedure",
            blocks=(
                ParagraphBlock(
                    "백업이 끝나면 지정한 디렉터리에 `snapshot_<timestamp>.db` 와 "
                    "`static_kuberesources_<timestamp>.tar.gz` 두 파일이 함께 있어야 합니다."
                ),
                CodeBlock(
                    language="bash",
                    caption="백업 디렉터리 확인",
                    code="ls -lh /home/core/assets/backup",
                ),
                ParagraphBlock(
                    "`snapshot_<timestamp>.db` 는 etcd 스냅샷이고, "
                    "`static_kuberesources_<timestamp>.tar.gz` 는 정적 pod 리소스와 필요 시 암호화 키를 포함합니다."
                ),
                ParagraphBlock(
                    "복원 시에는 반드시 두 파일이 같은 백업 시점의 한 쌍이어야 합니다. "
                    "둘 중 하나라도 없거나 시점이 다르면 복원을 진행하지 마십시오."
                ),
            ),
        ),
        _section(
            ordinal=5,
            heading="복원을 시작하기 전에 판단할 것",
            anchor="etcd-restore-decision",
            semantic_role="concept",
            blocks=(
                ParagraphBlock(
                    "이전 클러스터 상태로의 복원은 파괴적이고 불안정한 작업이므로 마지막 수단으로만 사용합니다."
                ),
                ParagraphBlock(
                    "복원에는 적어도 하나의 정상 컨트롤 플레인 호스트와, 같은 z-stream 릴리스에서 만든 "
                    "`snapshot_<timestamp>.db` 와 `static_kuberesources_<timestamp>.tar.gz` 가 필요합니다."
                ),
                NoteBlock(
                    title="주의",
                    variant="warning",
                    text=(
                        "과반수 컨트롤 플레인 노드가 아직 살아 있고 etcd quorum이 유지된다면, "
                        "전체 복원보다 단일 비정상 etcd 멤버 교체 절차를 우선 검토하십시오."
                    ),
                ),
            ),
        ),
        _section(
            ordinal=6,
            heading="이전 상태로 복원하는 절차",
            anchor="etcd-restore-procedure",
            semantic_role="procedure",
            blocks=(
                ProcedureBlock(
                    steps=(
                        ProcedureStep(
                            1,
                            "복구 대상 노드의 `/home/core/<etcd_backup_directory>` 아래에 백업 디렉터리를 준비합니다.",
                        ),
                        ProcedureStep(
                            2,
                            "`cluster-restore.sh` 로 이전 백업에서 클러스터 상태를 복원합니다.",
                        ),
                        ProcedureStep(
                            3,
                            "`oc adm wait-for-stable-cluster` 로 컨트롤 플레인이 안정화될 때까지 모니터링합니다.",
                        ),
                    )
                ),
                CodeBlock(
                    language="bash",
                    caption="이전 상태 복원 명령",
                    code="sudo -E /usr/local/bin/cluster-restore.sh /home/core/<etcd_backup_directory>",
                ),
                CodeBlock(
                    language="bash",
                    caption="복구 진행 상태 확인",
                    code="oc adm wait-for-stable-cluster",
                ),
                NoteBlock(
                    title="참고",
                    variant="note",
                    text="컨트롤 플레인 복구에는 최대 15분 정도 걸릴 수 있습니다.",
                ),
            ),
        ),
        _section(
            ordinal=7,
            heading="쿼럼 손실 복원",
            anchor="etcd-quorum-restore",
            semantic_role="procedure",
            blocks=(
                ParagraphBlock(
                    "quorum 손실로 클러스터가 오프라인이 되고 OpenShift API가 읽기 전용이 되었다면, "
                    "이전 상태 복원 대신 `quorum-restore.sh` 절차를 검토합니다."
                ),
                PrerequisiteBlock(
                    items=(
                        "적어도 하나의 정상 컨트롤 플레인 호스트가 있어야 합니다.",
                        "quorum 복원은 백업에서 이전 상태로 되돌리는 절차와 목적이 다릅니다.",
                    )
                ),
                CodeBlock(
                    language="bash",
                    caption="quorum 손실 복원 명령",
                    code="sudo -E /usr/local/bin/quorum-restore.sh",
                ),
                ParagraphBlock(
                    "quorum 복원 후에는 다른 온라인 노드가 새 etcd 클러스터에 다시 참여할 때까지 몇 분 정도 걸릴 수 있습니다."
                ),
            ),
        ),
        _section(
            ordinal=8,
            heading="작업 후 확인과 다음 분기",
            anchor="etcd-next-branches",
            semantic_role="reference",
            blocks=(
                ParagraphBlock(
                    "복원 또는 quorum 복원 뒤에는 먼저 `oc adm wait-for-stable-cluster` 가 성공하는지 확인하고, "
                    "그 다음 etcd 관련 Operator 상태와 control plane 노드 상태를 점검합니다."
                ),
                ParagraphBlock(
                    "백업 디렉터리 파일이 맞지 않으면 복원을 강행하지 말고 백업 시점을 다시 확인합니다."
                ),
                ParagraphBlock(
                    "복원 과정에서 인증서 만료 문제가 드러나면 expired control plane certificates 복구 절차를 다음 분기로 선택합니다."
                ),
            ),
        ),
    )
    return _build_curated_document(CURATED_ETCD_SPEC, sections)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_jsonl_safe(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return read_jsonl(path)


def _upsert_rows(
    existing: list[dict[str, object]],
    new_rows: list[dict[str, object]],
    *,
    key_field: str,
) -> list[dict[str, object]]:
    new_keys = {str(row[key_field]) for row in new_rows}
    kept = [row for row in existing if str(row.get(key_field, "")) not in new_keys]
    return kept + new_rows


def _upsert_book_rows_for_slug(
    existing: list[dict[str, object]],
    new_rows: list[dict[str, object]],
    *,
    book_slug: str,
) -> list[dict[str, object]]:
    kept = [row for row in existing if str(row.get("book_slug", "")) != book_slug]
    return kept + new_rows


def _bm25_row(chunk_row: dict[str, object]) -> dict[str, object]:
    chunk_type = str(chunk_row.get("chunk_type", "reference"))
    row = {
        "chunk_id": chunk_row["chunk_id"],
        "book_slug": chunk_row["book_slug"],
        "chapter": chunk_row["chapter"],
        "section": chunk_row["section"],
        "anchor": chunk_row["anchor"],
        "source_url": chunk_row["source_url"],
        "viewer_path": chunk_row["viewer_path"],
        "text": chunk_row["text"],
        "section_path": list(chunk_row["section_path"]),
        "chunk_type": chunk_type,
        "source_id": chunk_row["source_id"],
        "source_lane": chunk_row["source_lane"],
        "source_type": chunk_row["source_type"],
        "source_collection": chunk_row["source_collection"],
        "product": chunk_row["product"],
        "version": chunk_row["version"],
        "locale": chunk_row["locale"],
        "translation_status": chunk_row["translation_status"],
        "review_status": chunk_row["review_status"],
        "trust_score": chunk_row["trust_score"],
        "semantic_role": (
            "procedure"
            if chunk_type in {"procedure", "command"}
            else ("concept" if chunk_type == "concept" else "reference")
        ),
        "cli_commands": list(chunk_row.get("cli_commands", [])),
        "error_strings": list(chunk_row.get("error_strings", [])),
        "k8s_objects": list(chunk_row.get("k8s_objects", [])),
        "operator_names": list(chunk_row.get("operator_names", [])),
        "verification_hints": list(chunk_row.get("verification_hints", [])),
    }
    return enrich_contextual_row(row)


def _upsert_playbook_payload_for_slug(
    path: Path,
    books_dir: Path,
    payload: dict[str, object],
    *,
    book_slug: str,
) -> None:
    rows = _read_jsonl_safe(path)
    rows = _upsert_book_rows_for_slug(rows, [payload], book_slug=book_slug)
    _write_jsonl(path, rows)
    books_dir.mkdir(parents=True, exist_ok=True)
    (books_dir / f"{book_slug}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _curated_etcd_manifest_entry() -> SourceManifestEntry:
    return _curated_manifest_entry(CURATED_ETCD_SPEC)


def _upsert_manifest_entry(settings: Settings, entry: SourceManifestEntry) -> tuple[int, int]:
    before = 0
    if settings.source_manifest_path.exists():
        entries = read_manifest(settings.source_manifest_path)
        before = len(entries)
    else:
        entries = []
    filtered = [row for row in entries if row.book_slug != entry.book_slug]
    filtered.append(entry)
    filtered.sort(key=lambda item: (item.ocp_version, item.docs_language, item.source_kind, item.book_slug))
    write_manifest(settings.source_manifest_path, filtered)
    return before, len(filtered)


def _apply_curated_gold(
    settings: Settings,
    *,
    spec: CuratedGoldSpec,
    document_builder: Callable[[], CanonicalDocumentAst],
    refresh_synthesis_report: bool = False,
) -> dict[str, object]:
    document = document_builder()
    sections = project_normalized_sections(document)
    chunks = chunk_sections(sections, settings)

    normalized_rows = [section.to_dict() for section in sections]
    chunk_rows = [chunk.to_dict() for chunk in chunks]
    bm25_rows = [_bm25_row(chunk_row) for chunk_row in chunk_rows]

    playbook_payload = project_playbook_document(document).to_dict()
    playbook_payload["quality_score"] = spec.trust_score
    playbook_payload["quality_flags"] = []
    playbook_payload["review_status"] = "approved"
    playbook_payload["source_metadata"]["source_collection"] = "core"

    for path in settings.normalized_docs_candidates:
        rows = _read_jsonl_safe(path)
        _write_jsonl(
            path,
            _upsert_book_rows_for_slug(rows, normalized_rows, book_slug=spec.book_slug),
        )

    for path in (settings.chunks_path,):
        rows = _read_jsonl_safe(path)
        _write_jsonl(path, _upsert_rows(rows, chunk_rows, key_field="chunk_id"))

    for path in (settings.bm25_corpus_path,):
        rows = _read_jsonl_safe(path)
        _write_jsonl(path, _upsert_rows(rows, bm25_rows, key_field="chunk_id"))

    for path in (settings.playbook_documents_path,):
        _upsert_playbook_payload_for_slug(
            path,
            settings.playbook_books_dir,
            playbook_payload,
            book_slug=spec.book_slug,
        )

    manifest_before, manifest_after = _upsert_manifest_entry(
        settings,
        _curated_manifest_entry(spec),
    )
    graph_refresh = refresh_active_runtime_graph_artifacts(
        settings,
        refresh_full_sidecar=False,
        allow_compact_degrade=True,
    )

    synthesis_report_path = synthesis_lane_report_path(settings)
    synthesis_report = None
    if refresh_synthesis_report and settings.source_catalog_path.exists():
        synthesis_report = write_synthesis_lane_outputs(settings)

    report = {
        "book_slug": spec.book_slug,
        "title": spec.title,
        "section_count": len(normalized_rows),
        "chunk_count": len(chunk_rows),
        "manifest_before_count": manifest_before,
        "manifest_after_count": manifest_after,
        "graph_compact_refresh": dict(graph_refresh.get("compact_sidecar", {})),
        "graph_compact_artifact": graph_sidecar_compact_artifact_status(settings),
        "output_targets": {
            "normalized_docs": [str(path) for path in settings.normalized_docs_candidates],
            "chunks": [str(path) for path in (settings.chunks_path,)],
            "bm25_corpus": [str(path) for path in (settings.bm25_corpus_path,)],
            "playbook_documents": [str(path) for path in (settings.playbook_documents_path,)],
            "playbook_books": [str(path) for path in settings.playbook_book_dirs],
            "approved_manifest_path": str(settings.source_manifest_path),
            "graph_sidecar_compact_path": str(settings.graph_sidecar_compact_path),
        },
    }
    if synthesis_report is not None:
        report["synthesis_report_path"] = str(synthesis_report_path)
        report["synthesis_summary"] = synthesis_report["summary"]
    return report


def apply_curated_etcd_gold(
    settings: Settings,
    *,
    refresh_synthesis_report: bool = False,
) -> dict[str, object]:
    return _apply_curated_gold(
        settings,
        spec=CURATED_ETCD_SPEC,
        document_builder=build_curated_etcd_document,
        refresh_synthesis_report=refresh_synthesis_report,
    )


CURATED_BACKUP_RESTORE_BOOK_SLUG = "backup_and_restore"
CURATED_BACKUP_RESTORE_TITLE = "백업 및 복구 운영 플레이북"
CURATED_BACKUP_RESTORE_SOURCE_URL = (
    "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/"
    "html-single/backup_and_restore/index"
)
CURATED_BACKUP_RESTORE_TRANSLATION_SOURCE_URL = (
    "https://docs.redhat.com/en/documentation/openshift_container_platform/4.20/"
    "html-single/backup_and_restore/index"
)
CURATED_BACKUP_RESTORE_INDEX_URL = (
    "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/"
)
CURATED_BACKUP_RESTORE_VIEWER_BASE_PATH = "/docs/ocp/4.20/ko/backup_and_restore/index.html"
CURATED_BACKUP_RESTORE_SOURCE_ID = (
    "openshift_container_platform:4.20:ko:backup_and_restore:curated_gold_v1"
)
CURATED_BACKUP_RESTORE_UPDATED_AT = "2026-04-10T00:00:00Z"
CURATED_BACKUP_RESTORE_LICENSE = (
    "OpenShift documentation is licensed under the Apache License 2.0."
)


def _backup_restore_provenance_notes() -> tuple[str, ...]:
    return (
        "curated_backup_and_restore_gold_v1",
        "manual_review_promoted_from_source_bundle",
        "official_ko_en_and_repo_sidecars_reviewed",
    )


CURATED_BACKUP_RESTORE_SPEC = CuratedGoldSpec(
    book_slug=CURATED_BACKUP_RESTORE_BOOK_SLUG,
    title=CURATED_BACKUP_RESTORE_TITLE,
    source_url=CURATED_BACKUP_RESTORE_SOURCE_URL,
    translation_source_url=CURATED_BACKUP_RESTORE_TRANSLATION_SOURCE_URL,
    index_url=CURATED_BACKUP_RESTORE_INDEX_URL,
    viewer_base_path=CURATED_BACKUP_RESTORE_VIEWER_BASE_PATH,
    source_id=CURATED_BACKUP_RESTORE_SOURCE_ID,
    updated_at=CURATED_BACKUP_RESTORE_UPDATED_AT,
    license_or_terms=CURATED_BACKUP_RESTORE_LICENSE,
    original_title="Backup and restore",
    vendor_title="Backup and restore",
    approval_notes="curated backup_and_restore gold sample from official KO/EN docs and repo sidecars",
    notes=_backup_restore_provenance_notes(),
)


def _build_backup_restore_provenance() -> AstProvenance:
    return _build_curated_provenance(CURATED_BACKUP_RESTORE_SPEC)


def _backup_restore_section(
    *,
    ordinal: int,
    heading: str,
    anchor: str,
    semantic_role: str,
    blocks: tuple[object, ...],
    path: tuple[str, ...] | None = None,
    level: int = 2,
) -> CanonicalSectionAst:
    return _section_for(
        CURATED_BACKUP_RESTORE_SPEC,
        ordinal=ordinal,
        heading=heading,
        anchor=anchor,
        semantic_role=semantic_role,
        blocks=blocks,
        path=path,
        level=level,
    )


def build_curated_backup_restore_document() -> CanonicalDocumentAst:
    sections = (
        _backup_restore_section(
            ordinal=1,
            heading="백업 및 복구 운영 구도",
            anchor="backup-restore-playbook-overview",
            semantic_role="overview",
            blocks=(
                ParagraphBlock(
                    "이 플레이북은 OpenShift 4.20의 `backup_and_restore` 책에서 "
                    "운영자가 가장 자주 쓰는 판단 축만 다시 묶은 curated gold 수동서입니다. "
                    "핵심은 컨트롤 플레인 축과 애플리케이션 축을 혼동하지 않는 것입니다."
                ),
                ParagraphBlock(
                    "컨트롤 플레인 백업과 재해 복구는 etcd 스냅샷을 기준으로 판단하고, "
                    "애플리케이션 백업과 복원은 OADP로 namespace 단위 자산을 다룹니다."
                ),
                NoteBlock(
                    title="중요",
                    variant="important",
                    text=(
                        "OADP는 고객 워크로드 namespace와 cluster-scope resource를 보호하지만, "
                        "전체 클러스터 백업/복구나 etcd 재해 복구 자체를 대체하지 않습니다."
                    ),
                ),
            ),
        ),
        _backup_restore_section(
            ordinal=2,
            heading="어떤 복구 축을 선택할지 먼저 판단",
            anchor="backup-restore-decision-tree",
            semantic_role="concept",
            blocks=(
                ParagraphBlock(
                    "클러스터를 종료했다가 다시 올리거나 control plane 장애, quorum 손실, "
                    "실수로 삭제한 핵심 control plane 상태를 되돌려야 한다면 etcd 백업/복원 절차를 먼저 검토합니다."
                ),
                ParagraphBlock(
                    "반대로 애플리케이션 namespace, PV, 내부 이미지, VM 백업과 복원이 목적이라면 "
                    "OADP의 `Backup` 과 `Restore` CR 흐름으로 들어갑니다."
                ),
                NoteBlock(
                    title="주의",
                    variant="warning",
                    text=(
                        "etcd와 OADP를 같은 복구 수단으로 취급하면 안 됩니다. "
                        "전체 클러스터 상태 복구는 etcd, 애플리케이션 데이터 보호는 OADP가 담당합니다."
                    ),
                ),
            ),
        ),
        _backup_restore_section(
            ordinal=3,
            heading="OADP 적용 전 요구사항",
            anchor="oadp-prerequisites",
            semantic_role="concept",
            blocks=(
                PrerequisiteBlock(
                    items=(
                        "작업자는 `cluster-admin` 권한으로 로그인되어 있어야 합니다.",
                        "백업을 저장할 object storage가 준비되어 있어야 합니다.",
                        "PV를 스냅샷으로 보호하려면 native snapshot API 또는 CSI snapshot 지원 스토리지가 필요합니다.",
                        "스냅샷을 쓰지 않으면 OADP Operator가 기본 설치하는 Restic 기반 파일 시스템 백업을 사용합니다.",
                    )
                ),
                ParagraphBlock(
                    "OADP는 namespace 단위의 Kubernetes 리소스와 내부 이미지를 백업/복원하며, "
                    "지속 볼륨은 snapshot 또는 Restic/Kopia 경로로 보호합니다."
                ),
            ),
        ),
        _backup_restore_section(
            ordinal=4,
            heading="DPA와 백업 저장소를 먼저 준비",
            anchor="oadp-dpa-and-storage",
            semantic_role="procedure",
            blocks=(
                ProcedureBlock(
                    steps=(
                        ProcedureStep(1, "OADP Operator를 설치하고 `openshift-adp` namespace를 준비합니다."),
                        ProcedureStep(2, "`DataProtectionApplication` CR을 생성해 OADP 기본 구성을 선언합니다."),
                        ProcedureStep(3, "사용할 object storage에 맞는 `BackupStorageLocation` 을 연결합니다."),
                        ProcedureStep(4, "PV snapshot을 사용할 경우 `VolumeSnapshotLocation` 도 함께 구성합니다."),
                    )
                ),
                CodeBlock(
                    language="yaml",
                    caption="DPA CR 최소 골격",
                    code=(
                        "apiVersion: oadp.openshift.io/v1alpha1\n"
                        "kind: DataProtectionApplication\n"
                        "metadata:\n"
                        "  name: <dpa_name>\n"
                        "  namespace: openshift-adp\n"
                        "spec:\n"
                        "  # backupLocations / snapshotLocations / configuration 은\n"
                        "  # 사용하는 스토리지 provider에 맞게 채웁니다."
                    ),
                ),
                ParagraphBlock(
                    "문서상 OADP 주요 API는 `DataProtectionApplicationSpec`, `BackupLocation`, "
                    "`SnapshotLocation`, `ApplicationConfig`, `VeleroConfig`, `ResticConfig`, `PodConfig` 등입니다."
                ),
            ),
        ),
        _backup_restore_section(
            ordinal=5,
            heading="OADP 상태와 저장소를 먼저 검증",
            anchor="oadp-verification",
            semantic_role="procedure",
            blocks=(
                ParagraphBlock(
                    "백업이나 복원을 시작하기 전에 OADP 관련 리소스와 백업 저장소 연결 상태가 정상인지 먼저 확인합니다."
                ),
                CodeBlock(
                    language="bash",
                    caption="OADP 리소스 상태 확인",
                    code="oc get all -n openshift-adp",
                ),
                CodeBlock(
                    language="bash",
                    caption="BackupStorageLocation 확인",
                    code="oc get backupstoragelocations.velero.io -n openshift-adp",
                ),
                ParagraphBlock(
                    "백업 저장소가 보이지 않거나 상태가 비정상이면 `Backup` CR을 만들기 전에 "
                    "BSL 설정과 access key, bucket 연결 상태를 먼저 수정해야 합니다."
                ),
            ),
        ),
        _backup_restore_section(
            ordinal=6,
            heading="Backup CR로 애플리케이션 백업 실행",
            anchor="oadp-backup-cr",
            semantic_role="procedure",
            blocks=(
                ParagraphBlock(
                    "애플리케이션 백업은 `Backup` CR을 만들어 시작합니다. "
                    "최소 골격은 백업 이름, `openshift-adp` namespace, 대상 애플리케이션 namespace 입니다."
                ),
                CodeBlock(
                    language="yaml",
                    caption="Backup CR 최소 예시",
                    code=(
                        "apiVersion: velero.io/v1\n"
                        "kind: Backup\n"
                        "metadata:\n"
                        "  name: <backup_name>\n"
                        "  namespace: openshift-adp\n"
                        "spec:\n"
                        "  includedNamespaces:\n"
                        "  - <application_namespace>"
                    ),
                ),
                CodeBlock(
                    language="bash",
                    caption="Backup CR 적용",
                    code="oc apply -f <backup_cr_filename>",
                ),
                CodeBlock(
                    language="bash",
                    caption="Backup 상태 확인",
                    code='watch "oc -n openshift-adp get backup <backup_name> -o json | jq .status"',
                ),
                NoteBlock(
                    title="작은 정보",
                    variant="tip",
                    text=(
                        "문서 예시에서는 `storageLocation`, `ttl`, `defaultVolumesToFsBackup` 같은 옵션을 "
                        "백업 목적에 맞게 추가합니다."
                    ),
                ),
            ),
        ),
        _backup_restore_section(
            ordinal=7,
            heading="Restore CR로 복원 실행",
            anchor="oadp-restore-cr",
            semantic_role="procedure",
            blocks=(
                ParagraphBlock(
                    "복원은 `Restore` CR로 시작합니다. 가장 기본적인 필드는 복원 이름과 복원에 사용할 `backupName` 입니다."
                ),
                CodeBlock(
                    language="yaml",
                    caption="Restore CR 최소 예시",
                    code=(
                        "apiVersion: velero.io/v1\n"
                        "kind: Restore\n"
                        "metadata:\n"
                        "  name: <restore_name>\n"
                        "  namespace: openshift-adp\n"
                        "spec:\n"
                        "  backupName: <backup_name>"
                    ),
                ),
                CodeBlock(
                    language="bash",
                    caption="Restore CR 적용",
                    code="oc apply -f <restore_cr_filename>",
                ),
                ParagraphBlock(
                    "원문 예시에는 필요에 따라 `restorePVs`, `namespaceMapping`, "
                    "`itemOperationTimeout` 같은 필드를 추가합니다. 대용량 볼륨이 얽힌 복원은 timeout 조정이 필요할 수 있습니다."
                ),
            ),
        ),
        _backup_restore_section(
            ordinal=8,
            heading="장애 시 다음 분기",
            anchor="oadp-troubleshooting-next-branches",
            semantic_role="reference",
            blocks=(
                ParagraphBlock(
                    "백업/복원 CR 상태가 `InProgress` 에서 멈추거나 volume retrieval 문제가 생기면, "
                    "먼저 `BackupStorageLocation` 구성과 bucket 접근 키를 다시 확인합니다."
                ),
                ParagraphBlock(
                    "OADP 장애 분석은 Velero CLI, `must-gather`, Backup/Restore CR 상태 점검 순서로 들어갑니다. "
                    "지원 케이스를 여는 경우 `must-gather` 데이터 첨부가 기본입니다."
                ),
                ParagraphBlock(
                    "Restic 권한 오류, admission webhook 충돌, pod resource 부족, snapshot timeout 같은 문제는 "
                    "모두 `backup_and_restore` 원문 troubleshooting 절로 다시 분기합니다."
                ),
            ),
        ),
    )
    return _build_curated_document(CURATED_BACKUP_RESTORE_SPEC, sections)


def _curated_backup_restore_manifest_entry() -> SourceManifestEntry:
    return _curated_manifest_entry(CURATED_BACKUP_RESTORE_SPEC)


def apply_curated_backup_restore_gold(
    settings: Settings,
    *,
    refresh_synthesis_report: bool = False,
) -> dict[str, object]:
    return _apply_curated_gold(
        settings,
        spec=CURATED_BACKUP_RESTORE_SPEC,
        document_builder=build_curated_backup_restore_document,
        refresh_synthesis_report=refresh_synthesis_report,
    )


CURATED_MACHINE_CONFIGURATION_BOOK_SLUG = "machine_configuration"
CURATED_MACHINE_CONFIGURATION_TITLE = "머신 구성 운영 플레이북"
CURATED_MACHINE_CONFIGURATION_SOURCE_URL = (
    "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/"
    "html-single/machine_configuration/index"
)
CURATED_MACHINE_CONFIGURATION_TRANSLATION_SOURCE_URL = (
    "https://docs.redhat.com/en/documentation/openshift_container_platform/4.20/"
    "html-single/machine_configuration/index"
)
CURATED_MACHINE_CONFIGURATION_INDEX_URL = (
    "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/"
)
CURATED_MACHINE_CONFIGURATION_VIEWER_BASE_PATH = (
    "/docs/ocp/4.20/ko/machine_configuration/index.html"
)
CURATED_MACHINE_CONFIGURATION_SOURCE_ID = (
    "openshift_container_platform:4.20:ko:machine_configuration:curated_gold_v1"
)
CURATED_MACHINE_CONFIGURATION_UPDATED_AT = "2026-04-10T00:00:00Z"
CURATED_MACHINE_CONFIGURATION_LICENSE = (
    "OpenShift documentation is licensed under the Apache License 2.0."
)


def _machine_configuration_provenance_notes() -> tuple[str, ...]:
    return (
        "curated_machine_configuration_gold_v1",
        "manual_review_promoted_from_source_bundle",
        "official_ko_en_and_repo_sidecars_reviewed",
    )


CURATED_MACHINE_CONFIGURATION_SPEC = CuratedGoldSpec(
    book_slug=CURATED_MACHINE_CONFIGURATION_BOOK_SLUG,
    title=CURATED_MACHINE_CONFIGURATION_TITLE,
    source_url=CURATED_MACHINE_CONFIGURATION_SOURCE_URL,
    translation_source_url=CURATED_MACHINE_CONFIGURATION_TRANSLATION_SOURCE_URL,
    index_url=CURATED_MACHINE_CONFIGURATION_INDEX_URL,
    viewer_base_path=CURATED_MACHINE_CONFIGURATION_VIEWER_BASE_PATH,
    source_id=CURATED_MACHINE_CONFIGURATION_SOURCE_ID,
    updated_at=CURATED_MACHINE_CONFIGURATION_UPDATED_AT,
    license_or_terms=CURATED_MACHINE_CONFIGURATION_LICENSE,
    original_title="Machine configuration",
    vendor_title="Machine configuration",
    approval_notes="curated machine_configuration gold sample from official KO/EN docs and repo sidecars",
    notes=_machine_configuration_provenance_notes(),
)


def _build_machine_configuration_provenance() -> AstProvenance:
    return _build_curated_provenance(CURATED_MACHINE_CONFIGURATION_SPEC)


def _machine_configuration_section(
    *,
    ordinal: int,
    heading: str,
    anchor: str,
    semantic_role: str,
    blocks: tuple[object, ...],
    path: tuple[str, ...] | None = None,
    level: int = 2,
) -> CanonicalSectionAst:
    return _section_for(
        CURATED_MACHINE_CONFIGURATION_SPEC,
        ordinal=ordinal,
        heading=heading,
        anchor=anchor,
        semantic_role=semantic_role,
        blocks=blocks,
        path=path,
        level=level,
    )


def build_curated_machine_configuration_document() -> CanonicalDocumentAst:
    sections = (
        _machine_configuration_section(
            ordinal=1,
            heading="머신 구성 운영 개요",
            anchor="machine-config-playbook-overview",
            semantic_role="overview",
            blocks=(
                ParagraphBlock(
                    "OpenShift 노드 운영체제에 대한 대부분의 day-2 변경은 "
                    "`MachineConfig` 객체와 Machine Config Operator(MCO)로 관리합니다. "
                    "이 플레이북은 운영자가 실제로 자주 확인하는 구성 변경, 적용 상태, Degraded 분기를 한 흐름으로 묶은 curated gold 수동서입니다."
                ),
                ParagraphBlock(
                    "핵심 객체는 세 가지입니다. 변경 정의는 `MachineConfig`, 적용 대상은 `MachineConfigPool`, "
                    "노드별 진행 상태는 `MachineConfigNode` 가 보여줍니다."
                ),
            ),
        ),
        _machine_configuration_section(
            ordinal=2,
            heading="언제 MachineConfig를 써야 하는가",
            anchor="machine-config-usage-boundary",
            semantic_role="concept",
            blocks=(
                ParagraphBlock(
                    "chronyd 비활성화, kernel argument 추가, journald 설정, multipathing, "
                    "RHCOS extension 추가 같은 운영체제 수준 변경은 대부분 `MachineConfig` 로 처리합니다."
                ),
                ParagraphBlock(
                    "새로 만드는 machine config는 Ignition specification 3.5 기반으로 작성하는 것이 기준입니다."
                ),
                NoteBlock(
                    title="중요",
                    variant="important",
                    text=(
                        "구성 변경이 현재 적용된 machine config와 실제 노드 상태와 어긋나면 "
                        "MCD가 configuration drift를 감지하고 노드를 `degraded` 로 표시합니다. "
                        "이 상태의 노드는 온라인일 수 있지만 업데이트는 진행되지 않습니다."
                    ),
                ),
            ),
        ),
        _machine_configuration_section(
            ordinal=3,
            heading="MachineConfig 최소 골격",
            anchor="machine-config-minimal-yaml",
            semantic_role="procedure",
            blocks=(
                ParagraphBlock(
                    "실제 변경 내용은 목적마다 달라지지만, 운영자가 반드시 지켜야 할 골격은 "
                    "`role` 라벨, 객체 이름, 그리고 필요한 경우 Ignition 기반 `spec.config` 입니다."
                ),
                CodeBlock(
                    language="yaml",
                    caption="MachineConfig 최소 예시",
                    code=(
                        "apiVersion: machineconfiguration.openshift.io/v1\n"
                        "kind: MachineConfig\n"
                        "metadata:\n"
                        "  labels:\n"
                        "    machineconfiguration.openshift.io/role: worker\n"
                        "  name: 99-worker-custom\n"
                        "spec:\n"
                        "  config:\n"
                        "    ignition:\n"
                        "      version: 3.5.0"
                    ),
                ),
                ParagraphBlock(
                    "문서 예시에서는 목적에 따라 `kernelType`, `passwd`, 파일 변경, systemd unit, "
                    "extension 같은 필드를 `spec` 아래에 추가합니다."
                ),
            ),
        ),
        _machine_configuration_section(
            ordinal=4,
            heading="변경을 클러스터에 적용",
            anchor="machine-config-apply",
            semantic_role="procedure",
            blocks=(
                ProcedureBlock(
                    steps=(
                        ProcedureStep(1, "변경 목적에 맞는 MachineConfig YAML 파일을 준비합니다."),
                        ProcedureStep(2, "적용 대상 pool에 맞는 role 라벨을 확인합니다. 예: `worker`, `master`."),
                        ProcedureStep(3, "`oc create -f <machineconfig_file>.yaml` 로 MachineConfig 객체를 생성합니다."),
                    )
                ),
                CodeBlock(
                    language="bash",
                    caption="MachineConfig 생성",
                    code="oc create -f 99-worker-custom.yaml",
                ),
                CodeBlock(
                    language="bash",
                    caption="현재 MachineConfig 목록 확인",
                    code="oc get machineconfigs",
                ),
            ),
        ),
        _machine_configuration_section(
            ordinal=5,
            heading="MCP 상태로 롤아웃을 확인",
            anchor="machine-config-mcp-verification",
            semantic_role="procedure",
            blocks=(
                ParagraphBlock(
                    "구성 변경이 반영되기 시작하면 먼저 `MachineConfigPool` 상태를 봅니다. "
                    "여기서 `UPDATED`, `UPDATING`, `DEGRADED` 플래그가 전체 pool 기준 상태를 보여줍니다."
                ),
                CodeBlock(
                    language="bash",
                    caption="MachineConfigPool 상태 확인",
                    code="oc get machineconfigpool",
                ),
                ParagraphBlock(
                    "정상 롤아웃이면 대상 pool이 일시적으로 `UPDATING=True` 가 되었다가 "
                    "완료 후 `UPDATED=True`, `DEGRADED=False` 로 돌아옵니다."
                ),
                CodeBlock(
                    language="bash",
                    caption="특정 pool 상세 확인",
                    code="oc describe machineconfigpool worker",
                ),
            ),
        ),
        _machine_configuration_section(
            ordinal=6,
            heading="노드별 적용 상태를 확인",
            anchor="machine-config-node-verification",
            semantic_role="procedure",
            blocks=(
                ParagraphBlock(
                    "노드 단위 진행 상황과 current/desired config 차이는 `MachineConfigNode` 로 확인합니다."
                ),
                CodeBlock(
                    language="bash",
                    caption="노드별 MachineConfig 상태 확인",
                    code="oc get machineconfignodes",
                ),
                CodeBlock(
                    language="bash",
                    caption="노드별 상태 필드 전체 확인",
                    code="oc get machineconfignodes -o wide",
                ),
                ParagraphBlock(
                    "업데이트가 꼬였을 때는 `desiredConfig` 와 `currentConfig` 가 어긋나는 노드가 보입니다. "
                    "이 정보가 Degraded 원인 추적의 시작점입니다."
                ),
            ),
        ),
        _machine_configuration_section(
            ordinal=7,
            heading="Degraded와 disruption을 운영자가 해석하는 법",
            anchor="machine-config-degraded-and-disruption",
            semantic_role="concept",
            blocks=(
                ParagraphBlock(
                    "configuration drift가 감지되면 MCO가 노드를 `degraded` 로 표시합니다. "
                    "이 상태는 서비스가 즉시 죽었다는 뜻이 아니라, 현재 노드가 선언된 구성과 일치하지 않아 "
                    "안전한 추가 업데이트가 막혔다는 뜻입니다."
                ),
                ParagraphBlock(
                    "MachineConfig 변경 중 일부는 drain과 reboot가 기본 동작입니다. "
                    "반면 작은 파일 변경처럼 영향이 적은 작업은 node disruption policy로 완화할 수 있습니다."
                ),
                NoteBlock(
                    title="주의",
                    variant="warning",
                    text=(
                        "node disruption policy는 MCO가 형식 문제를 검사하더라도, "
                        "실제 변경이 안전하게 적용될지를 보장하지는 않습니다. 정책 정확성은 운영자가 책임집니다."
                    ),
                ),
            ),
        ),
        _machine_configuration_section(
            ordinal=8,
            heading="작업 후 다음 분기",
            anchor="machine-config-next-branches",
            semantic_role="reference",
            blocks=(
                ParagraphBlock(
                    "`oc get machineconfigpool` 에서 `DEGRADED=True` 이면 먼저 영향 pool과 노드를 좁히고, "
                    "`oc get machineconfignodes` 로 desired/current 차이를 확인한 뒤 "
                    "직전 MachineConfig 변경과 configuration drift 여부를 점검합니다."
                ),
                ParagraphBlock(
                    "광범위한 변경으로 reboot 비용이 크다면, 적용 전에 node disruption policy나 "
                    "pool pause 전략을 검토하는 것이 다음 분기입니다."
                ),
                ParagraphBlock(
                    "커스텀 layered image, boot image 관리, pinned image set 같은 고급 기능은 "
                    "기본 MachineConfig 흐름이 안정적인 것이 확인된 뒤 별도 플레이북으로 확장합니다."
                ),
            ),
        ),
    )
    return _build_curated_document(CURATED_MACHINE_CONFIGURATION_SPEC, sections)


def _curated_machine_configuration_manifest_entry() -> SourceManifestEntry:
    return _curated_manifest_entry(CURATED_MACHINE_CONFIGURATION_SPEC)


def apply_curated_machine_configuration_gold(
    settings: Settings,
    *,
    refresh_synthesis_report: bool = False,
) -> dict[str, object]:
    return _apply_curated_gold(
        settings,
        spec=CURATED_MACHINE_CONFIGURATION_SPEC,
        document_builder=build_curated_machine_configuration_document,
        refresh_synthesis_report=refresh_synthesis_report,
    )


CURATED_OPERATORS_BOOK_SLUG = "operators"
CURATED_OPERATORS_TITLE = "Operator 운영 플레이북"
CURATED_OPERATORS_SOURCE_URL = (
    "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/"
    "html-single/operators/index"
)
CURATED_OPERATORS_TRANSLATION_SOURCE_URL = (
    "https://docs.redhat.com/en/documentation/openshift_container_platform/4.20/"
    "html-single/operators/index"
)
CURATED_OPERATORS_INDEX_URL = (
    "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/"
)
CURATED_OPERATORS_VIEWER_BASE_PATH = "/docs/ocp/4.20/ko/operators/index.html"
CURATED_OPERATORS_SOURCE_ID = "openshift_container_platform:4.20:ko:operators:curated_gold_v1"
CURATED_OPERATORS_UPDATED_AT = "2026-04-10T00:00:00Z"
CURATED_OPERATORS_LICENSE = "OpenShift documentation is licensed under the Apache License 2.0."


def _operators_provenance_notes() -> tuple[str, ...]:
    return (
        "curated_operators_gold_v1",
        "manual_review_promoted_from_source_bundle",
        "official_ko_en_and_repo_sidecars_reviewed",
    )


CURATED_OPERATORS_SPEC = CuratedGoldSpec(
    book_slug=CURATED_OPERATORS_BOOK_SLUG,
    title=CURATED_OPERATORS_TITLE,
    source_url=CURATED_OPERATORS_SOURCE_URL,
    translation_source_url=CURATED_OPERATORS_TRANSLATION_SOURCE_URL,
    index_url=CURATED_OPERATORS_INDEX_URL,
    viewer_base_path=CURATED_OPERATORS_VIEWER_BASE_PATH,
    source_id=CURATED_OPERATORS_SOURCE_ID,
    updated_at=CURATED_OPERATORS_UPDATED_AT,
    license_or_terms=CURATED_OPERATORS_LICENSE,
    original_title="Operators",
    vendor_title="Operators",
    approval_notes="curated operators gold sample from official KO/EN docs and repo sidecars",
    notes=_operators_provenance_notes(),
)


def _build_operators_provenance() -> AstProvenance:
    return _build_curated_provenance(CURATED_OPERATORS_SPEC)


def _operators_section(
    *,
    ordinal: int,
    heading: str,
    anchor: str,
    semantic_role: str,
    blocks: tuple[object, ...],
    path: tuple[str, ...] | None = None,
    level: int = 2,
) -> CanonicalSectionAst:
    return _section_for(
        CURATED_OPERATORS_SPEC,
        ordinal=ordinal,
        heading=heading,
        anchor=anchor,
        semantic_role=semantic_role,
        blocks=blocks,
        path=path,
        level=level,
    )


def build_curated_operators_document() -> CanonicalDocumentAst:
    sections = (
        _operators_section(
            ordinal=1,
            heading="Operator 운영 개요",
            anchor="operators-playbook-overview",
            semantic_role="overview",
            blocks=(
                ParagraphBlock(
                    "Operator는 사람이 반복하던 운영 지식을 소프트웨어로 패키징해 "
                    "애플리케이션 배포, 업그레이드, 상태 유지 작업을 자동화합니다. "
                    "이 플레이북은 OpenShift 4.20의 OLM 운영에서 실제로 자주 쓰는 "
                    "판단과 확인 루프만 다시 묶은 curated gold 수동서입니다."
                ),
                ParagraphBlock(
                    "핵심 흐름은 세 단계입니다. 먼저 어떤 카탈로그와 설치 범위를 쓸지 정하고, "
                    "그 다음 Subscription과 OperatorGroup 상태를 확인하며, 마지막으로 "
                    "CSV와 operator pod 로그를 통해 실제 동작 상태를 좁혀갑니다."
                ),
            ),
        ),
        _operators_section(
            ordinal=2,
            heading="핵심 객체와 판단축",
            anchor="operators-core-resources",
            semantic_role="concept",
            blocks=(
                ParagraphBlock(
                    "`PackageManifest` 는 카탈로그에 어떤 Operator 패키지가 있는지 보여주고, "
                    "`Subscription` 은 어떤 채널을 따라 설치와 업데이트를 유지할지 선언합니다."
                ),
                ParagraphBlock(
                    "`OperatorGroup` 은 Operator가 어떤 namespace를 감시하며 어떤 RBAC 범위를 "
                    "가질지 정하고, `ClusterServiceVersion(CSV)` 는 현재 실제로 활성화된 "
                    "Operator 버전과 제공 API를 나타냅니다."
                ),
                ParagraphBlock(
                    "`CatalogSource` 는 패키지 메타데이터를 제공하는 공급원입니다. "
                    "동일한 Operator가 여러 catalog에 있으면 원하는 catalog를 명시하지 않을 경우 "
                    "예상과 다른 패키지를 보게 될 수 있습니다."
                ),
                NoteBlock(
                    title="중요",
                    variant="important",
                    text=(
                        "OperatorGroup은 대상 namespace를 선택해 멤버 Operator에 필요한 RBAC를 생성합니다. "
                        "설치 범위와 namespace를 잘못 잡으면 권한 범위와 가시성이 처음부터 어긋납니다."
                    ),
                ),
            ),
        ),
        _operators_section(
            ordinal=3,
            heading="설치 전에 먼저 정할 것",
            anchor="operators-installation-decisions",
            semantic_role="concept",
            blocks=(
                ParagraphBlock(
                    "설치 전에는 최소 세 가지를 먼저 정해야 합니다. 어떤 catalog를 쓸지, "
                    "Operator를 어느 namespace에 둘지, 그리고 single namespace와 all namespaces 중 "
                    "어떤 설치 범위를 허용할지입니다."
                ),
                ParagraphBlock(
                    "멀티테넌트 환경에서는 tenant용 Operator namespace를 별도로 두고, "
                    "OperatorGroup이 tenant namespace만 감시하도록 구성하는 방식이 기본 권한 원칙에 더 가깝습니다."
                ),
                NoteBlock(
                    title="주의",
                    variant="warning",
                    text=(
                        "같은 클러스터에 동일 Operator의 서로 다른 버전 라인을 병행 운영하는 방식은 안전한 기본값이 아닙니다. "
                        "특히 multitenant self-service를 허용할 때는 curated catalog와 동일 버전 라인을 강제해야 합니다."
                    ),
                ),
            ),
        ),
        _operators_section(
            ordinal=4,
            heading="카탈로그에서 패키지와 공급원을 확인",
            anchor="operators-catalog-discovery",
            semantic_role="procedure",
            blocks=(
                ProcedureBlock(
                    steps=(
                        ProcedureStep(1, "먼저 `openshift-marketplace` 의 catalog source 목록을 확인합니다."),
                        ProcedureStep(2, "설치하려는 Operator 패키지가 어떤 catalog에 노출되는지 확인합니다."),
                        ProcedureStep(3, "동일 패키지가 여러 catalog에 있으면 selector로 원하는 catalog를 명시합니다."),
                    )
                ),
                CodeBlock(
                    language="bash",
                    caption="카탈로그 source 목록 확인",
                    code=(
                        "oc get catalogsources -n openshift-marketplace\n"
                        "oc get catalogsource -n openshift-marketplace"
                    ),
                ),
                CodeBlock(
                    language="bash",
                    caption="패키지 manifest 확인",
                    code=(
                        "oc get packagemanifests -n openshift-marketplace\n"
                        "oc get packagemanifests <operator_name> -n <catalog_namespace> -o yaml\n"
                        "oc get packagemanifest "
                        "--selector=catalog=<catalogsource_name> "
                        "--field-selector metadata.name=<operator_name> "
                        "-n <catalog_namespace> -o yaml"
                    ),
                ),
                NoteBlock(
                    title="작은 정보",
                    variant="tip",
                    text=(
                        "문서에서도 catalog를 지정하지 않으면 여러 catalog 중 예상과 다른 package가 "
                        "보일 수 있다고 경고합니다. catalog가 둘 이상이면 selector를 기본값처럼 쓰는 편이 안전합니다."
                    ),
                ),
            ),
        ),
        _operators_section(
            ordinal=5,
            heading="Subscription과 OperatorGroup 상태 확인",
            anchor="operators-subscription-and-group-status",
            semantic_role="procedure",
            blocks=(
                ParagraphBlock(
                    "설치 이후 첫 확인 대상은 Subscription과 OperatorGroup입니다. "
                    "Subscription은 현재 어떤 CSV를 따라가고 있는지, OperatorGroup은 어느 namespace 범위를 대상으로 "
                    "RBAC를 생성했는지를 보여줍니다."
                ),
                CodeBlock(
                    language="bash",
                    caption="Subscription과 OperatorGroup 확인",
                    code=(
                        "oc describe subscription <subscription_name> -n <namespace>\n"
                        "oc describe operatorgroup <operatorgroup_name> -n <namespace>\n"
                        "oc get subscription.operators.coreos.com <subscription_name> -n <namespace> -o yaml | grep currentCSV"
                    ),
                ),
                ParagraphBlock(
                    "`currentCSV` 가 기대한 채널 head와 맞는지, OperatorGroup의 target namespace가 "
                    "설치 의도와 맞는지부터 확인하는 것이 가장 빠른 1차 점검입니다."
                ),
            ),
        ),
        _operators_section(
            ordinal=6,
            heading="CSV와 catalog source의 실제 진행 상태를 본다",
            anchor="operators-csv-and-catalog-runtime",
            semantic_role="procedure",
            blocks=(
                ParagraphBlock(
                    "설치가 진행 중인지, 이미 활성화됐는지, 사용자 가시성만 제한된 것인지를 나누려면 "
                    "CSV와 catalog source pod 상태를 함께 확인해야 합니다."
                ),
                CodeBlock(
                    language="bash",
                    caption="CSV와 catalog source 상태 확인",
                    code=(
                        "oc get csv\n"
                        "oc get csvs -n openshift\n"
                        "oc get pods -n openshift-marketplace"
                    ),
                ),
                ParagraphBlock(
                    "문서 기준으로 일반 사용자는 자기 namespace에 직접 설치된 Operator는 `oc get csvs` 로 볼 수 있지만, "
                    "`openshift` namespace에서 복사된 CSV는 자기 namespace에서 보이지 않을 수 있습니다. "
                    "이 경우 보이지 않는다고 해서 Operator가 죽었다고 판단하면 안 됩니다."
                ),
            ),
        ),
        _operators_section(
            ordinal=7,
            heading="문제가 생기면 pod와 로그로 좁힌다",
            anchor="operators-troubleshooting",
            semantic_role="procedure",
            blocks=(
                ParagraphBlock(
                    "공식 troubleshooting 흐름도 동일합니다. Subscription 상태를 먼저 보고, "
                    "그 다음 operator pod 건강 상태와 로그를 순서대로 확인합니다."
                ),
                CodeBlock(
                    language="bash",
                    caption="Operator pod와 로그 확인",
                    code=(
                        "oc get pods -n <operator_namespace>\n"
                        "oc logs pod/<pod_name> -n <operator_namespace>\n"
                        "oc logs pod/<operator_pod_name> -c <container_name> -n <operator_namespace>"
                    ),
                ),
                ParagraphBlock(
                    "카탈로그 자체가 비정상이라면 `openshift-marketplace` 의 catalog source pod부터 보고, "
                    "구독이 실패 상태라면 failing subscription refresh 또는 재설치를 다음 분기로 선택합니다."
                ),
            ),
        ),
        _operators_section(
            ordinal=8,
            heading="작업 후 다음 분기",
            anchor="operators-next-branches",
            semantic_role="reference",
            blocks=(
                ParagraphBlock(
                    "catalog에서 패키지가 안 보이면 먼저 catalog source와 selector를 다시 확인하고, "
                    "보이는데 설치가 진행되지 않으면 Subscription과 currentCSV를 점검합니다."
                ),
                ParagraphBlock(
                    "설치는 됐는데 사용 범위가 기대와 다르면 OperatorGroup target namespace와 "
                    "설치 모드(single namespace / all namespaces)를 다시 확인합니다."
                ),
                ParagraphBlock(
                    "disconnected 운영이나 custom catalog 운영이 필요하면, 기본 OLM 흐름이 안정적인 것이 확인된 뒤 "
                    "custom catalog 관리와 제한된 네트워크 운영 플레이북으로 다음 분기합니다."
                ),
            ),
        ),
    )
    return _build_curated_document(CURATED_OPERATORS_SPEC, sections)


def _curated_operators_manifest_entry() -> SourceManifestEntry:
    return _curated_manifest_entry(CURATED_OPERATORS_SPEC)


def apply_curated_operators_gold(
    settings: Settings,
    *,
    refresh_synthesis_report: bool = False,
) -> dict[str, object]:
    return _apply_curated_gold(
        settings,
        spec=CURATED_OPERATORS_SPEC,
        document_builder=build_curated_operators_document,
        refresh_synthesis_report=refresh_synthesis_report,
    )


CURATED_LOGGING_BOOK_SLUG = "logging"
CURATED_LOGGING_TITLE = "클러스터 로깅 운영 플레이북"
CURATED_LOGGING_SOURCE_URL = (
    "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/"
    "html-single/logging/index"
)
CURATED_LOGGING_TRANSLATION_SOURCE_URL = (
    "https://docs.redhat.com/en/documentation/openshift_container_platform/4.20/"
    "html-single/logging/index"
)
CURATED_LOGGING_INDEX_URL = (
    "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/"
)
CURATED_LOGGING_VIEWER_BASE_PATH = "/docs/ocp/4.20/ko/logging/index.html"
CURATED_LOGGING_SOURCE_ID = (
    "openshift_container_platform:4.20:ko:logging:curated_gold_v1"
)
CURATED_LOGGING_UPDATED_AT = "2026-04-18T00:00:00Z"
CURATED_LOGGING_LICENSE = "OpenShift documentation is licensed under the Apache License 2.0."


def _logging_provenance_notes() -> tuple[str, ...]:
    return (
        "curated_logging_gold_v1",
        "separate_logging_docs_family_repackaged_as_reader_grade_playbook",
        "landing_summary_replaced_by_reviewed_ko_playbook",
    )


CURATED_LOGGING_SPEC = CuratedGoldSpec(
    book_slug=CURATED_LOGGING_BOOK_SLUG,
    title=CURATED_LOGGING_TITLE,
    source_url=CURATED_LOGGING_SOURCE_URL,
    translation_source_url=CURATED_LOGGING_TRANSLATION_SOURCE_URL,
    index_url=CURATED_LOGGING_INDEX_URL,
    viewer_base_path=CURATED_LOGGING_VIEWER_BASE_PATH,
    source_id=CURATED_LOGGING_SOURCE_ID,
    updated_at=CURATED_LOGGING_UPDATED_AT,
    license_or_terms=CURATED_LOGGING_LICENSE,
    original_title="Logging",
    vendor_title="Logging",
    approval_notes="curated logging gold sample from official EN docs and repo sidecars",
    notes=_logging_provenance_notes(),
    source_state_reason="curated_translation_ready_promoted_from_official_en_bundle",
)


def _build_logging_provenance() -> AstProvenance:
    return _build_curated_provenance(CURATED_LOGGING_SPEC)


def _logging_section(
    *,
    ordinal: int,
    heading: str,
    anchor: str,
    semantic_role: str,
    blocks: tuple[object, ...],
    path: tuple[str, ...] | None = None,
    level: int = 2,
) -> CanonicalSectionAst:
    return _section_for(
        CURATED_LOGGING_SPEC,
        ordinal=ordinal,
        heading=heading,
        anchor=anchor,
        semantic_role=semantic_role,
        blocks=blocks,
        path=path,
        level=level,
    )


def build_curated_logging_document() -> CanonicalDocumentAst:
    sections = (
        _logging_section(
            ordinal=1,
            heading="로깅 운영 개요",
            anchor="logging-playbook-overview",
            semantic_role="overview",
            blocks=(
                ParagraphBlock(
                    "OpenShift 로깅은 애플리케이션, 인프라, 감사 로그를 수집하고 "
                    "전달 경로와 저장소를 운영 기준으로 정리하는 별도 문서 세트다. "
                    "이 플레이북은 landing summary 대신 운영자가 바로 쓰는 판단 축만 다시 묶은 수동서다."
                ),
                ParagraphBlock(
                    "핵심 질문은 세 가지다. 어떤 로그를 수집할지, 어디로 전달할지, "
                    "그리고 장애 시 어느 컴포넌트부터 좁힐지다."
                ),
            ),
        ),
        _logging_section(
            ordinal=2,
            heading="먼저 분리해야 하는 운영 축",
            anchor="logging-core-decisions",
            semantic_role="concept",
            blocks=(
                ParagraphBlock(
                    "클러스터 로깅을 볼 때는 애플리케이션 로그, 인프라 로그, 감사 로그를 "
                    "같은 저장소 요구사항으로 묶지 말아야 한다. "
                    "수집 대상과 보존 정책, 전달 대상이 서로 다를 수 있기 때문이다."
                ),
                ParagraphBlock(
                    "또한 OpenShift 본체 릴리스와 로깅 릴리스 주기는 다를 수 있으므로, "
                    "문제 조사와 운영 변경은 로깅 전용 문서 세트 기준으로 확인해야 한다."
                ),
            ),
        ),
        _logging_section(
            ordinal=3,
            heading="구성 변경은 logging API 경로로만 한다",
            anchor="logging-supported-configuration-boundary",
            semantic_role="concept",
            blocks=(
                ParagraphBlock(
                    "지원되는 변경 경로는 로깅 operator가 관리하는 API와 리소스다. "
                    "수집기 pod 안 설정 파일을 직접 수정하는 방식은 운영 기준에서 제외해야 한다."
                ),
                ParagraphBlock(
                    "특히 log forwarding은 `ClusterLogForwarder` 와 관련 output 정의를 중심으로 보고, "
                    "collector나 store 내부 설정을 직접 우회하지 않는 것이 안전하다."
                ),
                NoteBlock(
                    title="중요",
                    variant="important",
                    text=(
                        "landing summary를 더 잘 쪼개는 것으로는 운영 지식이 깊어지지 않는다. "
                        "지원되는 API 경계와 verification 루프를 먼저 고정해야 한다."
                    ),
                ),
            ),
        ),
        _logging_section(
            ordinal=4,
            heading="설정 전 운영자가 먼저 정할 것",
            anchor="logging-first-decisions",
            semantic_role="procedure",
            blocks=(
                ParagraphBlock(
                    "설정 전에 먼저 정해야 하는 것은 로그 출력 대상, 장기 저장 필요 여부, "
                    "감사 로그 분리 여부, 그리고 외부 전송이 필요한지다."
                ),
                PrerequisiteBlock(
                    items=(
                        "감사 로그가 규정상 별도 보관 대상인지 확인한다.",
                        "외부 SIEM 또는 장기 저장소로 forwarding 해야 하는지 결정한다.",
                        "애플리케이션 로그와 인프라 로그를 같은 retention 기준으로 둘지 분리할지 정한다.",
                    )
                ),
            ),
        ),
        _logging_section(
            ordinal=5,
            heading="기본 상태 확인 루프",
            anchor="logging-verification-loop",
            semantic_role="procedure",
            blocks=(
                ParagraphBlock(
                    "문제가 생기기 전에도 먼저 보는 순서는 같다. operator와 collector가 살아 있는지, "
                    "forwarder 정의가 기대와 맞는지, output 연결이 정상인지 순서대로 본다."
                ),
                CodeBlock(
                    language="bash",
                    caption="로깅 기본 상태 확인",
                    code=(
                        "oc get pods -n openshift-logging\n"
                        "oc get clusterlogforwarder -n openshift-logging\n"
                        "oc get clusterlogging -n openshift-logging"
                    ),
                ),
                ParagraphBlock(
                    "collector pod가 비정상이면 수집 단계부터 좁히고, "
                    "forwarder 리소스는 있는데 출력이 비정상이면 output 경로와 인증 정보를 다음 분기로 본다."
                ),
            ),
        ),
        _logging_section(
            ordinal=6,
            heading="forwarding 중심으로 읽어야 한다",
            anchor="logging-forwarding-model",
            semantic_role="procedure",
            blocks=(
                ParagraphBlock(
                    "실제 운영에서는 저장보다 forwarding이 더 자주 바뀐다. "
                    "따라서 변경은 `ClusterLogForwarder` 파이프라인 기준으로 읽고 검증하는 편이 낫다."
                ),
                CodeBlock(
                    language="yaml",
                    caption="ClusterLogForwarder 개념 예시",
                    code=(
                        "apiVersion: observability.openshift.io/v1\n"
                        "kind: ClusterLogForwarder\n"
                        "metadata:\n"
                        "  name: instance\n"
                        "  namespace: openshift-logging\n"
                        "spec:\n"
                        "  pipelines:\n"
                        "  - name: app-to-default\n"
                        "    inputRefs:\n"
                        "    - application\n"
                        "    outputRefs:\n"
                        "    - default"
                    ),
                ),
                ParagraphBlock(
                    "구성 변경 뒤에는 파이프라인 자체보다 collector 상태와 output 도달 여부를 같이 확인해야 한다."
                ),
            ),
        ),
        _logging_section(
            ordinal=7,
            heading="문제가 생기면 좁히는 순서",
            anchor="logging-troubleshooting-sequence",
            semantic_role="procedure",
            blocks=(
                ParagraphBlock(
                    "로그가 안 보일 때는 곧바로 저장소부터 의심하지 말고, "
                    "1) collector 정상 여부, 2) forwarder 정의, 3) output 연결, 4) 대상 시스템 수신 여부 순서로 좁힌다."
                ),
                CodeBlock(
                    language="bash",
                    caption="collector 로그와 이벤트 확인",
                    code=(
                        "oc logs -n openshift-logging daemonset/collector\n"
                        "oc get events -n openshift-logging --sort-by=.metadata.creationTimestamp"
                    ),
                ),
                NoteBlock(
                    title="주의",
                    variant="warning",
                    text=(
                        "collector 또는 output pod 내부 파일을 직접 수정해 임시 복구하는 방식은 "
                        "operator reconciliation과 충돌할 수 있다."
                    ),
                ),
            ),
        ),
        _logging_section(
            ordinal=8,
            heading="작업 후 다음 분기",
            anchor="logging-next-branches",
            semantic_role="reference",
            blocks=(
                ParagraphBlock(
                    "수집 자체가 안 되면 collector와 node 측 로그 접근 권한을 다시 확인하고, "
                    "수집은 되는데 외부 시스템에 안 보이면 forwarding/output 경로를 다음 분기로 본다."
                ),
                ParagraphBlock(
                    "감사 로그나 장기 보관 정책이 요구되면 retention과 external destination 설계를 "
                    "다음 작업으로 분리하는 편이 안전하다."
                ),
                ParagraphBlock(
                    "기본 루프가 안정화된 뒤에야 advanced filtering, multi-destination forwarding, "
                    "전용 분석 플랫폼 연동으로 넘어간다."
                ),
            ),
        ),
    )
    return _build_curated_document(CURATED_LOGGING_SPEC, sections)


def _curated_logging_manifest_entry() -> SourceManifestEntry:
    return _curated_manifest_entry(CURATED_LOGGING_SPEC)


def apply_curated_logging_gold(
    settings: Settings,
    *,
    refresh_synthesis_report: bool = False,
) -> dict[str, object]:
    return _apply_curated_gold(
        settings,
        spec=CURATED_LOGGING_SPEC,
        document_builder=build_curated_logging_document,
        refresh_synthesis_report=refresh_synthesis_report,
    )


CURATED_MONITORING_BOOK_SLUG = "monitoring"
CURATED_MONITORING_TITLE = "클러스터 모니터링 운영 플레이북"
CURATED_MONITORING_SOURCE_URL = (
    "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/"
    "html-single/monitoring/index"
)
CURATED_MONITORING_TRANSLATION_SOURCE_URL = (
    "https://docs.redhat.com/en/documentation/openshift_container_platform/4.20/"
    "html-single/monitoring/index"
)
CURATED_MONITORING_INDEX_URL = (
    "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/"
)
CURATED_MONITORING_VIEWER_BASE_PATH = "/docs/ocp/4.20/ko/monitoring/index.html"
CURATED_MONITORING_SOURCE_ID = (
    "openshift_container_platform:4.20:ko:monitoring:curated_gold_v1"
)
CURATED_MONITORING_UPDATED_AT = "2026-04-10T00:00:00Z"
CURATED_MONITORING_LICENSE = "OpenShift documentation is licensed under the Apache License 2.0."


def _monitoring_provenance_notes() -> tuple[str, ...]:
    return (
        "curated_monitoring_gold_v1",
        "translation_ready_promoted_from_official_en_and_repo_sidecars",
        "official_ko_fallback_replaced_by_reviewed_ko_playbook",
    )


CURATED_MONITORING_SPEC = CuratedGoldSpec(
    book_slug=CURATED_MONITORING_BOOK_SLUG,
    title=CURATED_MONITORING_TITLE,
    source_url=CURATED_MONITORING_SOURCE_URL,
    translation_source_url=CURATED_MONITORING_TRANSLATION_SOURCE_URL,
    index_url=CURATED_MONITORING_INDEX_URL,
    viewer_base_path=CURATED_MONITORING_VIEWER_BASE_PATH,
    source_id=CURATED_MONITORING_SOURCE_ID,
    updated_at=CURATED_MONITORING_UPDATED_AT,
    license_or_terms=CURATED_MONITORING_LICENSE,
    original_title="Monitoring",
    vendor_title="Monitoring",
    approval_notes="curated monitoring gold sample from official EN docs and repo sidecars",
    notes=_monitoring_provenance_notes(),
    source_state_reason="curated_translation_ready_promoted_from_official_en_bundle",
)


def _build_monitoring_provenance() -> AstProvenance:
    return _build_curated_provenance(CURATED_MONITORING_SPEC)


def _monitoring_section(
    *,
    ordinal: int,
    heading: str,
    anchor: str,
    semantic_role: str,
    blocks: tuple[object, ...],
    path: tuple[str, ...] | None = None,
    level: int = 2,
) -> CanonicalSectionAst:
    return _section_for(
        CURATED_MONITORING_SPEC,
        ordinal=ordinal,
        heading=heading,
        anchor=anchor,
        semantic_role=semantic_role,
        blocks=blocks,
        path=path,
        level=level,
    )


def build_curated_monitoring_document() -> CanonicalDocumentAst:
    sections = (
        _monitoring_section(
            ordinal=1,
            heading="모니터링 운영 개요",
            anchor="monitoring-playbook-overview",
            semantic_role="overview",
            blocks=(
                ParagraphBlock(
                    "OpenShift 4.20은 core platform component를 위한 모니터링 스택을 "
                    "기본 설치, 기본 구성, 자동 업데이트 상태로 제공합니다. "
                    "이 플레이북은 운영자가 실제로 자주 하는 판단과 설정 작업만 "
                    "curated gold 형태로 다시 묶은 수동서입니다."
                ),
                ParagraphBlock(
                    "핵심 구분은 두 가지입니다. 기본 제공되는 core platform monitoring과, "
                    "선택적으로 켜는 user-defined project monitoring을 분리해서 다뤄야 합니다."
                ),
            ),
        ),
        _monitoring_section(
            ordinal=2,
            heading="지원되는 설정 경로만 사용해야 한다",
            anchor="monitoring-supported-configuration-boundary",
            semantic_role="concept",
            blocks=(
                ParagraphBlock(
                    "공식 문서 기준으로 모니터링 스택의 지원되는 설정 경로는 "
                    "Cluster Monitoring Operator가 노출한 config map뿐입니다."
                ),
                ParagraphBlock(
                    "`cluster-monitoring-config` 는 `openshift-monitoring` namespace에서 "
                    "core monitoring stack을 제어하고, `user-workload-monitoring-config` 는 "
                    "`openshift-user-workload-monitoring` namespace에서 user workload monitoring을 제어합니다."
                ),
                NoteBlock(
                    title="중요",
                    variant="important",
                    text=(
                        "문서에 없는 임의 설정을 쓰면 CMO가 reconciliation 과정에서 다시 덮어쓸 수 있습니다. "
                        "unsupported configuration은 운영 기준에서 바로 제외해야 합니다."
                    ),
                ),
            ),
        ),
        _monitoring_section(
            ordinal=3,
            heading="설치 직후 운영자가 먼저 판단할 것",
            anchor="monitoring-first-decisions",
            semantic_role="concept",
            blocks=(
                ParagraphBlock(
                    "설치 직후에는 기본 메트릭 수집이 이미 시작됩니다. 운영자가 바로 정해야 하는 것은 "
                    "알림 수신 경로, persistent storage, remote write 필요 여부, 그리고 "
                    "user-defined project monitoring을 켤지 여부입니다."
                ),
                ParagraphBlock(
                    "문서 기준으로 multi-node cluster에서는 Prometheus, Alertmanager, Thanos Ruler에 "
                    "persistent storage를 구성해야 high availability를 보장할 수 있습니다."
                ),
                ParagraphBlock(
                    "storage가 비어 있으면 monitoring ClusterOperator가 "
                    "`PrometheusDataPersistenceNotConfigured` 상태 메시지로 이를 알려줍니다."
                ),
            ),
        ),
        _monitoring_section(
            ordinal=4,
            heading="cluster-monitoring-config 최소 골격",
            anchor="monitoring-core-configmap",
            semantic_role="procedure",
            blocks=(
                ParagraphBlock(
                    "core platform monitoring의 모든 정식 설정은 `cluster-monitoring-config` 의 "
                    "`data.config.yaml` 아래에 선언합니다."
                ),
                CodeBlock(
                    language="yaml",
                    caption="cluster-monitoring-config 최소 예시",
                    code=(
                        "apiVersion: v1\n"
                        "kind: ConfigMap\n"
                        "metadata:\n"
                        "  name: cluster-monitoring-config\n"
                        "  namespace: openshift-monitoring\n"
                        "data:\n"
                        "  config.yaml: |\n"
                        "    enableUserWorkload: true"
                    ),
                ),
                ParagraphBlock(
                    "`enableUserWorkload` 는 user-defined project monitoring을 여는 핵심 스위치입니다. "
                    "추가로 Prometheus, Alertmanager, Thanos Querier, node-exporter, monitoring plugin 같은 "
                    "구성도 이 config map 계열로 제어합니다."
                ),
            ),
        ),
        _monitoring_section(
            ordinal=5,
            heading="user workload monitoring을 열 때의 기준",
            anchor="monitoring-user-workload",
            semantic_role="procedure",
            blocks=(
                ParagraphBlock(
                    "user-defined project monitoring을 켜면 개발자와 비관리자 사용자도 자기 프로젝트의 "
                    "메트릭을 조회하고, alerting rule과 alert routing을 구성할 수 있게 됩니다."
                ),
                CodeBlock(
                    language="yaml",
                    caption="user-workload-monitoring-config 최소 예시",
                    code=(
                        "apiVersion: v1\n"
                        "kind: ConfigMap\n"
                        "metadata:\n"
                        "  name: user-workload-monitoring-config\n"
                        "  namespace: openshift-user-workload-monitoring\n"
                        "data:\n"
                        "  config.yaml: |\n"
                        "    # user workload monitoring 관련 지원 필드만 선언합니다."
                    ),
                ),
                PrerequisiteBlock(
                    items=(
                        "`monitoring-rules-view`, `monitoring-rules-edit`, `monitoring-edit` 같은 cluster role을 역할에 맞게 부여합니다.",
                        "`user-workload-monitoring-config-edit` role을 통해 비관리자에게 alert routing 설정 권한을 줄 수 있습니다.",
                    )
                ),
            ),
        ),
        _monitoring_section(
            ordinal=6,
            heading="설정 후 상태를 확인하는 기본 루프",
            anchor="monitoring-verification-loop",
            semantic_role="procedure",
            blocks=(
                ParagraphBlock(
                    "설정 후에는 먼저 config map이 기대대로 선언됐는지, 그 다음 monitoring namespace의 pod가 "
                    "정상적으로 재조정됐는지 확인하는 순서가 가장 안전합니다."
                ),
                CodeBlock(
                    language="bash",
                    caption="모니터링 설정과 pod 상태 확인",
                    code=(
                        "oc get configmap cluster-monitoring-config -n openshift-monitoring -o yaml\n"
                        "oc get configmap user-workload-monitoring-config -n openshift-user-workload-monitoring -o yaml\n"
                        "oc get pods -n openshift-monitoring\n"
                        "oc get pods -n openshift-user-workload-monitoring"
                    ),
                ),
                ParagraphBlock(
                    "core monitoring만 쓰는 경우에도 `openshift-monitoring` pod 상태는 반드시 확인합니다. "
                    "user workload monitoring을 켰다면 두 namespace를 같이 봐야 실제 기능이 열린 상태인지 판단할 수 있습니다."
                ),
            ),
        ),
        _monitoring_section(
            ordinal=7,
            heading="경고와 장애를 해석하는 기준",
            anchor="monitoring-alerts-and-troubleshooting",
            semantic_role="concept",
            blocks=(
                ParagraphBlock(
                    "문서의 troubleshooting 축은 세 가지입니다. "
                    "user-defined metrics가 안 보이는 경우, Prometheus가 디스크를 과도하게 쓰는 경우, "
                    "그리고 `AlertmanagerReceiversNotConfigured` 같은 경고가 뜨는 경우입니다."
                ),
                ParagraphBlock(
                    "`AlertmanagerReceiversNotConfigured` 는 알림 수신 경로가 아직 준비되지 않았다는 뜻입니다. "
                    "반대로 `PrometheusDataPersistenceNotConfigured` 는 storage 미구성 상태를 먼저 해소하라는 신호입니다."
                ),
                NoteBlock(
                    title="주의",
                    variant="warning",
                    text=(
                        "문제 증상을 바로 Prometheus 내부 설정으로 우회하지 마십시오. "
                        "공식 문서가 허용한 config map 경로와 supported field만 사용해야 CMO와 충돌하지 않습니다."
                    ),
                ),
            ),
        ),
        _monitoring_section(
            ordinal=8,
            heading="작업 후 다음 분기",
            anchor="monitoring-next-branches",
            semantic_role="reference",
            blocks=(
                ParagraphBlock(
                    "알림이 오지 않으면 alert receiver와 Alertmanager 설정부터 보고, "
                    "스토리지 경고가 보이면 persistent storage와 retention 설정을 먼저 조정합니다."
                ),
                ParagraphBlock(
                    "개발자 메트릭이 안 보이면 `enableUserWorkload` 설정, 관련 role 부여, "
                    "`openshift-user-workload-monitoring` namespace 상태를 다음 분기로 확인합니다."
                ),
                ParagraphBlock(
                    "이 기본 루프가 안정화된 뒤에야 remote write, performance tuning, "
                    "custom alert rule 최적화 같은 고급 설정으로 넘어가는 것이 맞습니다."
                ),
            ),
        ),
    )
    return _build_curated_document(CURATED_MONITORING_SPEC, sections)


def _curated_monitoring_manifest_entry() -> SourceManifestEntry:
    return _curated_manifest_entry(CURATED_MONITORING_SPEC)


def apply_curated_monitoring_gold(
    settings: Settings,
    *,
    refresh_synthesis_report: bool = False,
) -> dict[str, object]:
    return _apply_curated_gold(
        settings,
        spec=CURATED_MONITORING_SPEC,
        document_builder=build_curated_monitoring_document,
        refresh_synthesis_report=refresh_synthesis_report,
    )


CURATED_INSTALLING_ANY_BOOK_SLUG = "installing_on_any_platform"
CURATED_INSTALLING_ANY_TITLE = "플랫폼 비종속 설치 플레이북"
CURATED_INSTALLING_ANY_SOURCE_URL = (
    "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/"
    "html-single/installing_on_any_platform/index"
)
CURATED_INSTALLING_ANY_TRANSLATION_SOURCE_URL = (
    "https://docs.redhat.com/en/documentation/openshift_container_platform/4.20/"
    "html-single/installing_on_any_platform/index"
)
CURATED_INSTALLING_ANY_INDEX_URL = (
    "https://docs.redhat.com/ko/documentation/openshift_container_platform/4.20/"
)
CURATED_INSTALLING_ANY_VIEWER_BASE_PATH = "/docs/ocp/4.20/ko/installing_on_any_platform/index.html"
CURATED_INSTALLING_ANY_SOURCE_ID = (
    "openshift_container_platform:4.20:ko:installing_on_any_platform:curated_gold_v1"
)
CURATED_INSTALLING_ANY_UPDATED_AT = "2026-04-10T00:00:00Z"
CURATED_INSTALLING_ANY_LICENSE = "OpenShift documentation is licensed under the Apache License 2.0."


def _installing_any_provenance_notes() -> tuple[str, ...]:
    return (
        "curated_installing_on_any_platform_gold_v1",
        "manual_review_promoted_from_translation_ready_bundle",
        "official_en_platform_agnostic_installation_docs_reviewed",
    )


CURATED_INSTALLING_ANY_SPEC = CuratedGoldSpec(
    book_slug=CURATED_INSTALLING_ANY_BOOK_SLUG,
    title=CURATED_INSTALLING_ANY_TITLE,
    source_url=CURATED_INSTALLING_ANY_SOURCE_URL,
    translation_source_url=CURATED_INSTALLING_ANY_TRANSLATION_SOURCE_URL,
    index_url=CURATED_INSTALLING_ANY_INDEX_URL,
    viewer_base_path=CURATED_INSTALLING_ANY_VIEWER_BASE_PATH,
    source_id=CURATED_INSTALLING_ANY_SOURCE_ID,
    updated_at=CURATED_INSTALLING_ANY_UPDATED_AT,
    license_or_terms=CURATED_INSTALLING_ANY_LICENSE,
    original_title="Installing a cluster on any platform",
    vendor_title="Installing on any platform",
    approval_notes="curated any-platform installation gold sample from official EN docs and repo sidecars",
    notes=_installing_any_provenance_notes(),
    source_state_reason="curated_translation_ready_promoted_from_official_en_bundle",
)


def _build_installing_any_provenance() -> AstProvenance:
    return _build_curated_provenance(CURATED_INSTALLING_ANY_SPEC)


def _installing_any_section(
    *,
    ordinal: int,
    heading: str,
    anchor: str,
    semantic_role: str,
    blocks: tuple[object, ...],
    path: tuple[str, ...] | None = None,
    level: int = 2,
) -> CanonicalSectionAst:
    return _section_for(
        CURATED_INSTALLING_ANY_SPEC,
        ordinal=ordinal,
        heading=heading,
        anchor=anchor,
        semantic_role=semantic_role,
        blocks=blocks,
        path=path,
        level=level,
    )


def build_curated_installing_on_any_platform_document() -> CanonicalDocumentAst:
    sections = (
        _installing_any_section(
            ordinal=1,
            heading="플랫폼 비종속 설치 개요",
            anchor="installing-any-overview",
            semantic_role="overview",
            blocks=(
                ParagraphBlock(
                    "이 플레이북은 OpenShift 4.20을 user-provisioned infrastructure 방식으로 "
                    "설치할 때 운영자가 실제로 따라가야 하는 핵심 흐름만 추린 curated gold 수동서입니다."
                ),
                ParagraphBlock(
                    "핵심 축은 준비, install-config 작성, manifests/ignition 생성, "
                    "bootstrap 완료 대기, CSR 승인, 설치 직후 검증과 장애 대응입니다."
                ),
                NoteBlock(
                    title="중요",
                    variant="important",
                    text=(
                        "공식 문서 기준으로 any platform 설치는 테스트된 특정 클라우드 자동화가 아니라 "
                        "사용자가 DNS, load balancer, 네트워크, 머신 준비를 직접 책임지는 흐름입니다."
                    ),
                ),
            ),
        ),
        _installing_any_section(
            ordinal=2,
            heading="설치 전에 먼저 닫아야 할 전제조건",
            anchor="installing-any-prerequisites",
            semantic_role="concept",
            blocks=(
                PrerequisiteBlock(
                    items=(
                        "설치 및 업데이트 프로세스와 cluster installation method 선택 기준을 먼저 검토합니다.",
                        "방화벽이나 프록시가 있다면 클러스터가 접근해야 하는 외부 사이트를 미리 허용합니다.",
                        "DNS, load balancer, base domain, reverse DNS 같은 user-provisioned 인프라 요구사항을 설치 전에 확정합니다.",
                    )
                ),
                ParagraphBlock(
                    "공식 any platform 문서는 Kubernetes API용 `api.<cluster_name>.<base_domain>`, "
                    "내부 API용 `api-int.<cluster_name>.<base_domain>`, "
                    "애플리케이션 wildcard용 `*.apps.<cluster_name>.<base_domain>` 레코드를 "
                    "설치 전에 갖춰야 한다고 명시합니다."
                ),
                CodeBlock(
                    language="bash",
                    caption="DNS 검증 예시",
                    code="dig +noall +answer @<nameserver_ip> api.<cluster_name>.<base_domain>",
                ),
            ),
        ),
        _installing_any_section(
            ordinal=3,
            heading="초기 준비와 install-config 핵심값",
            anchor="installing-any-install-config",
            semantic_role="procedure",
            blocks=(
                ParagraphBlock(
                    "SSH 키와 설치 디렉터리를 먼저 준비하고, `install-config.yaml` 을 "
                    "정확한 cluster name, baseDomain, networking, pull secret 기준으로 작성합니다."
                ),
                CodeBlock(
                    language="bash",
                    caption="SSH 키 생성",
                    code="ssh-keygen -t ed25519 -N '' -f <path>/<file_name>",
                ),
                CodeBlock(
                    language="yaml",
                    caption="install-config 핵심값 예시",
                    code=(
                        "apiVersion: v1\n"
                        "baseDomain: example.com\n"
                        "metadata:\n"
                        "  name: <cluster_name>\n"
                        "platform:\n"
                        "  none: {}\n"
                        "compute:\n"
                        "- name: worker\n"
                        "  replicas: 0\n"
                        "controlPlane:\n"
                        "  name: master\n"
                        "  replicas: 3"
                    ),
                ),
                NoteBlock(
                    title="주의",
                    variant="warning",
                    text=(
                        "공식 문서 기준으로 user-provisioned 설치에서는 `compute.replicas` 를 `0` 으로 두고 "
                        "worker 노드를 수동으로 준비해야 합니다. `install-config.yaml` 은 다음 단계에서 소모되므로 "
                        "즉시 백업합니다."
                    ),
                ),
            ),
        ),
        _installing_any_section(
            ordinal=4,
            heading="Manifest와 Ignition 산출물 생성",
            anchor="installing-any-manifests-and-ignition",
            semantic_role="procedure",
            blocks=(
                ParagraphBlock(
                    "설치 디렉터리 안에 `install-config.yaml` 을 준비한 뒤 Kubernetes manifests 와 "
                    "Ignition 파일을 순서대로 생성합니다."
                ),
                ProcedureBlock(
                    steps=(
                        ProcedureStep(1, "설치 프로그램이 있는 디렉터리로 이동합니다."),
                        ProcedureStep(2, "`create manifests` 로 클러스터 manifests 를 생성합니다."),
                        ProcedureStep(3, "필요한 설치 커스터마이징을 반영한 뒤 `create ignition-configs` 를 실행합니다."),
                    )
                ),
                CodeBlock(
                    language="bash",
                    caption="manifests 생성",
                    code="./openshift-install create manifests --dir <installation_directory>",
                ),
                CodeBlock(
                    language="bash",
                    caption="ignition 생성",
                    code="./openshift-install create ignition-configs --dir <installation_directory>",
                ),
            ),
        ),
        _installing_any_section(
            ordinal=5,
            heading="부트스트랩과 설치 완료 대기",
            anchor="installing-any-bootstrap-and-complete",
            semantic_role="procedure",
            blocks=(
                ParagraphBlock(
                    "Ignition 파일을 각 노드에 배포하고 bootstrap 머신과 control plane, worker 머신을 띄운 뒤 "
                    "먼저 bootstrap 완료를 기다리고, 이어서 전체 설치 완료를 대기합니다."
                ),
                CodeBlock(
                    language="bash",
                    caption="bootstrap 완료 대기",
                    code=(
                        "./openshift-install --dir <installation_directory> wait-for bootstrap-complete \\\n"
                        "    --log-level=info"
                    ),
                ),
                CodeBlock(
                    language="bash",
                    caption="설치 완료 대기",
                    code="./openshift-install wait-for install-complete --log-level debug",
                ),
                ParagraphBlock(
                    "bootstrap 단계가 길어지면 먼저 API와 bootstrap 진행 로그를 보고, "
                    "그 뒤 DNS, load balancer, 방화벽 쪽 연결성을 다시 확인하는 순서가 안전합니다."
                ),
            ),
        ),
        _installing_any_section(
            ordinal=6,
            heading="CSR 승인과 초기 Operator 안정화",
            anchor="installing-any-csr-and-operators",
            semantic_role="procedure",
            blocks=(
                ParagraphBlock(
                    "클러스터 API 접근이 열리면 pending CSR을 승인하고, control plane과 worker가 "
                    "정상적으로 노드에 합류하는지 확인합니다."
                ),
                CodeBlock(
                    language="bash",
                    caption="대기 중인 CSR 일괄 승인",
                    code=(
                        "oc get csr -o go-template='{{range .items}}{{if not .status}}{{.metadata.name}}{{\"\\n\"}}{{end}}{{end}}' "
                        "| xargs --no-run-if-empty oc adm certificate approve"
                    ),
                ),
                CodeBlock(
                    language="bash",
                    caption="노드와 Operator 상태 확인",
                    code=(
                        "oc get nodes\n"
                        "watch -n5 oc get clusteroperators"
                    ),
                ),
                ParagraphBlock(
                    "공식 문서 기준으로 CSR 승인 뒤에는 초기 Operator 구성을 마치고, "
                    "registry storage와 restricted network용 OperatorHub 설정 같은 후속 구성을 이어갑니다."
                ),
            ),
        ),
        _installing_any_section(
            ordinal=7,
            heading="설치 직후 검증 루프",
            anchor="installing-any-validation",
            semantic_role="procedure",
            blocks=(
                ParagraphBlock(
                    "설치 직후 검증은 설치 로그 확인, cluster version 확인, node 상태 확인, "
                    "cluster operator 진행 상황 확인 순서로 돌리는 것이 가장 안정적입니다."
                ),
                CodeBlock(
                    language="bash",
                    caption="설치 직후 기본 검증",
                    code=(
                        "oc get clusterversion\n"
                        "oc get nodes\n"
                        "watch -n5 oc get clusteroperators"
                    ),
                ),
                ParagraphBlock(
                    "검증 문서 축에는 installation log 확인, image pull source 확인, "
                    "node health 확인, firing alerts 확인 절차가 함께 묶여 있습니다."
                ),
            ),
        ),
        _installing_any_section(
            ordinal=8,
            heading="설치 실패 시 다음 분기",
            anchor="installing-any-troubleshooting",
            semantic_role="reference",
            blocks=(
                ParagraphBlock(
                    "설치 실패 시에는 bootstrap 로그와 control plane 로그를 먼저 수집하고, "
                    "debug output 에 network timeout 이 보이면 방화벽과 load balancer 로그를 바로 확인합니다."
                ),
                CodeBlock(
                    language="bash",
                    caption="설치 디버그와 gather 전제",
                    code="./openshift-install gather",
                ),
                ParagraphBlock(
                    "공식 troubleshooting 문서 기준 다음 분기는 세 가지입니다. "
                    "bootstrap 로그 수집, SSH 여부에 따른 수동 로그 수집, 설치 재시작 여부 판단입니다."
                ),
                ParagraphBlock(
                    "설치가 끝난 뒤에는 post-install cluster tasks, registry storage 구성, "
                    "cluster customization 순으로 넘어가는 것이 공식 next step입니다."
                ),
            ),
        ),
    )
    return _build_curated_document(CURATED_INSTALLING_ANY_SPEC, sections)


def _curated_installing_any_manifest_entry() -> SourceManifestEntry:
    return _curated_manifest_entry(CURATED_INSTALLING_ANY_SPEC)


def apply_curated_installing_on_any_platform_gold(
    settings: Settings,
    *,
    refresh_synthesis_report: bool = False,
) -> dict[str, object]:
    return _apply_curated_gold(
        settings,
        spec=CURATED_INSTALLING_ANY_SPEC,
        document_builder=build_curated_installing_on_any_platform_document,
        refresh_synthesis_report=refresh_synthesis_report,
    )
