"""Batch experiment runner and artifact aggregator."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from csr_agent.artifacts import ArtifactWriter
from csr_agent.config import PipelineConfig, load_pipeline_config
from csr_agent.contracts import (
    load_agent_contracts,
    validate_json_schemas,
    validate_runtime_contracts,
)
from csr_agent.dataset import load_tasks_from_csv
from csr_agent.evaluation import MetricsEngine
from csr_agent.kb import RCKBBuilder
from csr_agent.llm import build_llm_client
from csr_agent.memory import EpisodicStore, MemoryManager, SkillStore
from csr_agent.models import ExperimentReport, RefactoringTask, TaskResult
from csr_agent.orchestration import Orchestrator
from csr_agent.tools import build_default_tool_registry


class ExperimentRunner:
    """Run config-driven experiments and persist reproducible artifacts."""

    def __init__(
        self,
        config: PipelineConfig,
        contracts_path: Path | str,
        schema_paths: list[Path | str],
    ) -> None:
        self.config = config
        self.contracts_path = Path(contracts_path)
        self.schema_paths = [Path(p) for p in schema_paths]
        self.tool_registry = build_default_tool_registry(
            config.tool_runtime,
            tool_enabled=config.tools.model_dump(mode="python"),
        )
        self.llm_client = build_llm_client(config.models, config.llm_api)
        self.artifact_writer = ArtifactWriter(config.project.output_root)
        self.metrics_engine = MetricsEngine()

        contracts = load_agent_contracts(self.contracts_path)
        validate_json_schemas(self.schema_paths)
        validate_runtime_contracts(
            config=self.config,
            contracts=contracts,
            available_agents={
                "planner_orchestrator",
                "method_refactorer",
                "move_refactorer",
                "class_harmonizer",
                "reviewer_verifier",
            },
            available_tools=self.tool_registry.names(),
        )

    @classmethod
    def from_paths(
        cls,
        config_path: Path | str,
        contracts_path: Path | str,
        schema_paths: list[Path | str],
        profile: str | None = None,
    ) -> "ExperimentRunner":
        cfg = load_pipeline_config(config_path, profile=profile)
        return cls(cfg, contracts_path=contracts_path, schema_paths=schema_paths)

    def run_from_csv(
        self,
        dataset_csv: Path | str,
        experiment_id: str | None = None,
        profile_name: str | None = None,
    ) -> ExperimentReport:
        tasks = load_tasks_from_csv(dataset_csv)
        return self.run_experiment(tasks, experiment_id=experiment_id, profile_name=profile_name)

    def run_experiment(
        self,
        tasks: list[RefactoringTask],
        experiment_id: str | None = None,
        profile_name: str | None = None,
    ) -> ExperimentReport:
        exp_id = experiment_id or datetime.now(timezone.utc).strftime("exp_%Y%m%d_%H%M%S")
        exp_dir = self.artifact_writer.experiment_dir(exp_id)
        selected_tasks = self._select_tasks(tasks)

        train_tasks = [t for t in tasks if t.dataset_split == "train"]
        semantic_store = None
        if self.config.memory.semantic_memory and train_tasks:
            semantic_store = RCKBBuilder().build_and_persist(
                train_tasks,
                output_dir=exp_dir / "rckb",
            )

        episodic_store = (
            EpisodicStore(exp_dir / "episodic_memory.sqlite")
            if self.config.memory.episode_memory
            else None
        )
        skill_store = SkillStore(None) if self.config.memory.skill_memory else None
        memory = MemoryManager(
            semantic_store=semantic_store,
            episodic_store=episodic_store,
            skill_store=skill_store,
        )

        orchestrator = Orchestrator(
            config=self.config,
            tool_registry=self.tool_registry,
            memory_manager=memory,
            artifact_writer=ArtifactWriter(exp_dir / "task_records"),
            llm_client=self.llm_client,
        )

        task_results: list[TaskResult] = []
        for task in selected_tasks:
            task_results.append(orchestrator.execute_task(task))

        self._post_validate_results(task_results, selected_tasks)

        agg = self.metrics_engine.aggregate(task_results)
        report = ExperimentReport(
            experiment_id=exp_id,
            profile_name=profile_name,
            total_tasks=len(selected_tasks),
            accepted_tasks=sum(1 for r in task_results if r.accepted),
            failed_tasks=sum(1 for r in task_results if not r.accepted),
            aggregated_metrics=agg,
            task_results=task_results,
            artifacts_root=str(exp_dir),
        )

        self._write_experiment_artifacts(exp_dir, report, selected_tasks)
        return report

    def _post_validate_results(
        self,
        task_results: list[TaskResult],
        selected_tasks: list[RefactoringTask],
    ) -> None:
        """Run PMD/tests at experiment scope (after all task refactor generations)."""
        task_map = {t.task_id: t for t in selected_tasks}
        for result in task_results:
            task = task_map.get(result.task_id)
            if task is None or result.validation is None:
                continue

            repo_path = str(Path(self.config.project.repo_root) / task.project)
            observations = list(result.validation.observations)

            targeted_pass = result.validation.targeted_tests_pass
            generated_pass = result.validation.generated_assertions_pass

            if self.config.validation.targeted_tests:
                test_obs = self.tool_registry.execute(
                    "test_tool",
                    "run_targeted_tests",
                    {
                        "repo_path": repo_path,
                        "file_path": task.file_path,
                        "changed_files": [task.file_path],
                    },
                )
                observations.append(test_obs)
                targeted_pass = bool(test_obs.artifacts.get("passed", True))

                should_run_generated = self.config.validation.generated_assertions != "never" and (
                    self.config.validation.generated_assertions == "always"
                    or targeted_pass is False
                    or targeted_pass is None
                )
                if should_run_generated:
                    gen_obs = self.tool_registry.execute(
                        "test_tool",
                        "run_generated_assertions",
                        {"repo_path": repo_path},
                    )
                    observations.append(gen_obs)
                    generated_pass = bool(gen_obs.artifacts.get("passed", True))
            elif self.config.validation.generated_assertions == "always":
                gen_obs = self.tool_registry.execute(
                    "test_tool",
                    "run_generated_assertions",
                    {"repo_path": repo_path},
                )
                observations.append(gen_obs)
                generated_pass = bool(gen_obs.artifacts.get("passed", True))

            target_smell_removed = result.validation.target_smell_removed
            newly_introduced_smells = list(result.validation.newly_introduced_smells)
            if self.config.validation.smell_redetect:
                smell_obs = self.tool_registry.execute(
                    "smell_detector_tool",
                    "detect_target_smell",
                    {
                        "repo_path": repo_path,
                        "file_path": task.file_path,
                        "task_id": task.task_id,
                        "project": task.project,
                        "smell_type": task.smell_type.value,
                        # Fallback if detector unavailable
                        "smell_removed": True,
                    },
                )
                observations.append(smell_obs)
                target_smell_removed = bool(smell_obs.artifacts.get("smell_removed", True))

                new_smell_obs = self.tool_registry.execute(
                    "smell_detector_tool",
                    "detect_new_smells",
                    {
                        "repo_path": repo_path,
                        "file_path": task.file_path,
                        "task_id": task.task_id,
                        "project": task.project,
                        "new_smells": [],
                    },
                )
                observations.append(new_smell_obs)
                newly_introduced_smells = list(new_smell_obs.artifacts.get("new_smells", []))

            result.validation.targeted_tests_pass = targeted_pass
            result.validation.generated_assertions_pass = generated_pass
            result.validation.target_smell_removed = target_smell_removed
            result.validation.newly_introduced_smells = newly_introduced_smells
            result.validation.observations = observations

            old_metric = result.metrics
            if old_metric is None:
                wall_time = 0.0
                token_cost = 0.0
            else:
                wall_time = old_metric.time_cost
                token_cost = old_metric.token_cost
            refreshed = self.metrics_engine.compute_task_metrics(
                task=task,
                result=result,
                wall_time_seconds=wall_time,
                token_cost=token_cost,
            )
            if old_metric and old_metric.extra:
                refreshed.extra.update(old_metric.extra)
            result.metrics = refreshed

    def _select_tasks(self, tasks: list[RefactoringTask]) -> list[RefactoringTask]:
        selected = [
            t
            for t in tasks
            if (not t.dataset_split or t.dataset_split == self.config.task_selection.dataset_split)
            and t.smell_type.value in self.config.task_selection.smell_types
            and t.project in self.config.task_selection.projects
        ]
        limit = self.config.task_selection.limit
        if limit is not None:
            return selected[:limit]
        return selected

    def _write_experiment_artifacts(
        self,
        exp_dir: Path,
        report: ExperimentReport,
        selected_tasks: list[RefactoringTask],
    ) -> None:
        self.artifact_writer.write_json(
            exp_dir / "config_snapshot.yaml",
            self.config.model_dump(mode="json"),
        )
        self.artifact_writer.write_json(exp_dir / "summary_metrics.csv.json", report.to_json_dict())

        rows: list[dict[str, Any]] = []
        for result in report.task_results:
            metric = result.metrics
            rows.append(
                {
                    "task_id": result.task_id,
                    "project": result.project,
                    "smell_type": result.smell_type.value,
                    "accepted": result.accepted,
                    "final_state": result.final_state.value,
                    "srr": metric.srr if metric else None,
                    "csr": metric.csr if metric else None,
                    "binary_sir": metric.binary_sir if metric else None,
                    "count_sir": metric.count_sir if metric else None,
                    "assertion_pass_rate": metric.assertion_pass_rate if metric else None,
                    "token_cost": metric.token_cost if metric else None,
                    "time_cost": metric.time_cost if metric else None,
                }
            )
        frame = pd.DataFrame(rows)
        numeric_cols = [
            "srr",
            "csr",
            "binary_sir",
            "count_sir",
            "assertion_pass_rate",
            "token_cost",
            "time_cost",
        ]
        for col in numeric_cols:
            if col in frame.columns:
                frame[col] = pd.to_numeric(frame[col], errors="coerce")
        frame.to_csv(exp_dir / "summary_metrics.csv", index=False)
        if not frame.empty:
            frame.groupby("smell_type").mean(numeric_only=True).to_csv(
                exp_dir / "by_smell_metrics.csv"
            )
            frame.groupby("project").mean(numeric_only=True).to_csv(
                exp_dir / "by_project_metrics.csv"
            )

            failure = frame[frame["accepted"] == False]  # noqa: E712
            failure.to_csv(exp_dir / "failure_analysis.csv", index=False)

            method_smells = {"LongMethod", "ComplexMethod", "LongParameterList"}
            method_frame = frame[frame["smell_type"].isin(method_smells)]
            if not method_frame.empty:
                (
                    method_frame.groupby("smell_type")
                    .mean(numeric_only=True)[["assertion_pass_rate"]]
                    .to_csv(exp_dir / "method_smell_assertion.csv")
                )
