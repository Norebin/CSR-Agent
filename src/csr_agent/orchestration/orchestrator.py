"""Main state-machine orchestrator."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from csr_agent.agents import (
    AgentContext,
    ClassHarmonizerAgent,
    MethodRefactorerAgent,
    MoveRefactorerAgent,
    PlannerOrchestratorAgent,
    ReviewerVerifierAgent,
)
from csr_agent.artifacts import ArtifactWriter
from csr_agent.config import PipelineConfig
from csr_agent.evaluation import MetricsEngine
from csr_agent.llm import LLMClient
from csr_agent.logging import StructuredLogger, utc_now_iso
from csr_agent.memory import MemoryManager
from csr_agent.models import (
    EvidencePack,
    MetricsRecord,
    PatchProposal,
    PlanGraph,
    RefactoringTask,
    ReviewDecision,
    ReviewFeedback,
    RiskLevel,
    TaskResult,
    TaskState,
)
from csr_agent.patching import PatchIntegrator
from csr_agent.resolver import EntityTracker, GraphResolver, VersionResolver
from csr_agent.retrieval import RetrievalEngine
from csr_agent.tools import ToolRegistry
from csr_agent.validation import ValidationPipeline

from .state_machine import TaskStateMachine


class Orchestrator:
    """Execute one smell task end-to-end via a bounded review loop."""

    def __init__(
        self,
        config: PipelineConfig,
        tool_registry: ToolRegistry,
        memory_manager: MemoryManager,
        artifact_writer: ArtifactWriter | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.config = config
        self.tools = tool_registry
        self.memory = memory_manager
        self.llm_client = llm_client
        self.version_resolver = VersionResolver()
        self.entity_tracker = EntityTracker()
        self.graph_resolver = GraphResolver(
            config.project.graph_root,
            Path(config.project.output_root) / ".graph_cache",
        )
        self.retrieval_engine = RetrievalEngine()
        self.patch_integrator = PatchIntegrator()
        self.validation_pipeline = ValidationPipeline(
            tool_registry,
            config.validation,
            config.project,
            config.tool_runtime,
        )
        self.metrics_engine = MetricsEngine()
        self.artifact_writer = artifact_writer or ArtifactWriter(config.project.output_root)

        self.agents = {
            "planner_orchestrator": PlannerOrchestratorAgent(),
            "method_refactorer": MethodRefactorerAgent(),
            "move_refactorer": MoveRefactorerAgent(),
            "class_harmonizer": ClassHarmonizerAgent(),
            "reviewer_verifier": ReviewerVerifierAgent(),
        }

    def execute_task(self, task: RefactoringTask) -> TaskResult:
        started = time.perf_counter()
        task_dir = self.artifact_writer.task_dir(task.project, task.task_id)
        logger = StructuredLogger(task_dir / "execution.log")
        ctx = AgentContext(
            tool_registry=self.tools,
            memory_manager=self.memory,
            logger=logger,
            llm_client=self.llm_client,
            prompting=self.config.prompting,
        )
        machine = TaskStateMachine()
        warnings: list[str] = []

        self.artifact_writer.write_json(task_dir / "task_input.json", task.to_json_dict())
        self._remember(task.task_id, machine.current.value, {"event": "task_loaded"})
        logger.emit(task.task_id, machine.current.value, "Task loaded")

        # 1) version resolve
        tags_obs = self.tools.execute(
            "git_tool",
            "list_tags",
            {
                "repo_path": str(Path(self.config.project.repo_root) / task.project),
                "tags": task.smell_metadata.get("tags", []),
            },
        )
        resolve = self.version_resolver.resolve(task, tags_obs.artifacts.get("tags", []))
        task.version.resolved_begin_tag = resolve.get("resolved_begin_tag")
        task.version.resolved_disappear_tag = resolve.get("resolved_disappear_tag")
        machine.transition(TaskState.VERSION_RESOLVED)
        logger.emit(task.task_id, machine.current.value, "Version resolved", resolve)
        self._remember(task.task_id, machine.current.value, resolve)
        if not resolve.get("recoverable", False):
            warnings.append("Version resolution uncertainty is high.")

        # 1.5) graph context resolve
        graph_resolution = self.graph_resolver.resolve(task)
        if graph_resolution.graph_context_path:
            task.context.graph_context_path = graph_resolution.graph_context_path
        task.context.graph_available = bool(graph_resolution.graph_available)
        logger.emit(
            task.task_id,
            machine.current.value,
            "Graph context resolved",
            graph_resolution.to_dict(),
        )
        self._remember(task.task_id, machine.current.value, graph_resolution.to_dict())
        if not graph_resolution.graph_available:
            warnings.append("Graph context missing or unresolved.")

        # 2) entity locate
        entity_mapping = self.entity_tracker.track(task)
        machine.transition(TaskState.ENTITY_LOCATED)
        logger.emit(
            task.task_id,
            machine.current.value,
            "Entity tracked",
            entity_mapping.to_json_dict(),
        )
        self._remember(task.task_id, machine.current.value, entity_mapping.to_json_dict())
        if not entity_mapping.anchored and not entity_mapping.recoverable:
            return self._fail_result(task, machine, warnings, logger, started)

        # 3) retrieval
        evidence_pack = self._retrieve_evidence(task)
        self.artifact_writer.write_json(
            task_dir / "retrieval_evidence.json", evidence_pack.to_json_dict()
        )
        machine.transition(TaskState.EVIDENCE_RETRIEVED)
        logger.emit(
            task.task_id,
            machine.current.value,
            "Evidence retrieved",
            {"items": len(evidence_pack.items)},
        )
        self._remember(task.task_id, machine.current.value, evidence_pack.to_json_dict())

        max_loops = self.config.validation.max_review_loops
        latest_plan: PlanGraph | None = None
        latest_feedback: ReviewFeedback | None = None
        latest_patch_bundle = None
        latest_validation = None
        loop_count = 0
        accepted = False

        while loop_count < max_loops:
            loop_count += 1
            if machine.current == TaskState.REPLAN:
                machine.transition(TaskState.PLAN_GENERATED)
            else:
                machine.transition(TaskState.PLAN_GENERATED)

            latest_plan = self._make_plan(task, evidence_pack, ctx)
            self.artifact_writer.write_json(task_dir / "plan.json", latest_plan.to_json_dict())
            self._remember(task.task_id, machine.current.value, latest_plan.to_json_dict())

            machine.transition(TaskState.PATCH_GENERATED)
            proposals = self._generate_patches(task, ctx)
            self._remember(
                task.task_id,
                machine.current.value,
                {"proposal_agents": [p.agent_name for p in proposals]},
            )

            machine.transition(TaskState.PATCH_INTEGRATED)
            latest_patch_bundle = self.patch_integrator.integrate(task.task_id, proposals)
            self.artifact_writer.write_text(
                task_dir / "candidate_patch.diff", latest_patch_bundle.merged_diff
            )
            self._remember(
                task.task_id,
                machine.current.value,
                latest_patch_bundle.to_json_dict(),
            )

            machine.transition(TaskState.STATIC_VALIDATED)
            latest_validation = self.validation_pipeline.run(task, latest_patch_bundle)
            machine.transition(TaskState.DYNAMIC_VALIDATED)
            machine.transition(TaskState.SMELL_RECHECKED)
            self._remember(
                task.task_id,
                machine.current.value,
                latest_validation.to_json_dict(),
            )

            machine.transition(TaskState.REVIEWED)
            latest_feedback = self._review(task, latest_patch_bundle, latest_validation, loop_count, ctx)
            self.artifact_writer.write_json(
                task_dir / "review_feedback.json",
                latest_feedback.to_json_dict(),
            )
            self._remember(task.task_id, machine.current.value, latest_feedback.to_json_dict())

            if latest_feedback.decision == ReviewDecision.ACCEPT:
                machine.transition(TaskState.ACCEPTED)
                accepted = True
                break
            if latest_feedback.decision == ReviewDecision.RETRY and loop_count < max_loops:
                machine.transition(TaskState.REPLAN)
                continue
            machine.transition(TaskState.FAILED)
            break

        final_state = machine.current
        task_result = TaskResult(
            task_id=task.task_id,
            project=task.project,
            smell_type=task.smell_type,
            final_state=final_state,
            accepted=accepted,
            loop_count=loop_count,
            evidence_pack=evidence_pack,
            plan=latest_plan,
            patch_bundle=latest_patch_bundle,
            review_feedback=latest_feedback,
            validation=latest_validation,
            warnings=warnings,
        )

        elapsed = time.perf_counter() - started
        token_usage = float(ctx.llm_usage.get("total_tokens", 0))
        metrics = self.metrics_engine.compute_task_metrics(
            task,
            task_result,
            elapsed,
            token_cost=token_usage,
        )
        metrics.extra["llm_usage"] = dict(ctx.llm_usage)
        task_result.metrics = metrics
        self._write_final_artifacts(task_dir, task_result, metrics)
        return task_result

    def _retrieve_evidence(self, task: RefactoringTask) -> EvidencePack:
        if not self.config.retrieval.enabled:
            return EvidencePack(
                task_id=task.task_id,
                retrieval_mode="disabled",
                graph_available=task.context.graph_available,
                items=[],
                notes=["retrieval disabled in config"],
            )
        if self.memory.semantic_store is None:
            return EvidencePack(
                task_id=task.task_id,
                retrieval_mode="no_store",
                graph_available=task.context.graph_available,
                items=[],
                notes=["semantic store missing; skip retrieval"],
            )
        return self.retrieval_engine.retrieve(task, self.memory.semantic_store, self.config.retrieval)

    def _make_plan(
        self,
        task: RefactoringTask,
        evidence_pack: EvidencePack,
        ctx: AgentContext,
    ) -> PlanGraph:
        if not self.config.agents.planner_orchestrator:
            return PlanGraph(
                task_summary=f"default plan for {task.task_id}",
                smell_diagnosis="planner disabled",
                risk_assessment="unknown",
                selected_agents=["method_refactorer", "reviewer_verifier"],
                execution_order=["method_refactorer", "reviewer_verifier"],
                required_tools=[],
                stop_conditions=["max_review_loops_reached"],
                acceptance_criteria=["compile_pass"],
                nodes=[],
                edges=[],
            )
        output = self.agents["planner_orchestrator"].run(
            {"task": task, "evidence_pack": evidence_pack},
            ctx,
        )
        return PlanGraph.model_validate(output)

    def _generate_patches(
        self,
        task: RefactoringTask,
        ctx: AgentContext,
    ) -> list[PatchProposal]:
        proposals: list[PatchProposal] = []

        if task.smell_type.value == "FeatureEnvy":
            if self.config.agents.move_refactorer:
                output = self.agents["move_refactorer"].run({"task": task}, ctx)
                proposals.append(PatchProposal.model_validate(output))
        else:
            if self.config.agents.method_refactorer:
                output = self.agents["method_refactorer"].run({"task": task}, ctx)
                proposals.append(PatchProposal.model_validate(output))

        if self.config.agents.class_harmonizer:
            output = self.agents["class_harmonizer"].run({"task": task}, ctx)
            proposals.append(PatchProposal.model_validate(output))

        if not proposals:
            proposals.append(
                PatchProposal(
                    agent_name="fallback",
                    proposed_refactor_actions=["No-op fallback"],
                    unified_diff=f"--- a/{task.file_path}\n+++ b/{task.file_path}\n",
                    rationale="No refactorer enabled by config.",
                    expected_smell_effect="none",
                )
            )
        return proposals

    def _review(
        self,
        task: RefactoringTask,
        patch_bundle,
        validation,
        loop_count: int,
        ctx: AgentContext,
    ) -> ReviewFeedback:
        if not self.config.agents.reviewer_verifier:
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
                symptom = "reviewer disabled; deterministic checks passed"
            elif loop_count < self.config.validation.max_review_loops:
                decision = ReviewDecision.RETRY
                should_retry = True
                symptom = "reviewer disabled; deterministic checks failed but retry allowed"
            else:
                decision = ReviewDecision.FAIL
                should_retry = False
                symptom = "reviewer disabled; deterministic checks failed at max loops"
            return ReviewFeedback(
                task_id=task.task_id,
                decision=decision,
                failure_stage="review",
                symptom=symptom,
                location=None,
                risk_level=RiskLevel.MEDIUM if not accepted else RiskLevel.LOW,
                suggested_fix="Narrow patch scope and retry with stricter validation." if not accepted else "",
                should_retry=should_retry,
                recommended_agent="method_refactorer"
                if task.smell_type.value != "FeatureEnvy"
                else "move_refactorer",
                forbidden_actions_next_round=["ignore validation failures"] if not accepted else [],
                tool_observations=validation.observations,
            )
        output = self.agents["reviewer_verifier"].run(
            {
                "task": task,
                "patch_bundle": patch_bundle,
                "validation": validation,
                "loop_count": loop_count,
                "max_loops": self.config.validation.max_review_loops,
            },
            ctx,
        )
        return ReviewFeedback.model_validate(output)

    def _write_final_artifacts(
        self,
        task_dir: Path,
        result: TaskResult,
        metrics: MetricsRecord,
    ) -> None:
        self.artifact_writer.write_json(task_dir / "final_result.json", result.to_json_dict())
        self.artifact_writer.write_json(task_dir / "metrics.json", metrics.to_json_dict())

    def _fail_result(
        self,
        task: RefactoringTask,
        machine: TaskStateMachine,
        warnings: list[str],
        logger: StructuredLogger,
        started: float,
    ) -> TaskResult:
        machine.transition(TaskState.FAILED)
        logger.emit(task.task_id, machine.current.value, "Task failed at entity resolution")
        task_result = TaskResult(
            task_id=task.task_id,
            project=task.project,
            smell_type=task.smell_type,
            final_state=machine.current,
            accepted=False,
            loop_count=0,
            warnings=warnings + ["entity tracking unrecoverable"],
        )
        elapsed = time.perf_counter() - started
        task_result.metrics = self.metrics_engine.compute_task_metrics(task, task_result, elapsed)
        return task_result

    def _remember(self, task_id: str, stage: str, payload: dict[str, Any]) -> None:
        if self.memory.episodic_store is None:
            return
        self.memory.episodic_store.append(
            task_id=task_id,
            stage=stage,
            payload=payload,
            created_at=utc_now_iso(),
        )
