"""Method-level refactoring agent."""

from __future__ import annotations

import json
from typing import Any

from csr_agent.models import PatchProposal, RefactoringTask

from .base import AgentContext, AgentRuntime


class MethodRefactorerAgent(AgentRuntime):
    name = "method_refactorer"
    allowed_tools = {"repo_browser_tool", "ast_tool", "patch_tool"}

    def run(self, inputs: dict[str, Any], context: AgentContext) -> dict[str, Any]:
        task: RefactoringTask = inputs["task"]
        fallback = self._fallback_proposal(task, context)

        llm_output = self.call_llm_json(
            context,
            task_id=task.task_id,
            role="executor",
            system_prompt=(
                "You are a Java method-level refactoring expert. "
                "Return only one PatchProposal JSON object. "
                "Keep patch conservative and behavior-preserving."
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
                    "Invalid method_refactorer LLM output, fallback to deterministic patch",
                    {"error": str(exc)},
                )
        return fallback.to_json_dict()

    def _fallback_proposal(
        self,
        task: RefactoringTask,
        context: AgentContext,
    ) -> PatchProposal:
        skill_cards = context.memory_manager.get_skill_cards(task.smell_type.value)
        actions = [
            "Extract Method",
            "Decompose Conditional",
            "Introduce Parameter Object"
            if task.smell_type.value == "LongParameterList"
            else "Guard Clause",
        ]

        if skill_cards:
            actions.append("Apply Skill Card Guidance")

        method_name = task.location.method_name if task.location else "targetMethod"
        diff = (
            f"--- a/{task.file_path}\n"
            f"+++ b/{task.file_path}\n"
            f"@@\n"
            f"-// TODO: {method_name} original implementation\n"
            f"+// Refactored {method_name} using low-risk intra-method transformations\n"
        )

        proposal = PatchProposal(
            agent_name=self.name,
            proposed_refactor_actions=actions,
            unified_diff=diff,
            rationale="Prioritize behavior-preserving intra-method refactoring.",
            expected_smell_effect=f"Reduce {task.smell_type.value} intensity.",
            possible_side_effects=["Potential over-extraction if context is sparse."],
            metadata={"skill_cards_used": len(skill_cards)},
        )
        return proposal

    def _build_prompt(self, task: RefactoringTask, context: AgentContext) -> str:
        context_summary = {
            "task_id": task.task_id,
            "project": task.project,
            "smell_type": task.smell_type.value,
            "file_path": task.file_path,
            "type_name": task.location.type_name if task.location else None,
            "method_name": task.location.method_name if task.location else None,
            "raw_code": task.context.raw_code or "",
        }
        core_prompt = (
            "Create a conservative method-level refactoring proposal.\n"
            f"Context JSON: {json.dumps(context_summary, ensure_ascii=False)}\n"
            "Output valid PatchProposal JSON."
        )
        return self.apply_prompting_strategy(context, core_prompt)
