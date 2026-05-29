"""Tool adapter protocol and base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from csr_agent.models import ToolObservation


class ToolAdapter(ABC):
    """Unified interface for all tool adapters."""

    name: str
    operations: set[str]

    @abstractmethod
    def execute(self, operation: str, payload: dict[str, Any]) -> ToolObservation:
        """Execute operation with structured payload."""
