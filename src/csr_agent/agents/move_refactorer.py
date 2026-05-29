"""Feature Envy move refactoring agent."""

from __future__ import annotations

import json
from typing import Any

from csr_agent.models import PatchProposal, RefactoringTask

from .base import AgentContext, AgentRuntime


class MoveRefactorerAgent(AgentRuntime):
    name = "move_refactorer"
    allowed_tools = {
        "repo_browser_tool",
        "ast_tool",
        "entity_tracker_tool",
        "patch_tool",
    }

    def run(self, inputs: dict[str, Any], context: AgentContext) -> dict[str, Any]:
        task: RefactoringTask = inputs["task"]
        fallback = self._fallback_proposal(task)

        llm_output = self.call_llm_json(
            context,
            task_id=task.task_id,
            role="executor",
            system_prompt=(
                "You are a Java Feature Envy refactoring expert. "
                "Return only one PatchProposal JSON object."
            ),
            user_prompt=self._build_prompt(task, context),
            schema=PatchProposal.model_json_schema(),
        )
        if llm_output is not None:
            try:
                llm_output["agent_name"] = self.name
                proposal = PatchProposal.model_validate(llm_output)
                return proposal.to_json_dict()
            except Exception as exc:
                context.logger.emit(
                    task.task_id,
                    self.name,
                    "Invalid move_refactorer LLM output, fallback to deterministic patch",
                    {"error": str(exc)},
                )
        return fallback.to_json_dict()

    def _fallback_proposal(self, task: RefactoringTask) -> PatchProposal:
        type_name = task.location.type_name if task.location else "UnknownType"
        method_name = task.location.method_name if task.location else "targetMethod"
        target_owner = f"{type_name}Owner"

        diff = (
            f"--- a/{task.file_path}\n"
            f"+++ b/{task.file_path}\n"
            f"@@\n"
            f"-// Feature Envy candidate method: {method_name}\n"
            f"+// Move strategy: delegate {method_name} to {target_owner}\n"
        )

        proposal = PatchProposal(
            agent_name=self.name,
            proposed_refactor_actions=["Move Method", "Delegate Call Sites", "Access Adjustment"],
            unified_diff=diff,
            rationale="Method behavior relies more on external owner data than current class.",
            expected_smell_effect="Reduce Feature Envy by ownership alignment.",
            possible_side_effects=["Call-site breakage if visibility contracts are not updated."],
            metadata={"target_owner_analysis": target_owner},
        )
        return proposal

    def _build_prompt(self, task: RefactoringTask, context: AgentContext) -> str:
        payload = {
            "task_id": task.task_id,
            "project": task.project,
            "smell_type": task.smell_type.value,
            "file_path": task.file_path,
            "type_name": task.location.type_name if task.location else None,
            "method_name": task.location.method_name if task.location else None,
            "raw_code": task.context.raw_code or "",
        }
        core_prompt = (
            "Generate a move-method oriented patch proposal for Feature Envy.\n"
            f"Task context: {json.dumps(payload, ensure_ascii=False)}\n"
            "Output valid PatchProposal JSON."
        )
        return self.apply_prompting_strategy(context, core_prompt)
