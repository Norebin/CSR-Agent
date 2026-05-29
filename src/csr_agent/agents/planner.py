"""Planner / Orchestrator agent implementation."""

from __future__ import annotations

import json
from typing import Any

from csr_agent.models import EvidencePack, PlanEdge, PlanGraph, PlanNode, RefactoringTask

from .base import AgentContext, AgentRuntime


class PlannerOrchestratorAgent(AgentRuntime):
    name = "planner_orchestrator"
    allowed_tools = {"repo_browser_tool", "retrieval_tool", "entity_tracker_tool"}

    def run(self, inputs: dict[str, Any], context: AgentContext) -> dict[str, Any]:
        task: RefactoringTask = inputs["task"]
        evidence: EvidencePack = inputs["evidence_pack"]
        fallback_plan = self._fallback_plan(task, evidence)

        llm_output = self.call_llm_json(
            context,
            task_id=task.task_id,
            role="planner",
            system_prompt=(
                "You are a Java code-smell refactoring planner. "
                "Return only JSON for PlanGraph."
            ),
            user_prompt=self._build_prompt(task, evidence, context),
            schema=PlanGraph.model_json_schema(),
        )
        if llm_output is not None:
            try:
                plan = PlanGraph.model_validate(llm_output)
                if task.smell_type.value == "FeatureEnvy" and "move_refactorer" not in plan.selected_agents:
                    raise ValueError("FeatureEnvy plan must include move_refactorer")
                return plan.to_json_dict()
            except Exception as exc:
                context.logger.emit(
                    task.task_id,
                    self.name,
                    "Invalid planner LLM output, fallback to deterministic plan",
                    {"error": str(exc)},
                )
        return fallback_plan.to_json_dict()

    def _fallback_plan(self, task: RefactoringTask, evidence: EvidencePack) -> PlanGraph:
        selected_agents = (
            ["method_refactorer", "class_harmonizer", "reviewer_verifier"]
            if task.smell_type.value != "FeatureEnvy"
            else ["move_refactorer", "class_harmonizer", "reviewer_verifier"]
        )
        execution_order = ["planner_orchestrator", *selected_agents]

        nodes = [
            PlanNode(
                node_id="retrieve_evidence",
                kind="service",
                description="Collect retrieval evidence pack",
                required_tools=["retrieval_tool"],
            ),
            PlanNode(
                node_id="refactor_main",
                kind="agent",
                description=f"Primary refactor path for {task.smell_type.value}",
                required_tools=["ast_tool", "patch_tool"],
            ),
            PlanNode(
                node_id="review_decision",
                kind="agent",
                description="Review and decide accept/retry/fail",
                required_tools=["repo_browser_tool"],
            ),
        ]
        edges = [
            PlanEdge(source="retrieve_evidence", target="refactor_main", edge_type="serial"),
            PlanEdge(source="refactor_main", target="review_decision", edge_type="serial"),
        ]
        if not evidence.graph_available:
            risk = "graph_context_missing"
        else:
            risk = "normal"

        return PlanGraph(
            task_summary=f"Refactor {task.smell_type.value} for {task.project}:{task.task_id}",
            smell_diagnosis=f"Evidence count={len(evidence.items)}",
            risk_assessment=risk,
            selected_agents=selected_agents,
            execution_order=execution_order,
            required_tools=list(self.allowed_tools),
            stop_conditions=[
                "accepted_by_reviewer",
                "max_review_loops_reached",
                "unrecoverable_entity_resolution_failure",
            ],
            acceptance_criteria=[
                "compile_pass",
                "target_smell_removed",
                "no_high_risk_new_smells",
            ],
            nodes=nodes,
            edges=edges,
        )

    def _build_prompt(
        self,
        task: RefactoringTask,
        evidence: EvidencePack,
        context: AgentContext,
    ) -> str:
        evidence_payload = [item.to_json_dict() for item in evidence.items[:5]]
        core_prompt = (
            f"Task id: {task.task_id}\n"
            f"Project: {task.project}\n"
            f"Smell type: {task.smell_type.value}\n"
            f"File: {task.file_path}\n"
            f"Method: {task.location.method_name if task.location else None}\n"
            f"Graph available: {task.context.graph_available}\n"
            "Routing constraint:\n"
            "- If smell_type == FeatureEnvy, selected_agents must include move_refactorer.\n"
            "- Otherwise use method_refactorer and do not require move_refactorer.\n"
            f"Evidence: {json.dumps(evidence_payload, ensure_ascii=False)}\n"
            "Output a complete PlanGraph JSON object."
        )
        return self.apply_prompting_strategy(context, core_prompt)
