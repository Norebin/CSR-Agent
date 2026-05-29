"""Tool registry and dispatch."""

from __future__ import annotations

from typing import Any

from csr_agent.exceptions import ToolExecutionError
from csr_agent.models import ToolObservation

from .protocol import ToolAdapter


class ToolRegistry:
    """Registry for tool adapters with operation dispatch."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolAdapter] = {}

    def register(self, adapter: ToolAdapter) -> None:
        self._tools[adapter.name] = adapter

    def names(self) -> set[str]:
        return set(self._tools.keys())

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def execute(
        self,
        tool_name: str,
        operation: str,
        payload: dict[str, Any] | None = None,
    ) -> ToolObservation:
        if tool_name not in self._tools:
            raise ToolExecutionError(f"Tool not found: {tool_name}")
        return self._tools[tool_name].execute(operation, payload or {})
