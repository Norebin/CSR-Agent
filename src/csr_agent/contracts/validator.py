"""Contract validation utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from csr_agent.config import PipelineConfig
from csr_agent.exceptions import ContractValidationError
from csr_agent.models import ReviewFeedback


def load_agent_contracts(path: Path | str) -> dict[str, Any]:
    path_obj = Path(path)
    if not path_obj.exists():
        raise ContractValidationError(f"Contract file not found: {path_obj}")
    with path_obj.open("r", encoding="utf-8") as fh:
        contracts = yaml.safe_load(fh)
    if not isinstance(contracts, dict):
        raise ContractValidationError("Agent contract root must be a mapping")
    return contracts


def validate_json_schemas(schema_paths: list[Path | str]) -> None:
    for schema_path in schema_paths:
        path_obj = Path(schema_path)
        if not path_obj.exists():
            raise ContractValidationError(f"Schema not found: {path_obj}")
        with path_obj.open("r", encoding="utf-8") as fh:
            schema = json.load(fh)
        try:
            jsonschema.Draft202012Validator.check_schema(schema)
        except jsonschema.SchemaError as exc:  # pragma: no cover - library handles text
            raise ContractValidationError(f"Invalid schema: {path_obj}") from exc


def validate_runtime_contracts(
    config: PipelineConfig,
    contracts: dict[str, Any],
    available_agents: set[str],
    available_tools: set[str],
) -> None:
    errors: list[str] = []
    contract_agents = set((contracts.get("agents") or {}).keys())
    contract_tools = set((contracts.get("tools") or {}).keys())
    state_machine = contracts.get("state_machine") or []

    for agent_name, enabled in config.agents.model_dump().items():
        if enabled and agent_name not in contract_agents:
            errors.append(f"Enabled agent missing in contract: {agent_name}")
        if enabled and agent_name not in available_agents:
            errors.append(f"Enabled agent not registered: {agent_name}")

    for tool_name, enabled in config.tools.model_dump().items():
        if enabled and tool_name not in contract_tools:
            errors.append(f"Enabled tool missing in contract: {tool_name}")
        if enabled and tool_name not in available_tools:
            errors.append(f"Enabled tool not registered: {tool_name}")

    if not state_machine:
        errors.append("Contract state_machine is empty")

    required_feedback_fields = (
        ((contracts.get("review_loop") or {}).get("required_feedback_fields")) or []
    )
    model_fields = set(ReviewFeedback.model_fields.keys())
    for field_name in required_feedback_fields:
        if field_name not in model_fields:
            errors.append(f"Required feedback field missing in model: {field_name}")

    if errors:
        raise ContractValidationError("; ".join(errors))
