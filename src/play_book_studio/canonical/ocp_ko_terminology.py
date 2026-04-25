"""Preferred OCP Korean terminology for official-source translation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OcpKoTerminologyEntry:
    source: str
    preferred_ko: str
    notes: str = ""


OCP_KO_TERMINOLOGY = (
    OcpKoTerminologyEntry(
        source="OpenShift Container Platform",
        preferred_ko="OpenShift Container Platform",
        notes="Keep product name in English.",
    ),
    OcpKoTerminologyEntry(
        source="Red Hat OpenShift",
        preferred_ko="Red Hat OpenShift",
        notes="Keep product name in English.",
    ),
    OcpKoTerminologyEntry(
        source="OpenShift",
        preferred_ko="OpenShift",
        notes="Keep product name in English inside official book text.",
    ),
    OcpKoTerminologyEntry(
        source="Kubernetes",
        preferred_ko="쿠버네티스(Kubernetes)",
    ),
    OcpKoTerminologyEntry(
        source="BuildConfig",
        preferred_ko="BuildConfig",
        notes="Do not translate resource kind.",
    ),
    OcpKoTerminologyEntry(
        source="BuildConfigs",
        preferred_ko="BuildConfigs",
        notes="Do not translate resource kind.",
    ),
    OcpKoTerminologyEntry(
        source="Pipeline build strategy",
        preferred_ko="파이프라인 빌드 전략",
    ),
    OcpKoTerminologyEntry(
        source="pipeline build strategy",
        preferred_ko="파이프라인 빌드 전략",
    ),
    OcpKoTerminologyEntry(
        source="pipelines",
        preferred_ko="파이프라인",
    ),
    OcpKoTerminologyEntry(
        source="pipeline",
        preferred_ko="파이프라인",
    ),
    OcpKoTerminologyEntry(
        source="Operator",
        preferred_ko="Operator",
        notes="Do not translate product/resource role name.",
    ),
    OcpKoTerminologyEntry(
        source="Operators",
        preferred_ko="Operators",
        notes="Do not translate product/resource role name.",
    ),
    OcpKoTerminologyEntry(
        source="Cluster Observability Operator",
        preferred_ko="클러스터 관측성 Operator",
    ),
    OcpKoTerminologyEntry(
        source="Networking Operator",
        preferred_ko="네트워킹 Operator",
    ),
    OcpKoTerminologyEntry(
        source="Migration Toolkit for Containers",
        preferred_ko="컨테이너용 Migration Toolkit",
    ),
    OcpKoTerminologyEntry(
        source="Service Mesh",
        preferred_ko="서비스 메시",
    ),
    OcpKoTerminologyEntry(
        source="Virtualization",
        preferred_ko="가상화",
    ),
    OcpKoTerminologyEntry(
        source="Machine configuration",
        preferred_ko="머신 구성",
    ),
    OcpKoTerminologyEntry(
        source="custom resource",
        preferred_ko="사용자 정의 리소스",
    ),
    OcpKoTerminologyEntry(
        source="custom resources",
        preferred_ko="사용자 정의 리소스",
    ),
    OcpKoTerminologyEntry(
        source="namespace",
        preferred_ko="네임스페이스(namespace)",
    ),
    OcpKoTerminologyEntry(
        source="namespaces",
        preferred_ko="네임스페이스(namespace)",
    ),
    OcpKoTerminologyEntry(
        source="cluster",
        preferred_ko="클러스터",
    ),
    OcpKoTerminologyEntry(
        source="clusters",
        preferred_ko="클러스터",
    ),
    OcpKoTerminologyEntry(
        source="node",
        preferred_ko="노드",
    ),
    OcpKoTerminologyEntry(
        source="nodes",
        preferred_ko="노드",
    ),
    OcpKoTerminologyEntry(
        source="bare metal",
        preferred_ko="베어 메탈",
    ),
    OcpKoTerminologyEntry(
        source="registry",
        preferred_ko="레지스트리",
    ),
    OcpKoTerminologyEntry(
        source="image registry",
        preferred_ko="이미지 레지스트리",
    ),
    OcpKoTerminologyEntry(
        source="route",
        preferred_ko="Route",
        notes="Keep OpenShift resource kind in English.",
    ),
    OcpKoTerminologyEntry(
        source="routes",
        preferred_ko="Routes",
        notes="Keep OpenShift resource kind in English.",
    ),
    OcpKoTerminologyEntry(
        source="Ingress",
        preferred_ko="Ingress",
        notes="Keep Kubernetes resource kind in English.",
    ),
    OcpKoTerminologyEntry(
        source="IngressController",
        preferred_ko="IngressController",
        notes="Do not translate resource kind.",
    ),
    OcpKoTerminologyEntry(
        source="Hosted control planes overview",
        preferred_ko="호스팅된 컨트롤 플레인 개요",
    ),
    OcpKoTerminologyEntry(
        source="Hosted control planes",
        preferred_ko="호스팅된 컨트롤 플레인",
    ),
    OcpKoTerminologyEntry(
        source="hosted control planes",
        preferred_ko="호스팅된 컨트롤 플레인",
    ),
    OcpKoTerminologyEntry(
        source="hosted control plane",
        preferred_ko="호스팅된 컨트롤 플레인",
    ),
    OcpKoTerminologyEntry(
        source="control planes",
        preferred_ko="컨트롤 플레인",
    ),
    OcpKoTerminologyEntry(
        source="control plane",
        preferred_ko="컨트롤 플레인",
    ),
    OcpKoTerminologyEntry(
        source="hosted cluster",
        preferred_ko="호스팅된 클러스터",
    ),
    OcpKoTerminologyEntry(
        source="management cluster",
        preferred_ko="관리 클러스터",
    ),
    OcpKoTerminologyEntry(
        source="HyperShift",
        preferred_ko="HyperShift",
        notes="Do not translate product name.",
    ),
    OcpKoTerminologyEntry(
        source="NodePool",
        preferred_ko="NodePool",
        notes="Do not translate resource name.",
    ),
    OcpKoTerminologyEntry(
        source="NodePools",
        preferred_ko="NodePools",
        notes="Do not translate resource name.",
    ),
)


OCP_KO_NORMALIZATION_RULES = (
    ("лимите", "한도"),
    ("лим이트", "한도"),
    ("арте팩트", "아티팩트"),
    ("артефакt", "아티팩트"),
    ("다м프", "덤프"),
    ("다мп", "덤프"),
    ("오фф셋", "오프셋"),
    ("внести", "적용"),
    ("문서ацию", "문서"),
    ("гаранти", "보장"),
    ("поздний", "최신"),
    ("исходящий", "아웃바운드"),
    ("임пор터", "임포터"),
    ("서ти피케이트", "인증서"),
    ("Red Hat OpenShift Documentation Team Legal Notice Abstract", "Red Hat OpenShift 문서 팀 법적 고지 및 개요"),
    ("Builds for OpenShift Container Platform", "OpenShift Container Platform 빌드"),
    ("Legal Notice", "법적 고지"),
    ("Important", "중요"),
    ("Tip", "팁"),
    ("오픈시프트 컨테이너 플랫폼", "OpenShift Container Platform"),
    ("오픈시프트 컨테이너 플랫폼(OpenShift Container Platform)", "OpenShift Container Platform"),
    ("OpenShift 컨테이너 플랫폼", "OpenShift Container Platform"),
    ("쿠버네티스(Kubernetes)(Kubernetes)", "쿠버네티스(Kubernetes)"),
    ("쿠버네티스 Kubernetes", "쿠버네티스(Kubernetes)"),
    ("파이프라인 빌드 전략", "파이프라인 빌드 전략"),
    ("호스팅 제어 평면 개요", "호스팅된 컨트롤 플레인 개요"),
    ("호스트된 제어 평면 개요", "호스팅된 컨트롤 플레인 개요"),
    ("호스팅 제어 평면", "호스팅된 컨트롤 플레인"),
    ("호스트된 제어 평면", "호스팅된 컨트롤 플레인"),
    ("제어 평면", "컨트롤 플레인"),
    ("Cluster Observability Operator", "클러스터 관측성 Operator"),
    ("Networking Operator", "네트워킹 Operator"),
    ("Migration Toolkit for Containers", "컨테이너용 Migration Toolkit"),
    ("Service Mesh", "서비스 메시"),
    ("Virtualization", "가상화"),
    ("Machine configuration", "머신 구성"),
)


def ocp_ko_terminology_prompt() -> str:
    lines = [
        "Use the following preferred OpenShift Korean terminology exactly when applicable.",
        "Do not invent alternate Korean paraphrases for these terms.",
    ]
    for entry in OCP_KO_TERMINOLOGY:
        line = f"- {entry.source} -> {entry.preferred_ko}"
        if entry.notes:
            line = f"{line} ({entry.notes})"
        lines.append(line)
    return "\n".join(lines)


def normalize_ocp_ko_terminology(text: str) -> str:
    normalized = text or ""
    for before, after in OCP_KO_NORMALIZATION_RULES:
        normalized = normalized.replace(before, after)
    return normalized
