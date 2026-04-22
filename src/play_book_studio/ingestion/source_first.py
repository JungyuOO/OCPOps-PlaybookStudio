from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess


SOURCE_REPO_URL = "https://github.com/openshift/openshift-docs"
SOURCE_BRANCH = "enterprise-4.20"
SOURCE_MIRROR_DIRNAME = "openshift-docs-enterprise-4.20"
OFFICIAL_OCP_DOCS_LICENSE = "OpenShift documentation is licensed under the Apache License 2.0."

DOCS_SOURCE_URL_RE = re.compile(
    r"^https://docs\.redhat\.com/"
    r"(?P<lang>ko|en)/documentation/"
    r"(?P<product>[^/]+)/(?P<version>\d+\.\d+)/"
    r"html(?:-single)?/(?P<slug>[^/]+)/index$"
)

MANUAL_PATH_ALIASES: dict[str, str] = {
    "architecture": "architecture/index.adoc",
    "authentication_and_authorization": "authentication/index.adoc",
    "backup_and_restore": "backup_and_restore/index.adoc",
    "cli_tools": "cli_reference/index.adoc",
    "disconnected_environments": "disconnected/index.adoc",
    "etcd": "etcd/etcd-overview.adoc",
    "images": "openshift_images/index.adoc",
    "installing_on_any_platform": "installing/overview/index.adoc",
    "installation_overview": "installing/overview/index.adoc",
    "logging": "observability/logging/about-logging.adoc",
    "machine_configuration": "machine_configuration/index.adoc",
    "machine_management": "machine_management/index.adoc",
    "monitoring": "observability/monitoring/about-ocp-monitoring.adoc",
    "nodes": "nodes/index.adoc",
    "observability_overview": "observability/overview/index.adoc",
    "operators": "operators/index.adoc",
    "postinstallation_configuration": "post_installation_configuration/index.adoc",
    "registry": "registry/index.adoc",
    "release_notes": "release_notes/ocp-4-20-release-notes.adoc",
    "security_and_compliance": "security/index.adoc",
    "storage": "storage/index.adoc",
    "support": "support/index.adoc",
    "updating_clusters": "updating/index.adoc",
}

MANUAL_COLLECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "advanced_networking": (
        "networking/advanced_networking/verifying-connectivity-endpoint.adoc",
        "networking/advanced_networking/changing-cluster-network-mtu.adoc",
        "networking/advanced_networking/network-bonding-considerations.adoc",
        "networking/advanced_networking/using-sctp.adoc",
        "networking/advanced_networking/associating-secondary-interfaces-metrics-to-network-attachments.adoc",
        "networking/advanced_networking/bgp_routing/about-bgp-routing.adoc",
        "networking/advanced_networking/bgp_routing/enabling-bgp-routing.adoc",
        "networking/advanced_networking/bgp_routing/disabling-bgp-routing.adoc",
        "networking/advanced_networking/bgp_routing/migrating-frr-k8s-resources.adoc",
        "networking/advanced_networking/route_advertisements/about-route-advertisements.adoc",
        "networking/advanced_networking/route_advertisements/enabling-route-advertisements.adoc",
        "networking/advanced_networking/route_advertisements/disabling-route-advertisements.adoc",
        "networking/advanced_networking/route_advertisements/example-route-advertisement-setup.adoc",
        "networking/advanced_networking/ptp/about-ptp.adoc",
        "networking/advanced_networking/ptp/configuring-ptp.adoc",
        "networking/advanced_networking/ptp/ptp-cloud-events-consumer-dev-reference-v2.adoc",
        "networking/advanced_networking/ptp/ptp-events-rest-api-reference-v2.adoc",
    ),
    "ingress_and_load_balancing": (
        "networking/ingress_load_balancing/routes/creating-basic-routes.adoc",
        "networking/ingress_load_balancing/routes/securing-routes.adoc",
        "networking/ingress_load_balancing/routes/nw-configuring-routes.adoc",
        "networking/ingress_load_balancing/routes/creating-advanced-routes.adoc",
        "networking/ingress_load_balancing/configuring_ingress_cluster_traffic/overview-traffic.adoc",
        "networking/ingress_load_balancing/configuring_ingress_cluster_traffic/configuring-externalip.adoc",
        "networking/ingress_load_balancing/configuring_ingress_cluster_traffic/configuring-ingress-cluster-traffic-ingress-controller.adoc",
        "networking/ingress_load_balancing/configuring_ingress_cluster_traffic/nw-configuring-ingress-controller-endpoint-publishing-strategy.adoc",
        "networking/ingress_load_balancing/configuring_ingress_cluster_traffic/configuring-ingress-cluster-traffic-load-balancer.adoc",
        "networking/ingress_load_balancing/configuring_ingress_cluster_traffic/configuring-ingress-cluster-traffic-aws.adoc",
        "networking/ingress_load_balancing/configuring_ingress_cluster_traffic/configuring-ingress-cluster-traffic-service-external-ip.adoc",
        "networking/ingress_load_balancing/configuring_ingress_cluster_traffic/configuring-ingress-cluster-traffic-nodeport.adoc",
        "networking/ingress_load_balancing/configuring_ingress_cluster_traffic/configuring-ingress-cluster-traffic-load-balancer-allowed-source-ranges.adoc",
        "networking/ingress_load_balancing/configuring_ingress_cluster_traffic/configuring-ingress-cluster-patch-fields.adoc",
        "networking/ingress_load_balancing/configuring_ingress_cluster_traffic/ingress-controller-dnsmgt.adoc",
        "networking/ingress_load_balancing/configuring_ingress_cluster_traffic/ingress-gateway-api.adoc",
        "networking/ingress_load_balancing/load-balancing-openstack.adoc",
        "networking/ingress_load_balancing/metallb/metallb-configure-address-pools.adoc",
        "networking/ingress_load_balancing/metallb/about-advertising-ipaddresspool.adoc",
        "networking/ingress_load_balancing/metallb/metallb-configure-bgp-peers.adoc",
        "networking/ingress_load_balancing/metallb/metallb-configure-community-alias.adoc",
        "networking/ingress_load_balancing/metallb/metallb-configure-bfd-profiles.adoc",
        "networking/ingress_load_balancing/metallb/metallb-configure-services.adoc",
        "networking/ingress_load_balancing/metallb/metallb-configure-return-traffic.adoc",
        "networking/ingress_load_balancing/metallb/metallb-frr-k8s.adoc",
        "networking/ingress_load_balancing/metallb/metallb-troubleshoot-support.adoc",
    ),
    "networking_overview": (
        "networking/networking_overview/understanding-networking.adoc",
        "networking/networking_overview/accessing-hosts.adoc",
        "networking/networking_overview/networking-dashboards.adoc",
        "networking/networking_overview/cidr-range-definitions.adoc",
    ),
    "overview": (
        "welcome/index.adoc",
        "welcome/ocp-overview.adoc",
        "welcome/learn_more_about_openshift.adoc",
        "welcome/kubernetes-overview.adoc",
        "welcome/openshift-editions.adoc",
        "welcome/glossary.adoc",
        "welcome/oke_about.adoc",
        "welcome/providing-feedback-on-red-hat-documentation.adoc",
    ),
    "validation_and_troubleshooting": (
        "installing/validation_and_troubleshooting/validating-an-installation.adoc",
        "installing/validation_and_troubleshooting/installing-troubleshooting.adoc",
    ),
    "web_console": (
        "web_console/web-console-overview.adoc",
        "web_console/web-console.adoc",
        "web_console/using-dashboard-to-get-cluster-information.adoc",
        "web_console/adding-user-preferences.adoc",
        "web_console/configuring-web-console.adoc",
        "web_console/customizing-the-web-console.adoc",
        "web_console/dynamic-plugin/overview-dynamic-plugin.adoc",
        "web_console/dynamic-plugin/dynamic-plugins-get-started.adoc",
        "web_console/dynamic-plugin/deploy-plugin-cluster.adoc",
        "web_console/dynamic-plugin/content-security-policy.adoc",
        "web_console/dynamic-plugin/dynamic-plugin-example.adoc",
        "web_console/dynamic-plugin/dynamic-plugins-reference.adoc",
        "web_console/web_terminal/installing-web-terminal.adoc",
        "web_console/web_terminal/configuring-web-terminal.adoc",
        "web_console/web_terminal/odc-using-web-terminal.adoc",
        "web_console/web_terminal/troubleshooting-web-terminal.adoc",
        "web_console/web_terminal/uninstalling-web-terminal.adoc",
        "web_console/disabling-web-console.adoc",
        "web_console/creating-quick-start-tutorials.adoc",
        "web_console/capabilities_products-web-console.adoc",
    ),
}


@dataclass(frozen=True, slots=True)
class SourceBinding:
    slug: str
    binding_kind: str
    root_relative_path: str
    source_relative_paths: tuple[str, ...]


def source_mirror_root(root_dir: Path) -> Path:
    return root_dir / "tmp_source" / SOURCE_MIRROR_DIRNAME


def _binding_root(source_relative_paths: tuple[str, ...]) -> str:
    if len(source_relative_paths) == 1:
        return source_relative_paths[0]
    common_prefix = Path(source_relative_paths[0]).parts[:-1]
    for path in source_relative_paths[1:]:
        current_parts = Path(path).parts[:-1]
        size = min(len(common_prefix), len(current_parts))
        index = 0
        while index < size and common_prefix[index] == current_parts[index]:
            index += 1
        common_prefix = common_prefix[:index]
    return str(Path(*common_prefix)).replace("\\", "/") if common_prefix else ""


def _binding_exists(root_dir: Path, binding: SourceBinding) -> bool:
    mirror_root = source_mirror_root(root_dir)
    return all((mirror_root / relative_path).exists() and (mirror_root / relative_path).is_file() for relative_path in binding.source_relative_paths)


def _manual_binding(slug: str) -> SourceBinding | None:
    collection_paths = MANUAL_COLLECTION_ALIASES.get(slug)
    if collection_paths:
        return SourceBinding(
            slug=slug,
            binding_kind="collection",
            root_relative_path=_binding_root(collection_paths),
            source_relative_paths=collection_paths,
        )
    file_path = MANUAL_PATH_ALIASES.get(slug)
    if file_path:
        return SourceBinding(
            slug=slug,
            binding_kind="file",
            root_relative_path=file_path,
            source_relative_paths=(file_path,),
        )
    return None


def _fallback_file_candidates(slug: str) -> tuple[str, ...]:
    return (
        f"{slug}/index.adoc",
        f"{slug.replace('_', '-')}/index.adoc",
    )


def repo_binding_candidates(root_dir: Path, slug: str) -> list[SourceBinding]:
    candidates: list[SourceBinding] = []
    manual = _manual_binding(slug)
    if manual is not None:
        candidates.append(manual)
    for relative_path in _fallback_file_candidates(slug):
        binding = SourceBinding(
            slug=slug,
            binding_kind="file",
            root_relative_path=relative_path,
            source_relative_paths=(relative_path,),
        )
        if binding not in candidates:
            candidates.append(binding)
    return [binding for binding in candidates if _binding_exists(root_dir, binding)]


def resolve_repo_binding(root_dir: Path, slug: str) -> SourceBinding | None:
    candidates = repo_binding_candidates(root_dir, slug)
    return candidates[0] if candidates else None


def repo_path_candidates(root_dir: Path, slug: str) -> list[Path]:
    binding = resolve_repo_binding(root_dir, slug)
    if binding is None:
        return []
    mirror_root = source_mirror_root(root_dir)
    return [(mirror_root / relative_path).resolve() for relative_path in binding.source_relative_paths]


def resolve_repo_path(root_dir: Path, slug: str) -> Path | None:
    candidates = repo_path_candidates(root_dir, slug)
    return candidates[0] if candidates else None


def resolve_repo_relative_path(root_dir: Path, slug: str) -> str:
    binding = resolve_repo_binding(root_dir, slug)
    return binding.root_relative_path if binding is not None else ""


def resolve_repo_relative_paths(root_dir: Path, slug: str) -> list[str]:
    binding = resolve_repo_binding(root_dir, slug)
    return list(binding.source_relative_paths) if binding is not None else []


def derive_official_docs_legal_notice_url(entry) -> str:
    explicit = str(getattr(entry, "legal_notice_url", "") or "").strip()
    if explicit:
        return explicit
    candidates = (
        str(getattr(entry, "resolved_source_url", "") or "").strip(),
        str(getattr(entry, "source_url", "") or "").strip(),
        str(getattr(entry, "translation_source_url", "") or "").strip(),
    )
    for candidate in candidates:
        match = DOCS_SOURCE_URL_RE.match(candidate)
        if match is None:
            continue
        return (
            "https://docs.redhat.com/"
            f"{match.group('lang')}/documentation/{match.group('product')}/{match.group('version')}/"
            "html/legal_notice/index"
        )
    return ""


def derive_official_docs_license_or_terms(entry, *, legal_notice_url: str) -> str:
    explicit = str(getattr(entry, "license_or_terms", "") or "").strip()
    if explicit:
        return explicit
    candidates = (
        str(getattr(entry, "resolved_source_url", "") or "").strip(),
        str(getattr(entry, "source_url", "") or "").strip(),
        str(getattr(entry, "translation_source_url", "") or "").strip(),
        str(legal_notice_url or "").strip(),
    )
    if any(
        "docs.redhat.com" in candidate and "openshift_container_platform" in candidate
        for candidate in candidates
        if candidate
    ):
        return OFFICIAL_OCP_DOCS_LICENSE
    return ""


def derive_source_repo_updated_at(
    root_dir: Path,
    *,
    source_relative_paths: tuple[str, ...] | list[str],
    mirror_root: Path | None = None,
) -> str:
    relative_paths = tuple(str(path).strip() for path in source_relative_paths if str(path).strip())
    if not relative_paths:
        return ""
    repo_root = Path(mirror_root or source_mirror_root(root_dir))
    timestamps: list[str] = []
    for relative_path in relative_paths:
        try:
            result = subprocess.run(
                ["git", "-C", str(repo_root), "log", "-1", "--format=%cI", "--", relative_path],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            result = None
        if result is not None:
            stamp = str(result.stdout or "").strip()
            if stamp:
                timestamps.append(stamp)
                continue
        file_path = (repo_root / relative_path).resolve()
        if file_path.exists():
            timestamps.append(
                datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
            )
    return max(timestamps) if timestamps else ""
