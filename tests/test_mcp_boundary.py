from pathlib import Path

import pytest

from play_book_studio.aiops.event_timeline import append_timeline_event
from play_book_studio.mcp.boundary import PBS_MCP_TOOL_NAMES, execute_read_only_tool, list_pbs_mcp_tools


def test_pbs_mcp_tool_catalog_is_read_only_and_complete() -> None:
    tools = list_pbs_mcp_tools()

    assert [tool.name for tool in tools] == list(PBS_MCP_TOOL_NAMES)
    assert all(tool.read_only for tool in tools)
    assert "search_pbs_library" in {tool.name for tool in tools}
    assert "generate_remediation_plan" in {tool.name for tool in tools}


def test_search_and_read_generated_private_markdown(tmp_path: Path) -> None:
    document_path = tmp_path / "storage" / "private-rag" / "generated" / "koscom" / "storage" / "pvc.md"
    document_path.parent.mkdir(parents=True)
    document_path.write_text(
        "# KOSCOM PVC Pending Troubleshooting\n\nUse `oc describe pvc` for pending PVC checks.\n",
        encoding="utf-8",
    )

    search_result = execute_read_only_tool("search_pbs_library", {"query": "PVC Pending"}, root_dir=tmp_path)
    assert search_result["items"][0]["title"] == "KOSCOM PVC Pending Troubleshooting"

    document_result = execute_read_only_tool(
        "get_pbs_document",
        {"path": "storage/private-rag/generated/koscom/storage/pvc.md"},
        root_dir=tmp_path,
    )
    assert "oc describe pvc" in document_result["content"]


def test_get_pbs_document_rejects_paths_outside_generated_private_docs(tmp_path: Path) -> None:
    outside = tmp_path / "notes.md"
    outside.write_text("# private\n", encoding="utf-8")

    with pytest.raises(ValueError):
        execute_read_only_tool("get_pbs_document", {"path": "notes.md"}, root_dir=tmp_path)


def test_timeline_tools(tmp_path: Path) -> None:
    append_timeline_event(
        tmp_path,
        event_type="yaml_apply",
        source="ops_console",
        summary="Applied Deployment/api",
        namespace="demo",
        resource_type="deployments",
        resource_name="api",
        yaml_diff="- replicas: 1\n+ replicas: 3",
        apply_result={"status": "simulated"},
        resource_snapshot={"kind": "Deployment", "metadata": {"name": "api"}},
    )
    append_timeline_event(
        tmp_path,
        event_type="cli_output",
        source="terminal",
        summary="Captured terminal output",
        session_id="session-1",
        stdout="pod/api running",
    )

    events = execute_read_only_tool("list_recent_pbs_events", {"limit": 5}, root_dir=tmp_path)
    assert len(events["items"]) == 2

    yaml_history = execute_read_only_tool(
        "get_yaml_apply_history",
        {"resource_name": "api", "namespace": "demo"},
        root_dir=tmp_path,
    )
    assert yaml_history["items"][0]["yaml_diff"].startswith("- replicas")

    cli_output = execute_read_only_tool("get_cli_session_output", {"session_id": "session-1"}, root_dir=tmp_path)
    assert cli_output["items"][0]["stdout"] == "pod/api running"

    snapshot = execute_read_only_tool("get_cluster_snapshot", {"resource_name": "api"}, root_dir=tmp_path)
    assert snapshot["resource_snapshot"]["kind"] == "Deployment"

    plan = execute_read_only_tool("generate_remediation_plan", {"problem": "deployment not ready"}, root_dir=tmp_path)
    assert "Mutation Boundary" in plan["plan_markdown"]
