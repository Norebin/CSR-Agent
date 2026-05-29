"""Reviewer/verifier agent for accept/retry/fail decisions."""

from __future__ import annotations

import json
from typing import Any

from csr_agent.models import (
    PatchBundle,
    RefactoringTask,
    ReviewDecision,
    ReviewFeedback,
    ReviewLocation,
    RiskLevel,
    ValidationBundle,
)

from .base import AgentContext, AgentRuntime


class ReviewerVerifierAgent(AgentRuntime):
    name = "reviewer_verifier"
    allowed_tools = {"repo_browser_tool"}

    def run(self, inputs: dict[str, Any], context: AgentContext) -> dict[str, Any]:
        task: RefactoringTask = inputs["task"]
        patch_bundle: PatchBundle = inputs["patch_bundle"]
        validation: ValidationBundle = inputs["validation"]
        loop_count: int = int(inputs.get("loop_count", 1))
        max_loops: int = int(inputs.get("max_loops", 3))

        fallback = self._fallback_feedback(task, validation, loop_count, max_loops)
        llm_output = self.call_llm_json(
            context,
            task_id=task.task_id,
            role="reviewer",
            system_prompt=(
                "You are a strict reviewer for Java refactoring patches. "
                "Return only one ReviewFeedback JSON object."
            ),
            user_prompt=self._build_prompt(
                task,
                patch_bundle,
                validation,
                loop_count,
                max_loops,
                context,
            ),
            schema=ReviewFeedback.model_json_schema(),
        )
        if llm_output is not None:
            try:
                llm_output["task_id"] = task.task_id
                feedback = ReviewFeedback.model_validate(llm_output)
                return feedback.to_json_dict()
            except Exception as exc:
                context.logger.emit(
                    task.task_id,
                    self.name,
                    "Invalid reviewer LLM output, fallback to deterministic decision",
                    {"error": str(exc)},
                )
        return fallback.to_json_dict()

    def _fallback_feedback(
        self,
        task: RefactoringTask,
        validation: ValidationBundle,
        loop_count: int,
        max_loops: int,
    ) -> ReviewFeedback:

        static_ok = validation.parser_pass and validation.project_compile_pass
        dynamic_ok = (
            validation.targeted_tests_pass is not False
            and validation.generated_assertions_pass is not False
        )
        smell_ok = validation.target_smell_removed
        no_new_high_risk = len(validation.newly_introduced_smells) == 0

        accepted = static_ok and dynamic_ok and smell_ok and no_new_high_risk
        if accepted:
            decision = ReviewDecision.ACCEPT
            should_retry = False
            stage = "review"
            symptom = "All checks passed."
            risk = RiskLevel.LOW
            suggested_fix = ""
            forbidden = []
        else:
            if loop_count < max_loops:
                decision = ReviewDecision.RETRY
                should_retry = True
            else:
                decision = ReviewDecision.FAIL
                should_retry = False

            stage = _pick_failure_stage(validation)
            symptom = _compose_symptom(validation)
            risk = RiskLevel.HIGH if not static_ok else RiskLevel.MEDIUM
            suggested_fix = "Retry with smaller patch scope and targeted fix."
            forbidden = ["broad architectural rewrite", "ignore tool failures"]

        feedback = ReviewFeedback(
            task_id=task.task_id,
            decision=decision,
            failure_stage=stage,
            symptom=symptom,
            location=ReviewLocation(
                file_path=task.file_path,
                class_name=task.location.type_name if task.location else None,
                method_name=task.location.method_name if task.location else None,
            ),
            risk_level=risk,
            suggested_fix=suggested_fix,
            should_retry=should_retry,
            recommended_agent=_suggest_agent(task),
            forbidden_actions_next_round=forbidden,
            tool_observations=validation.observations,
        )
        return feedback

    def _build_prompt(
        self,
        task: RefactoringTask,
        patch_bundle: PatchBundle,
        validation: ValidationBundle,
        loop_count: int,
        max_loops: int,
        context: AgentContext,
    ) -> str:
        summary = {
            "task_id": task.task_id,
            "project": task.project,
            "smell_type": task.smell_type.value,
            "file_path": task.file_path,
            "loop_count": loop_count,
            "max_loops": max_loops,
            "validation": validation.to_json_dict(),
            "patch_diff_preview": patch_bundle.merged_diff[:2000],
        }
        core_prompt = (
            "Review the candidate patch based on validation results.\n"
            f"Review context: {json.dumps(summary, ensure_ascii=False)}\n"
            "Decision policy:\n"
            "- accept only when static/dynamic/smell checks are all satisfied.\n"
            "- retry when failures may be recoverable and loop_count < max_loops.\n"
            "- fail when unrecoverable or loop_count reached max_loops.\n"
            "Output valid ReviewFeedback JSON."
        )
        return self.apply_prompting_strategy(context, core_prompt)


def _pick_failure_stage(validation: ValidationBundle) -> str:
    if not validation.parser_pass or not validation.module_compile_pass or not validation.project_compile_pass:
        return "static_validation"
    if validation.targeted_tests_pass is False or validation.generated_assertions_pass is False:
        return "dynamic_validation"
    if not validation.target_smell_removed:
        return "smell_redetect"
    return "review"


def _compose_symptom(validation: ValidationBundle) -> str:
    bits: list[str] = []
    if not validation.parser_pass:
        bits.append("AST parse failed")
    if not validation.project_compile_pass:
        bits.append("project compile failed")
    if validation.targeted_tests_pass is False:
        bits.append("targeted tests failed")
    if validation.generated_assertions_pass is False:
        bits.append("generated assertions failed")
    if not validation.target_smell_removed:
        bits.append("target smell still detected")
    if validation.newly_introduced_smells:
        bits.append("new smells introduced")
    return "; ".join(bits) if bits else "validation uncertain"


def _suggest_agent(task: RefactoringTask) -> str:
    if task.smell_type.value == "FeatureEnvy":
        return "move_refactorer"
    return "method_refactorer"
