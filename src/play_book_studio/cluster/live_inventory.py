from __future__ import annotations

from dataclasses import dataclass
import argparse
import hashlib
import json
from pathlib import Path
from typing import Iterable


EXTERNAL_OWNER_NAMESPACES = {
    "openshift-lightspeed",
    "redhat-ods-operator",
    "redhat-ods-applications",
    "openshift-operators",
}

EXTERNAL_OWNER_KINDS = {
    "ClusterServiceVersion",
    "Subscription",
    "InstallPlan",
    "OperatorGroup",
}


@dataclass(frozen=True, order=True)
class ResourceIdentity:
    kind: str
    namespace: str
    name: str

    def stable_key(self) -> str:
        namespace = self.namespace or "_cluster"
        return f"{self.kind}/{namespace}/{self.name}"


@dataclass(frozen=True)
class ResourceRecord:
    identity: ResourceIdentity
    source: str
    digest: str


@dataclass(frozen=True)
class InventoryDecision:
    identity: ResourceIdentity
    decision: str
    reason: str
    live_source: str | None = None
    desired_source: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "key": self.identity.stable_key(),
            "kind": self.identity.kind,
            "namespace": self.identity.namespace,
            "name": self.identity.name,
            "decision": self.decision,
            "reason": self.reason,
            "live_source": self.live_source,
            "desired_source": self.desired_source,
        }


def parse_resource_documents(text: str, source: str) -> list[ResourceRecord]:
    records: list[ResourceRecord] = []
    for document in _split_yaml_documents(text):
        if not document.strip():
            continue
        if _root_value(document, "kind") == "List":
            records.extend(_parse_list_items(document, source))
            continue
        record = _parse_single_resource(document, source)
        if record:
            records.append(record)
    return records


def load_resources_from_paths(paths: Iterable[Path]) -> dict[ResourceIdentity, ResourceRecord]:
    resources: dict[ResourceIdentity, ResourceRecord] = {}
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        for record in parse_resource_documents(path.read_text(encoding="utf-8"), str(path)):
            resources[record.identity] = record
    return resources


def inventory_yaml_paths(inventory_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in inventory_dir.rglob("*.yaml")
        if path.name != "README.md" and "secrets" not in path.name.lower()
    )


def desired_yaml_paths(paths: Iterable[Path]) -> list[Path]:
    expanded: list[Path] = []
    for path in paths:
        if path.is_dir():
            expanded.extend(sorted(path.rglob("*.yaml")))
        elif path.exists():
            expanded.append(path)
    return expanded


def classify_inventory(
    live: dict[ResourceIdentity, ResourceRecord],
    desired: dict[ResourceIdentity, ResourceRecord],
) -> list[InventoryDecision]:
    decisions: list[InventoryDecision] = []
    all_identities = sorted(set(live) | set(desired))
    for identity in all_identities:
        live_record = live.get(identity)
        desired_record = desired.get(identity)
        if _is_external_owner(identity):
            decisions.append(
                InventoryDecision(
                    identity=identity,
                    decision="external-owner",
                    reason="Owned by OpenShift AI, OpenShift Lightspeed, OLM, or platform operator namespace.",
                    live_source=live_record.source if live_record else None,
                    desired_source=desired_record.source if desired_record else None,
                )
            )
            continue

        if live_record and desired_record:
            reason = "Live resource exists in repository desired state."
            if live_record.digest != desired_record.digest:
                reason = "Live resource exists in desired state but content differs; review before adoption."
            decisions.append(
                InventoryDecision(
                    identity=identity,
                    decision="adopt",
                    reason=reason,
                    live_source=live_record.source,
                    desired_source=desired_record.source,
                )
            )
            continue

        if live_record and not desired_record:
            decisions.append(
                InventoryDecision(
                    identity=identity,
                    decision="remove",
                    reason="Live resource is not represented in repository desired state; back up before removal.",
                    live_source=live_record.source,
                )
            )
            continue

        if desired_record and not live_record:
            decisions.append(
                InventoryDecision(
                    identity=identity,
                    decision="replace",
                    reason="Desired resource is absent from live inventory; apply only in an approved mutation window.",
                    desired_source=desired_record.source,
                )
            )

    return decisions


def write_decision_report(decisions: Iterable[InventoryDecision], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "decisions": [decision.as_dict() for decision in sorted(decisions, key=lambda item: item.identity)],
    }
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify Phase 2 live inventory against desired manifests.")
    parser.add_argument("--inventory-dir", required=True, type=Path)
    parser.add_argument("--desired", required=True, nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    live = load_resources_from_paths(inventory_yaml_paths(args.inventory_dir))
    desired = load_resources_from_paths(desired_yaml_paths(args.desired))
    write_decision_report(classify_inventory(live, desired), args.output)
    return 0


def _is_external_owner(identity: ResourceIdentity) -> bool:
    return identity.namespace in EXTERNAL_OWNER_NAMESPACES or identity.kind in EXTERNAL_OWNER_KINDS


def _split_yaml_documents(text: str) -> list[str]:
    docs: list[list[str]] = [[]]
    for line in text.splitlines():
        if line.strip() == "---":
            docs.append([])
        else:
            docs[-1].append(line)
    return ["\n".join(doc) for doc in docs]


def _parse_list_items(document: str, source: str) -> list[ResourceRecord]:
    records: list[ResourceRecord] = []
    current: list[str] = []
    in_items = False
    for line in document.splitlines():
        stripped = line.strip()
        if stripped == "items:":
            in_items = True
            continue
        if not in_items:
            continue
        if line.startswith("- ") and current:
            record = _parse_single_resource("\n".join(_dedent_list_item(current)), source)
            if record:
                records.append(record)
            current = [line]
        elif line.startswith("- ") or current:
            current.append(line)
    if current:
        record = _parse_single_resource("\n".join(_dedent_list_item(current)), source)
        if record:
            records.append(record)
    return records


def _dedent_list_item(lines: list[str]) -> list[str]:
    result: list[str] = []
    for index, line in enumerate(lines):
        if index == 0 and line.startswith("- "):
            result.append(line[2:])
        elif line.startswith("  "):
            result.append(line[2:])
        else:
            result.append(line)
    return result


def _parse_single_resource(document: str, source: str) -> ResourceRecord | None:
    kind = _root_value(document, "kind")
    if not kind:
        return None
    name = _metadata_value(document, "name")
    if not name:
        return None
    namespace = _metadata_value(document, "namespace") or ""
    digest = hashlib.sha256(_normalized_resource_text(document).encode("utf-8")).hexdigest()
    return ResourceRecord(ResourceIdentity(kind=kind, namespace=namespace, name=name), source, digest)


def _root_value(document: str, key: str) -> str:
    prefix = f"{key}:"
    for line in document.splitlines():
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip().strip('"')
    return ""


def _metadata_value(document: str, key: str) -> str:
    in_metadata = False
    prefix = f"  {key}:"
    for line in document.splitlines():
        if line == "metadata:":
            in_metadata = True
            continue
        if in_metadata and line and not line.startswith(" "):
            return ""
        if in_metadata and line.startswith(prefix):
            return line.split(":", 1)[1].strip().strip('"')
    return ""


def _normalized_resource_text(document: str) -> str:
    ignored_roots = ("status:",)
    ignored_metadata = (
        "  creationTimestamp:",
        "  resourceVersion:",
        "  uid:",
        "  generation:",
    )
    lines = []
    skip_status = False
    for line in document.splitlines():
        if line in ignored_roots:
            skip_status = True
            continue
        if skip_status:
            if line and not line.startswith(" "):
                skip_status = False
            else:
                continue
        if line.startswith(ignored_metadata):
            continue
        lines.append(line.rstrip())
    return "\n".join(lines).strip()


if __name__ == "__main__":
    raise SystemExit(main())
