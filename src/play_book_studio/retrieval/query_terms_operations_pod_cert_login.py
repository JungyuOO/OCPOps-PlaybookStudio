from __future__ import annotations

from .intents import (
    CRASH_LOOP_RE,
    OC_LOGIN_RE,
    POD_LIFECYCLE_RE,
    has_certificate_monitor_intent,
)


def append_operation_pod_cert_login_terms(normalized: str, terms: list[str]) -> None:
    if CRASH_LOOP_RE.search(normalized):
        terms.extend(
            [
                "CrashLoopBackOff",
                "pod",
                "container",
                "restart",
                "back-off",
                "restartCount",
                "OOMKilled",
                "ImagePullBackOff",
                "ErrImagePull",
                "Back-off restarting failed container",
                "livenessProbe",
                "readinessProbe",
                "events",
                "describe",
                "oc",
                "logs",
                "troubleshooting",
                "pod issues",
                "error states",
                "application diagnostics",
                "애플리케이션 오류",
            ]
        )
    if POD_LIFECYCLE_RE.search(normalized):
        terms.extend(
            [
                "pod",
                "lifecycle",
                "phase",
                "status",
                "Pending",
                "Running",
                "Succeeded",
                "Failed",
                "Unknown",
                "개념",
                "overview",
                "definition",
                "glossary",
                "용어집",
                "pod phase",
                "pod status",
            ]
        )
    if OC_LOGIN_RE.search(normalized):
        terms.extend(["oc", "login", "token", "--token", "--server", "cli"])
    if has_certificate_monitor_intent(normalized):
        terms.extend(
            [
                "monitor-certificates",
                "oc",
                "adm",
                "ocp-certificates",
                "certificate",
                "expiry",
            ]
        )
