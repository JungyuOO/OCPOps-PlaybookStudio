from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class WorkspaceHandle:
    namespace: str
    pod_name: str = ""
    service_account_name: str = "learner"
    pvc_name: str = "home-learner"
    deployment_name: str = "sandbox"
    ready: bool = False
    created: bool = False
    hibernated: bool = False
    manifests: tuple[dict[str, Any], ...] = field(default_factory=tuple)
