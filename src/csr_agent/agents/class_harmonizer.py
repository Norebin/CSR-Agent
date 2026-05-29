"""Low-risk cleanup agent after core refactoring."""

from __future__ import annotations

import json
from typing import Any

from csr_agent.models import PatchProposal, RefactoringTask

from .base import AgentContext, AgentRuntime


class ClassHarmonizerAgent(AgentRuntime):
    name = "class_harmonizer"
    allowed_tools = {"repo_browser_tool", "ast_tool", "patch_tool"}

    def run(self, inputs: dict[str, Any], context: AgentContext) -> dict[str, Any]:
        task: RefactoringTask = inputs["task"]
        fallback = self._fallback_proposal(task)

        llm_output = self.call_llm_json(
            context,
            task_id=task.task_id,
            role="executor",
            system_prompt=(
                "You are a Java class-level harmonizer. "
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
                    "Invalid class_harmonizer LLM output, fallback to deterministic patch",
                    {"error": str(exc)},
                )
        return fallback.to_json_dict()

    def _fallback_proposal(self, task: RefactoringTask) -> PatchProposal:
        diff = (
            f"--- a/{task.file_path}\n"
            f"+++ b/{task.file_path}\n"
            f"@@\n"
            f"-// TODO: cleanup imports\n"
            f"+// Harmonized naming/import cleanup after refactoring\n"
        )

        proposal = PatchProposal(
            agent_name=self.name,
            proposed_refactor_actions=[
                "Cleanup Unused Imports",
                "Normalize Local Naming",
                "Adjust Visibility",
            ],
            unified_diff=diff,
            rationale="Low-risk structural cleanup only; no business logic rewrite.",
            expected_smell_effect="Stabilize patch and reduce integration risks.",
            possible_side_effects=[],
            metadata={"cleanup_scope": "class-level"},
        )
        return proposal

    def _build_prompt(self, task: RefactoringTask, context: AgentContext) -> str:
        payload = {
            "task_id": task.task_id,
            "project": task.project,
            "smell_type": task.smell_type.value,
            "file_path": task.file_path,
            "type_name": task.location.type_name if task.location else None,
            "raw_code": task.context.raw_code or "",
        }
        core_prompt = (
            "Generate a low-risk class harmonization patch proposal.\n"
            f"Task context: {json.dumps(payload, ensure_ascii=False)}\n"
            "Output valid PatchProposal JSON."
        )
        return self.apply_prompting_strategy(context, core_prompt)
