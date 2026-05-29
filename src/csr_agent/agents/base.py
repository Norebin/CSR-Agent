"""Agent runtime base classes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from csr_agent.config import PromptingConfig
from csr_agent.exceptions import AgentExecutionError
from csr_agent.llm import LLMClient
from csr_agent.logging import StructuredLogger
from csr_agent.memory import MemoryManager
from csr_agent.models import ToolObservation
from csr_agent.tools import ToolRegistry


@dataclass(slots=True)
class AgentContext:
    tool_registry: ToolRegistry
    memory_manager: MemoryManager
    logger: StructuredLogger
    llm_client: LLMClient | None = None
    prompting: PromptingConfig | None = None
    llm_usage: dict[str, int] = field(
        default_factory=lambda: {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
    )


class AgentRuntime(ABC):
    """Base class for all agents with tool allowlist enforcement."""

    name: str
    allowed_tools: set[str]

    @abstractmethod
    def run(self, inputs: dict[str, Any], context: AgentContext) -> dict[str, Any]:
        """Run the agent and return structured output."""

    def call_tool(
        self,
        context: AgentContext,
        tool_name: str,
        operation: str,
        payload: dict[str, Any] | None = None,
    ) -> ToolObservation:
        if tool_name not in self.allowed_tools:
            raise AgentExecutionError(
                f"{self.name} cannot call forbidden tool: {tool_name}"
            )
        return context.tool_registry.execute(tool_name, operation, payload or {})

    def call_llm_json(
        self,
        context: AgentContext,
        *,
        task_id: str,
        role: str,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if context.llm_client is None:
            return None
        try:
            output, usage = context.llm_client.generate_json(
                role=role,  # type: ignore[arg-type]
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=schema,
            )
            context.llm_usage["prompt_tokens"] += int(usage.prompt_tokens)
            context.llm_usage["completion_tokens"] += int(usage.completion_tokens)
            context.llm_usage["total_tokens"] += int(usage.total_tokens)
            context.logger.emit(
                task_id,
                self.name,
                "LLM response received",
                {
                    "role": role,
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens,
                },
            )
            return output
        except Exception as exc:
            context.logger.emit(
                task_id,
                self.name,
                "LLM call failed, fallback to deterministic logic",
                {"role": role, "error": str(exc)},
            )
            return None

    def apply_prompting_strategy(self, context: AgentContext, core_prompt: str) -> str:
        cfg = context.prompting
        if cfg is None:
            return core_prompt

        directives: list[str] = []
        strategy = cfg.strategy.lower().strip()
        if strategy == "one_shot":
            directives.append("Use one-shot style: produce one direct solution path.")
        else:
            directives.append("Use few-shot style consistent with prior refactoring cases.")

        if cfg.use_cot:
            directives.append("Reason step-by-step internally, but output only final JSON.")
        if cfg.use_react:
            directives.append("Use tool-aware reasoning internally before finalizing output.")
        if cfg.use_tot:
            directives.append("Consider multiple candidate plans internally and choose best.")

        if not directives:
            return core_prompt
        return "\n".join(directives) + "\n\n" + core_prompt
