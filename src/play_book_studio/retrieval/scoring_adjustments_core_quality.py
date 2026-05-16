from __future__ import annotations

from .models import RetrievalHit
from .scoring_signals import ScoreSignals


def _hit_text(hit: RetrievalHit) -> str:
    return "\n".join(
        (
            hit.book_slug,
            hit.chapter,
            hit.section,
            hit.heading_title,
            hit.text,
            " ".join(hit.section_path),
            " ".join(hit.toc_path),
            " ".join(hit.cli_commands),
            " ".join(hit.k8s_objects),
            " ".join(hit.operator_names),
            " ".join(hit.verification_hints),
        )
    ).lower()


def _has_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _apply_factor(hit: RetrievalHit, key: str, factor: float) -> None:
    hit.fused_score *= factor
    hit.component_scores[key] = factor


def _query_has_registry_storage(query: str) -> bool:
    lowered = query.lower()
    return (
        ("registry" in lowered or "레지스트리" in query)
        and ("storage" in lowered or "스토리지" in query or "저장" in query)
    )


def _query_platform(query: str) -> str:
    lowered = query.lower()
    if "aws" in lowered:
        return "aws"
    if "azure stack hub" in lowered:
        return "azure_stack_hub"
    if "azure" in lowered:
        return "azure"
    if "google cloud" in lowered or "gcp" in lowered:
        return "gcp"
    if "rhosp" in lowered or "openstack" in lowered:
        return "rhosp"
    if "vsphere" in lowered or "vmware" in lowered:
        return "vsphere"
    return ""


def _apply_platform_registry_storage_adjustments(hit: RetrievalHit, *, query: str) -> None:
    if not _query_has_registry_storage(query):
        return
    platform = _query_platform(query)
    if not platform:
        return
    text = _hit_text(hit)
    platform_terms = {
        "aws": ("aws", "s3", "amazon"),
        "azure": ("azure", "azure blob", "azure storage"),
        "azure_stack_hub": ("azure stack hub",),
        "gcp": ("google cloud", "gcp", "gcs", "google storage"),
        "rhosp": ("rhosp", "openstack", "cinder"),
        "vsphere": ("vsphere", "vmware"),
    }
    all_other_terms = tuple(
        token
        for key, values in platform_terms.items()
        if key != platform
        for token in values
    )
    if _has_any(text, platform_terms[platform]):
        _apply_factor(hit, f"v016_{platform}_registry_storage_platform_boost", 1.9)
    if _has_any(text, all_other_terms) and not _has_any(text, platform_terms[platform]):
        _apply_factor(hit, f"v016_{platform}_registry_storage_platform_mismatch_penalty", 0.38)
        return
    if _has_any(text, ("configs.imageregistry.operator.openshift.io", "image registry operator", "이미지 레지스트리")):
        _apply_factor(hit, "v016_registry_operator_boost", 1.22)


def _apply_etcd_adjustments(hit: RetrievalHit, *, query: str) -> None:
    lowered_query = query.lower()
    if "etcd" not in lowered_query:
        return
    text = _hit_text(hit)
    if "조각" in query or "defrag" in lowered_query or "defragment" in lowered_query:
        if _has_any(text, ("defrag", "defragment", "etcdctl")):
            _apply_factor(hit, "v016_etcd_defrag_boost", 2.1)
        if "lsblk" in text and not _has_any(text, ("defrag", "defragment", "etcdctl")):
            _apply_factor(hit, "v016_etcd_defrag_disk_command_penalty", 0.22)
    if "backup" in lowered_query or "백업" in query:
        if _has_any(text, ("cluster-backup.sh", "oc debug", "chroot /host")):
            _apply_factor(hit, "v016_etcd_backup_command_boost", 1.55)
    if "latency" in lowered_query or "대기 시간" in query:
        if _has_any(text, ("etcd_disk", "histogram_quantile", "latency", "prometheus")):
            _apply_factor(hit, "v016_etcd_latency_boost", 1.6)


def _apply_insights_adjustments(hit: RetrievalHit, *, query: str) -> None:
    lowered_query = query.lower()
    if not (
        "insights" in lowered_query
        or "원격 상태 보고" in query
        or "진단 데이터" in query
        or "지원 케이스" in query
        or "must-gather" in lowered_query
    ):
        return
    text = _hit_text(hit)
    if _has_any(text, ("insights operator", "openshift-insights", "remote health", "원격 상태", "support case")):
        _apply_factor(hit, "v016_insights_support_boost", 1.8)
    if _has_any(text, ("oc adm must-gather", "must-gather")):
        _apply_factor(hit, "v016_must_gather_boost", 1.55)
    if "operator catalog" in text or "catalogsource" in text:
        _apply_factor(hit, "v016_insights_operator_catalog_penalty", 0.32)


def _apply_build_security_adjustments(hit: RetrievalHit, *, query: str) -> None:
    if not ("빌드" in query and ("보안" in query or "입력" in query)):
        return
    text = _hit_text(hit)
    if _has_any(text, ("buildconfig", "build input", "source secret", "input secret", "secret")):
        _apply_factor(hit, "v016_build_input_security_boost", 1.8)
    if _has_any(text, ("oauth", "oidc", "authentication.config")) and not _has_any(text, ("buildconfig", "build input")):
        _apply_factor(hit, "v016_build_input_oauth_penalty", 0.28)


def apply_quality_core_adjustments(hit: RetrievalHit, *, signals: ScoreSignals) -> None:
    query = signals.query
    _apply_platform_registry_storage_adjustments(hit, query=query)
    _apply_etcd_adjustments(hit, query=query)
    _apply_insights_adjustments(hit, query=query)
    _apply_build_security_adjustments(hit, query=query)
