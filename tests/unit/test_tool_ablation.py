from __future__ import annotations

from csr_agent.tools import build_default_tool_registry


def test_disabled_tool_returns_structured_observation():
    registry = build_default_tool_registry(tool_enabled={"git_tool": False})
    obs = registry.execute("git_tool", "list_tags", {"repo_path": "D:/not_exists"})
    assert obs.status == "degraded"
    assert obs.error_code == "TOOL_DISABLED"
