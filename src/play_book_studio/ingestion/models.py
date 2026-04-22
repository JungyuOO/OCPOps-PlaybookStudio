# ingestion 단계에서 쓰는 manifest/source entry 데이터 모델 모음.
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Any

SOURCE_STATE_PUBLISHED_NATIVE = "published_native"
SOURCE_STATE_FALLBACK_TO_EN = "fallback_to_en"
SOURCE_STATE_EN_ONLY = "en_only"
SOURCE_STATE_MISSING = "missing"
SOURCE_STATE_BLOCKED = "blocked"

KNOWN_SOURCE_STATES = (
    SOURCE_STATE_PUBLISHED_NATIVE,
    SOURCE_STATE_FALLBACK_TO_EN,
    SOURCE_STATE_EN_ONLY,
    SOURCE_STATE_MISSING,
    SOURCE_STATE_BLOCKED,
)

CONTENT_STATUS_APPROVED_KO = "approved_ko"
CONTENT_STATUS_TRANSLATED_KO_DRAFT = "translated_ko_draft"
CONTENT_STATUS_MIXED = "mixed"
CONTENT_STATUS_EN_ONLY = "en_only"
CONTENT_STATUS_BLOCKED = "blocked"
CONTENT_STATUS_UNKNOWN = "unknown"

KNOWN_CONTENT_STATUSES = (
    CONTENT_STATUS_APPROVED_KO,
    CONTENT_STATUS_TRANSLATED_KO_DRAFT,
    CONTENT_STATUS_MIXED,
    CONTENT_STATUS_EN_ONLY,
    CONTENT_STATUS_BLOCKED,
    CONTENT_STATUS_UNKNOWN,
)

CITATION_ELIGIBLE_STATUSES = (CONTENT_STATUS_APPROVED_KO,)

DEFAULT_TENANT_ID = "public"
DEFAULT_WORKSPACE_ID = "core"
DEFAULT_ACCESS_GROUPS = ("public",)
DEFAULT_PROVIDER_EGRESS_POLICY = "unspecified"
DEFAULT_CLASSIFICATION = "public"
DEFAULT_BUNDLE_SCOPE = "official"
DEFAULT_REDACTION_STATE = "not_required"


def _contract_translation_status(status: str) -> str:
    if status in {"approved_ko", "translated_ko_draft", "review_required", "original", "blocked"}:
        return status
    if status in {CONTENT_STATUS_EN_ONLY, CONTENT_STATUS_MIXED, CONTENT_STATUS_UNKNOWN}:
        return "original" if status == CONTENT_STATUS_EN_ONLY else "review_required"
    return "review_required"


def _contract_review_status(status: str) -> str:
    if status in {"unreviewed", "needs_review", "approved", "rejected"}:
        return status
    if not status.strip():
        return "unreviewed"
    return "needs_review"


def _contract_access_groups(groups: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    if not groups:
        return DEFAULT_ACCESS_GROUPS
    normalized = tuple(str(group).strip() for group in groups if str(group).strip())
    return normalized or DEFAULT_ACCESS_GROUPS


def _contract_approval_state(status: str) -> str:
    review_status = _contract_review_status(status)
    if review_status == "approved":
        return "approved"
    if review_status == "rejected":
        return "rejected"
    if review_status == "needs_review":
        return "review_required"
    return "unreviewed"


def _contract_publication_state(
    publication_state: str,
    *,
    approval_state: str,
    citation_eligible: bool,
) -> str:
    explicit = publication_state.strip()
    if explicit in {"candidate", "published", "blocked", "restricted"}:
        return explicit
    if approval_state == "rejected":
        return "blocked"
    if approval_state == "approved" and citation_eligible:
        return "published"
    return "candidate"


@dataclass(slots=True)
class SourceManifestEntry:
    product_slug: str = "openshift_container_platform"
    ocp_version: str = "4.20"
    docs_language: str = "ko"
    source_kind: str = "source-first"
    book_slug: str = ""
    title: str = ""
    index_url: str = ""
    source_url: str = ""
    resolved_source_url: str = ""
    resolved_language: str = "ko"
    source_state: str = SOURCE_STATE_PUBLISHED_NATIVE
    source_state_reason: str = ""
    catalog_source_label: str = ""
    viewer_path: str = ""
    high_value: bool = False
    vendor_title: str = ""
    content_status: str = CONTENT_STATUS_UNKNOWN
    citation_eligible: bool = False
    citation_block_reason: str = ""
    viewer_strategy: str = "raw_html"
    body_language_guess: str = "unknown"
    hangul_section_ratio: float = 0.0
    hangul_chunk_ratio: float = 0.0
    fallback_detected: bool = False
    source_fingerprint: str = ""
    approval_status: str = "unreviewed"
    approval_notes: str = ""
    source_id: str = ""
    source_lane: str = ""
    source_type: str = "official_doc"
    source_collection: str = "core"
    legal_notice_url: str = ""
    original_title: str = ""
    license_or_terms: str = ""
    review_status: str = "unreviewed"
    trust_score: float = 1.0
    verifiability: str = "anchor_backed"
    updated_at: str = ""
    translation_source_language: str = ""
    translation_target_language: str = "ko"
    translation_source_url: str = ""
    translation_source_fingerprint: str = ""
    translation_stage: str = ""
    tenant_id: str = DEFAULT_TENANT_ID
    workspace_id: str = DEFAULT_WORKSPACE_ID
    pack_id: str = ""
    pack_version: str = ""
    bundle_scope: str = DEFAULT_BUNDLE_SCOPE
    classification: str = DEFAULT_CLASSIFICATION
    access_groups: tuple[str, ...] = field(default_factory=lambda: DEFAULT_ACCESS_GROUPS)
    provider_egress_policy: str = DEFAULT_PROVIDER_EGRESS_POLICY
    approval_state: str = ""
    publication_state: str = ""
    redaction_state: str = DEFAULT_REDACTION_STATE
    primary_input_kind: str = "html_single"
    fallback_input_kind: str = ""
    source_repo: str = ""
    source_branch: str = ""
    source_binding_kind: str = ""
    source_relative_path: str = ""
    source_relative_paths: tuple[str, ...] = field(default_factory=tuple)
    source_mirror_root: str = ""
    fallback_source_url: str = ""
    fallback_viewer_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["access_groups"] = list(_contract_access_groups(self.access_groups))
        payload["source_relative_paths"] = [
            str(path).strip()
            for path in self.source_relative_paths
            if str(path).strip()
        ]
        payload["pack_id"] = self.pack_id or f"{self.product_slug}-{self.ocp_version}-core"
        payload["pack_version"] = self.pack_version or self.ocp_version
        payload["approval_state"] = self.approval_state or _contract_approval_state(
            self.review_status or self.approval_status
        )
        payload["publication_state"] = _contract_publication_state(
            self.publication_state,
            approval_state=str(payload["approval_state"]),
            citation_eligible=bool(self.citation_eligible),
        )
        return payload


@dataclass(slots=True)
class ParsedArtifactRecord:
    parsed_artifact_id: str
    source_ref: dict[str, Any]
    raw_asset_ref: dict[str, Any]
    parser_route: str = "html_native"
    parser_backend: str = "canonical_html_v1"
    parser_version: str = "1.0"
    ocr_strategy: str = "not_required"
    ocr_used: bool = False
    page_refs: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    layout_blocks: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    table_refs: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    figure_refs: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    section_trace_hints: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    language_state: str = "resolved_ko"
    quality_state: dict[str, Any] = field(default_factory=dict)
    security_envelope: dict[str, Any] = field(default_factory=dict)
    promotion_trace: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["page_refs"] = list(self.page_refs)
        payload["layout_blocks"] = list(self.layout_blocks)
        payload["table_refs"] = list(self.table_refs)
        payload["figure_refs"] = list(self.figure_refs)
        payload["section_trace_hints"] = list(self.section_trace_hints)
        source_ref = dict(self.source_ref)
        source_ref["source_id"] = str(source_ref.get("source_id") or "")
        source_ref["source_type"] = str(source_ref.get("source_type") or "official_doc")
        source_ref["source_lane"] = str(source_ref.get("source_lane") or "official_ko")
        source_ref["source_collection"] = str(source_ref.get("source_collection") or "core")
        source_ref["product"] = str(source_ref.get("product") or "openshift")
        source_ref["version"] = str(source_ref.get("version") or "4.20")
        source_ref["locale"] = str(source_ref.get("locale") or "ko")
        payload["source_ref"] = source_ref
        raw_asset_ref = dict(self.raw_asset_ref)
        raw_asset_ref["raw_asset_uri"] = str(raw_asset_ref.get("raw_asset_uri") or "")
        raw_asset_ref["source_fingerprint"] = str(raw_asset_ref.get("source_fingerprint") or "")
        raw_asset_ref["raw_asset_hash"] = str(raw_asset_ref.get("raw_asset_hash") or "")
        payload["raw_asset_ref"] = raw_asset_ref
        quality_state = dict(self.quality_state)
        quality_state["parse_status"] = str(quality_state.get("parse_status") or "parsed")
        quality_state["review_status"] = str(quality_state.get("review_status") or "unreviewed")
        quality_state["trust_score"] = float(quality_state.get("trust_score") or 0.0)
        quality_state["updated_at"] = str(quality_state.get("updated_at") or "")
        payload["quality_state"] = quality_state
        security_envelope = dict(self.security_envelope)
        security_envelope["tenant_id"] = (security_envelope.get("tenant_id") or DEFAULT_TENANT_ID).strip()
        security_envelope["workspace_id"] = (security_envelope.get("workspace_id") or DEFAULT_WORKSPACE_ID).strip()
        security_envelope["pack_id"] = (
            security_envelope.get("pack_id")
            or source_ref["source_id"]
            or "public-core"
        )
        security_envelope["classification"] = (
            security_envelope.get("classification") or DEFAULT_CLASSIFICATION
        ).strip()
        security_envelope["access_groups"] = list(
            _contract_access_groups(security_envelope.get("access_groups"))
        )
        security_envelope["provider_egress_policy"] = (
            security_envelope.get("provider_egress_policy") or DEFAULT_PROVIDER_EGRESS_POLICY
        ).strip()
        security_envelope["redaction_state"] = (
            security_envelope.get("redaction_state") or DEFAULT_REDACTION_STATE
        ).strip()
        payload["security_envelope"] = security_envelope
        promotion_trace = dict(self.promotion_trace)
        promotion_trace["source_stage"] = (
            promotion_trace.get("source_stage") or "bronze_raw"
        ).strip()
        promotion_trace["target_stage"] = (
            promotion_trace.get("target_stage") or "bronze_parsed"
        ).strip()
        promotion_trace["decision"] = (
            promotion_trace.get("decision") or "accepted"
        ).strip()
        promotion_trace["updated_at"] = str(promotion_trace.get("updated_at") or "")
        payload["promotion_trace"] = promotion_trace
        return payload


@dataclass(slots=True)
class NormalizedSection:
    book_slug: str
    book_title: str
    heading: str
    section_level: int
    section_path: list[str]
    anchor: str
    source_url: str
    viewer_path: str
    text: str
    section_id: str = ""
    semantic_role: str = "unknown"
    block_kinds: tuple[str, ...] = field(default_factory=tuple)
    source_language: str = "ko"
    display_language: str = "ko"
    translation_status: str = "approved_ko"
    translation_stage: str = "approved_ko"
    translation_source_language: str = ""
    translation_source_url: str = ""
    translation_source_fingerprint: str = ""
    source_id: str = ""
    source_lane: str = "official_ko"
    source_type: str = "official_doc"
    source_collection: str = "core"
    product: str = "openshift"
    version: str = "4.20"
    locale: str = "ko"
    original_title: str = ""
    legal_notice_url: str = ""
    license_or_terms: str = ""
    review_status: str = "unreviewed"
    trust_score: float = 1.0
    verifiability: str = "anchor_backed"
    updated_at: str = ""
    parsed_artifact_id: str = ""
    tenant_id: str = DEFAULT_TENANT_ID
    workspace_id: str = DEFAULT_WORKSPACE_ID
    parent_pack_id: str = ""
    pack_version: str = ""
    bundle_scope: str = DEFAULT_BUNDLE_SCOPE
    classification: str = DEFAULT_CLASSIFICATION
    access_groups: tuple[str, ...] = field(default_factory=lambda: DEFAULT_ACCESS_GROUPS)
    provider_egress_policy: str = DEFAULT_PROVIDER_EGRESS_POLICY
    approval_state: str = ""
    publication_state: str = ""
    redaction_state: str = DEFAULT_REDACTION_STATE
    cli_commands: tuple[str, ...] = field(default_factory=tuple)
    error_strings: tuple[str, ...] = field(default_factory=tuple)
    k8s_objects: tuple[str, ...] = field(default_factory=tuple)
    operator_names: tuple[str, ...] = field(default_factory=tuple)
    verification_hints: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "book_slug": self.book_slug,
            "book_title": self.book_title,
            "heading": self.heading,
            "section_level": self.section_level,
            "section_path": list(self.section_path),
            "anchor": self.anchor,
            "anchor_id": self.anchor,
            "source_url": self.source_url,
            "viewer_path": self.viewer_path,
            "text": self.text,
            "section_id": self.section_id,
            "semantic_role": self.semantic_role,
            "block_kinds": list(self.block_kinds),
            "source_language": self.source_language,
            "display_language": self.display_language,
            "translation_status": self.translation_status,
            "translation_stage": self.translation_stage,
            "translation_source_language": self.translation_source_language,
            "translation_source_url": self.translation_source_url,
            "translation_source_fingerprint": self.translation_source_fingerprint,
            "source_id": self.source_id,
            "source_lane": self.source_lane,
            "source_type": self.source_type,
            "source_collection": self.source_collection,
            "product": self.product,
            "version": self.version,
            "locale": self.locale,
            "original_title": self.original_title,
            "legal_notice_url": self.legal_notice_url,
            "license_or_terms": self.license_or_terms,
            "review_status": self.review_status,
            "trust_score": self.trust_score,
            "verifiability": self.verifiability,
            "updated_at": self.updated_at,
            "parsed_artifact_id": self.parsed_artifact_id,
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "parent_pack_id": self.parent_pack_id or f"{self.product}-{self.version}-core",
            "pack_version": self.pack_version or self.version,
            "bundle_scope": self.bundle_scope,
            "classification": self.classification,
            "access_groups": list(_contract_access_groups(self.access_groups)),
            "provider_egress_policy": self.provider_egress_policy,
            "approval_state": self.approval_state or _contract_approval_state(self.review_status),
            "publication_state": _contract_publication_state(
                self.publication_state,
                approval_state=self.approval_state or _contract_approval_state(self.review_status),
                citation_eligible=bool(self.translation_status == "approved_ko"),
            ),
            "redaction_state": self.redaction_state,
            "citation_eligible": bool(self.translation_status == "approved_ko"),
            "citation_block_reason": "" if self.translation_status == "approved_ko" else "translation_or_review_pending",
            "cli_commands": list(self.cli_commands),
            "error_strings": list(self.error_strings),
            "k8s_objects": list(self.k8s_objects),
            "operator_names": list(self.operator_names),
            "verification_hints": list(self.verification_hints),
        }

    def to_contract_dict(self) -> dict[str, Any]:
        payload = self.to_dict()
        payload["translation_status"] = _contract_translation_status(self.translation_status)
        payload["review_status"] = _contract_review_status(self.review_status)
        payload["original_title"] = self.original_title or self.book_title
        return payload


@dataclass(slots=True)
class ChunkRecord:
    chunk_id: str
    book_slug: str
    book_title: str
    chapter: str
    section: str
    anchor: str
    source_url: str
    viewer_path: str
    text: str
    token_count: int
    ordinal: int
    section_id: str = ""
    section_path: tuple[str, ...] = field(default_factory=tuple)
    chunk_type: str = "reference"
    source_id: str = ""
    source_lane: str = "official_ko"
    source_type: str = "official_doc"
    source_collection: str = "core"
    product: str = "openshift"
    version: str = "4.20"
    locale: str = "ko"
    source_language: str = "ko"
    display_language: str = "ko"
    translation_status: str = "approved_ko"
    translation_stage: str = "approved_ko"
    translation_source_language: str = ""
    translation_source_url: str = ""
    translation_source_fingerprint: str = ""
    original_title: str = ""
    legal_notice_url: str = ""
    license_or_terms: str = ""
    review_status: str = "unreviewed"
    trust_score: float = 1.0
    verifiability: str = "anchor_backed"
    updated_at: str = ""
    parsed_artifact_id: str = ""
    tenant_id: str = DEFAULT_TENANT_ID
    workspace_id: str = DEFAULT_WORKSPACE_ID
    parent_pack_id: str = ""
    pack_version: str = ""
    bundle_scope: str = DEFAULT_BUNDLE_SCOPE
    classification: str = DEFAULT_CLASSIFICATION
    access_groups: tuple[str, ...] = field(default_factory=lambda: DEFAULT_ACCESS_GROUPS)
    provider_egress_policy: str = DEFAULT_PROVIDER_EGRESS_POLICY
    approval_state: str = ""
    publication_state: str = ""
    redaction_state: str = DEFAULT_REDACTION_STATE
    citation_eligible: bool = False
    citation_block_reason: str = ""
    cli_commands: tuple[str, ...] = field(default_factory=tuple)
    error_strings: tuple[str, ...] = field(default_factory=tuple)
    k8s_objects: tuple[str, ...] = field(default_factory=tuple)
    operator_names: tuple[str, ...] = field(default_factory=tuple)
    verification_hints: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["anchor_id"] = self.anchor
        payload["section_id"] = self.section_id
        payload["section_path"] = list(self.section_path)
        payload["cli_commands"] = list(self.cli_commands)
        payload["error_strings"] = list(self.error_strings)
        payload["k8s_objects"] = list(self.k8s_objects)
        payload["operator_names"] = list(self.operator_names)
        payload["verification_hints"] = list(self.verification_hints)
        payload["parsed_artifact_id"] = self.parsed_artifact_id
        payload["access_groups"] = list(_contract_access_groups(self.access_groups))
        payload["parent_pack_id"] = self.parent_pack_id or f"{self.product}-{self.version}-core"
        payload["pack_version"] = self.pack_version or self.version
        payload["approval_state"] = self.approval_state or _contract_approval_state(self.review_status)
        payload["publication_state"] = _contract_publication_state(
            self.publication_state,
            approval_state=str(payload["approval_state"]),
            citation_eligible=bool(self.citation_eligible),
        )
        return payload


@dataclass(slots=True)
class PipelineLog:
    stage: str = "init"
    manifest_count: int = 0
    collected_count: int = 0
    normalized_count: int = 0
    chunk_count: int = 0
    graph_book_count: int = 0
    graph_relation_count: int = 0
    embedded_count: int = 0
    qdrant_upserted_count: int = 0
    collected_sources: list[str] = field(default_factory=list)
    processed_sources: list[str] = field(default_factory=list)
    per_book_stats: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def add_error(self, stage: str, source: str, message: str) -> None:
        self.errors.append({"stage": stage, "source": source, "message": message})

    def upsert_book_stat(self, book_slug: str, **fields: Any) -> None:
        for item in self.per_book_stats:
            if item.get("book_slug") == book_slug:
                item.update(fields)
                return
        record = {"book_slug": book_slug}
        record.update(fields)
        self.per_book_stats.append(record)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
