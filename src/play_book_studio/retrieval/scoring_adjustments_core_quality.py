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


def _query_has_registry_pvc_config(query: str) -> bool:
    lowered = query.lower()
    return (
        ("registry" in lowered or "레지스트리" in query)
        and "pvc" in lowered
        and (
            "configs.imageregistry" in lowered
            or "spec.storage.pvc" in lowered
            or "필드" in query
            or "설정" in query
        )
    )


def _query_has_etcd_restore_script(query: str) -> bool:
    lowered = query.lower()
    return "etcd" in lowered and any(token in query for token in ("복원", "복구", "restore")) and any(
        token in query for token in ("스냅샷", "snapshot", "스크립트", "script", "절차")
    )


def _query_has_oidc_auth_config(query: str) -> bool:
    lowered = query.lower()
    return "oidc" in lowered and (
        "authentication.config/cluster" in lowered
        or any(token in query for token in ("인증", "구성", "설정", "절차"))
    )


def _query_has_route_expose_service(query: str) -> bool:
    lowered = query.lower()
    return "route" in lowered and ("service" in lowered or "서비스" in query) and (
        "oc expose" in lowered or "노출" in query or "외부" in query
    )


def _query_has_image_pruning(query: str) -> bool:
    lowered = query.lower()
    has_image_registry = (
        "image" in lowered
        or "registry" in lowered
        or "이미지" in query
        or "레지스트리" in query
    )
    return has_image_registry and (
        "prune" in lowered
        or "pruning" in lowered
        or any(token in query for token in ("오래된", "정리", "가지치기", "태그"))
    )


def _query_has_upgrade_precheck(query: str) -> bool:
    lowered = query.lower()
    return (
        "oc adm upgrade recommend" in lowered
        or "upgrade recommend" in lowered
        or ("업데이트" in query and any(token in query for token in ("사전 점검", "전에", "점검")))
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


def _apply_registry_pvc_config_adjustments(hit: RetrievalHit, *, query: str) -> None:
    if not _query_has_registry_pvc_config(query):
        return
    text = _hit_text(hit)
    has_exact_field = _has_any(
        text,
        (
            "configs.imageregistry/cluster",
            "configs.imageregistry.operator.openshift.io",
            "spec.storage.pvc",
        ),
    )
    if has_exact_field:
        _apply_factor(hit, "v016_registry_pvc_exact_field_boost", 2.35)
    if hit.book_slug in {"registry", "installing_on_any_platform", "images"}:
        _apply_factor(hit, "v016_registry_pvc_book_boost", 1.48)
    if hit.book_slug == "storage" and not _has_any(text, ("registry", "imageregistry", "openshift-image-registry")):
        _apply_factor(hit, "v016_registry_pvc_generic_storage_penalty", 0.34)


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
    if _query_has_etcd_restore_script(query):
        if _has_any(text, ("cluster-restore.sh", "/usr/local/bin/cluster-restore.sh", "이전 클러스터 상태로 복원")):
            _apply_factor(hit, "v016_etcd_restore_script_boost", 2.35)
        if _has_any(text, ("lsblk", "custom /var", "사용자 지정 /var", "worker node")):
            _apply_factor(hit, "v016_etcd_restore_node_partition_penalty", 0.18)
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


def _apply_route_policy_adjustments(hit: RetrievalHit, *, query: str) -> None:
    lowered_query = query.lower()
    if not ("route" in lowered_query and ("허용" in query or "정책" in query or "admission" in lowered_query)):
        return
    text = _hit_text(hit)
    if _has_any(text, ("routeadmission", "namespaceownership", "internamespaceallowed", "ingresscontroller")):
        _apply_factor(hit, "v016_route_admission_policy_boost", 2.0)
    if _has_any(text, ("oc expose", "create route")) and not _has_any(text, ("routeadmission", "namespaceownership")):
        _apply_factor(hit, "v016_route_expose_policy_mismatch_penalty", 0.35)


def _apply_oidc_auth_config_adjustments(hit: RetrievalHit, *, query: str) -> None:
    if not _query_has_oidc_auth_config(query):
        return
    text = _hit_text(hit)
    if hit.book_slug == "authentication_and_authorization":
        _apply_factor(hit, "v016_oidc_auth_book_boost", 1.72)
    if _has_any(text, ("authentication.config/cluster", "oc edit authentication.config/cluster", "keycloak-oidc-ca")):
        _apply_factor(hit, "v016_oidc_auth_config_boost", 2.1)
    if hit.book_slug == "release_notes" or _has_any(text, ("ocpbugs", "known issue", "확인된 문제")):
        _apply_factor(hit, "v016_oidc_auth_release_note_penalty", 0.18)


def _apply_route_expose_service_adjustments(hit: RetrievalHit, *, query: str) -> None:
    if not _query_has_route_expose_service(query):
        return
    text = _hit_text(hit)
    if hit.book_slug in {"ingress_and_load_balancing", "cli_tools"}:
        _apply_factor(hit, "v016_route_expose_book_boost", 1.28)
    if _has_any(text, ("oc expose", "oc expose service")):
        _apply_factor(hit, "v016_route_expose_command_boost", 2.15)
    if _has_any(text, ("http 요청 및 응답 헤더", "request header", "response header", "ingress 오브젝트")):
        _apply_factor(hit, "v016_route_expose_mismatch_penalty", 0.38)


def _apply_image_pruning_adjustments(hit: RetrievalHit, *, query: str) -> None:
    if not _query_has_image_pruning(query):
        return
    text = _hit_text(hit)
    if hit.book_slug in {"images", "registry"}:
        _apply_factor(hit, "v016_image_pruning_book_boost", 1.22)
    if _has_any(text, ("pruning images", "image pruner", "oc adm prune images", "이미지 자동 정리", "이미지 정리")):
        _apply_factor(hit, "v016_image_pruning_exact_boost", 2.5)
    if _has_any(text, ("외부 이미지에 대해 태그 추가", "타사 레지스트리", "허용 목록", "oc tag -d")):
        _apply_factor(hit, "v016_image_pruning_mismatch_penalty", 0.28)


def _apply_upgrade_precheck_adjustments(hit: RetrievalHit, *, query: str) -> None:
    if not _query_has_upgrade_precheck(query):
        return
    text = _hit_text(hit)
    if hit.book_slug in {"updating_clusters", "release_notes", "cli_tools"}:
        _apply_factor(hit, "v016_upgrade_precheck_book_boost", 1.22)
    if _has_any(text, ("oc adm upgrade recommend", "recommend", "precheck", "업데이트 전")):
        _apply_factor(hit, "v016_upgrade_precheck_exact_boost", 1.85)
    if _has_any(text, ("multiarch tuning operator", "다중 아키텍처", "워크로드를 관리")):
        _apply_factor(hit, "v016_upgrade_precheck_multiarch_penalty", 0.28)


def apply_quality_core_adjustments(hit: RetrievalHit, *, signals: ScoreSignals) -> None:
    query = signals.query
    _apply_platform_registry_storage_adjustments(hit, query=query)
    _apply_registry_pvc_config_adjustments(hit, query=query)
    _apply_etcd_adjustments(hit, query=query)
    _apply_insights_adjustments(hit, query=query)
    _apply_build_security_adjustments(hit, query=query)
    _apply_route_policy_adjustments(hit, query=query)
    _apply_oidc_auth_config_adjustments(hit, query=query)
    _apply_route_expose_service_adjustments(hit, query=query)
    _apply_image_pruning_adjustments(hit, query=query)
    _apply_upgrade_precheck_adjustments(hit, query=query)
