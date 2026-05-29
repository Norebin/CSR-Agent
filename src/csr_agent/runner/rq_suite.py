"""RQ1-RQ4 suite runner with method/ablation matrix execution."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field

from csr_agent.artifacts import ArtifactWriter
from csr_agent.config import PipelineConfig, load_pipeline_config
from csr_agent.models import RefactoringTask

from .experiment_runner import ExperimentRunner


class MethodSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    profile: str | None = None
    overrides: dict[str, Any] = Field(default_factory=dict)


class RQSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = ""
    methods: list[MethodSpec]


class RQSuiteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rq1: RQSpec
    rq2: RQSpec
    rq3: RQSpec
    rq4: RQSpec


class RQSuiteRunner:
    """Run RQ1-RQ4 in one reproducible batch and export comparison tables."""

    def __init__(
        self,
        base_config_path: Path | str,
        contracts_path: Path | str,
        schema_paths: list[Path | str],
        matrix_path: Path | str,
    ) -> None:
        self.base_config_path = Path(base_config_path)
        self.contracts_path = Path(contracts_path)
        self.schema_paths = [Path(p) for p in schema_paths]
        self.suite_cfg = load_rq_suite_config(matrix_path)
        self.base_cfg = load_pipeline_config(self.base_config_path)
        self.writer = ArtifactWriter(self.base_cfg.project.output_root)

    def run_suite(
        self,
        tasks: list[RefactoringTask],
        suite_id: str | None = None,
    ) -> dict[str, Any]:
        sid = suite_id or datetime.now(timezone.utc).strftime("rq_suite_%Y%m%d_%H%M%S")
        suite_dir = self.writer.experiment_dir(sid)

        task_rows: list[dict[str, Any]] = []
        run_rows: list[dict[str, Any]] = []
        outputs: dict[str, Any] = {"suite_id": sid, "runs": []}

        for rq_name in ("rq1", "rq2", "rq3", "rq4"):
            rq_spec = getattr(self.suite_cfg, rq_name)
            for method in rq_spec.methods:
                cfg = load_pipeline_config(self.base_config_path, profile=method.profile)
                cfg = apply_overrides(cfg, method.overrides)
                runner = ExperimentRunner(
                    config=cfg,
                    contracts_path=self.contracts_path,
                    schema_paths=self.schema_paths,
                )
                exp_id = f"{sid}_{rq_name}_{sanitize_name(method.name)}"
                report = runner.run_experiment(
                    tasks=tasks,
                    experiment_id=exp_id,
                    profile_name=method.profile,
                )
                outputs["runs"].append(
                    {
                        "rq": rq_name,
                        "method": method.name,
                        "profile": method.profile,
                        "experiment_id": exp_id,
                        "artifacts_root": report.artifacts_root,
                    }
                )
                run_rows.append(
                    {
                        "rq": rq_name,
                        "method": method.name,
                        "profile": method.profile or "",
                        "experiment_id": exp_id,
                        "total_tasks": report.total_tasks,
                        "accepted_tasks": report.accepted_tasks,
                        "failed_tasks": report.failed_tasks,
                        "mean_srr": report.aggregated_metrics.get("mean_srr", 0.0),
                        "mean_csr": report.aggregated_metrics.get("mean_csr", 0.0),
                        "mean_binary_sir": report.aggregated_metrics.get("mean_binary_sir", 0.0),
                        "mean_count_sir": report.aggregated_metrics.get("mean_count_sir", 0.0),
                        "mean_token_cost": report.aggregated_metrics.get("mean_token_cost", 0.0),
                        "mean_time_cost": report.aggregated_metrics.get("mean_time_cost", 0.0),
                    }
                )
                for result in report.task_results:
                    metric = result.metrics
                    task_rows.append(
                        {
                            "rq": rq_name,
                            "method": method.name,
                            "profile": method.profile or "",
                            "experiment_id": exp_id,
                            "task_id": result.task_id,
                            "project": result.project,
                            "smell_type": result.smell_type.value,
                            "accepted": result.accepted,
                            "final_state": result.final_state.value,
                            "loop_count": result.loop_count,
                            "srr": metric.srr if metric else 0.0,
                            "csr": metric.csr if metric else 0.0,
                            "binary_sir": metric.binary_sir if metric else 0.0,
                            "count_sir": metric.count_sir if metric else 0.0,
                            "assertion_pass_rate": metric.assertion_pass_rate if metric else None,
                            "token_cost": metric.token_cost if metric else 0.0,
                            "time_cost": metric.time_cost if metric else 0.0,
                        }
                    )

        task_df = pd.DataFrame(task_rows)
        run_df = pd.DataFrame(run_rows)

        if not task_df.empty:
            numeric_cols = [
                "srr",
                "csr",
                "binary_sir",
                "count_sir",
                "assertion_pass_rate",
                "token_cost",
                "time_cost",
                "loop_count",
            ]
            for col in numeric_cols:
                if col in task_df.columns:
                    task_df[col] = pd.to_numeric(task_df[col], errors="coerce")

            task_df.to_csv(suite_dir / "rq_all_task_metrics.csv", index=False)
            run_df.to_csv(suite_dir / "rq_run_summary.csv", index=False)

            value_cols = [
                col
                for col in [
                    "srr",
                    "csr",
                    "binary_sir",
                    "count_sir",
                    "assertion_pass_rate",
                    "token_cost",
                    "time_cost",
                    "loop_count",
                ]
                if col in task_df.columns
            ]

            by_method_smell = (
                task_df.groupby(["rq", "method", "smell_type"])
                .mean(numeric_only=True)[value_cols]
                .reset_index()
            )
            by_method_smell.to_csv(suite_dir / "rq_by_method_smell.csv", index=False)

            by_method = (
                task_df.groupby(["rq", "method"])
                .mean(numeric_only=True)[value_cols]
                .reset_index()
            )
            by_method.to_csv(suite_dir / "rq_by_method.csv", index=False)

            method_smells = {"LongMethod", "ComplexMethod", "LongParameterList"}
            method_df = task_df[task_df["smell_type"].isin(method_smells)]
            if not method_df.empty and "assertion_pass_rate" in method_df.columns:
                method_assert = (
                    method_df.groupby(["rq", "method", "smell_type"])
                    .mean(numeric_only=True)[["assertion_pass_rate"]]
                    .reset_index()
                )
                method_assert.to_csv(suite_dir / "rq_method_level_assertion.csv", index=False)

            rq4_df = task_df[task_df["rq"] == "rq4"]
            if not rq4_df.empty:
                rq4_tradeoff = (
                    rq4_df.groupby(["method"])
                    .mean(numeric_only=True)[["srr", "csr", "binary_sir", "token_cost", "time_cost", "loop_count"]]
                    .reset_index()
                )
                rq4_tradeoff.to_csv(suite_dir / "rq4_loop_tradeoff.csv", index=False)

        (suite_dir / "rq_suite_summary.json").write_text(
            json.dumps(outputs, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return outputs


def load_rq_suite_config(path: Path | str) -> RQSuiteConfig:
    path_obj = Path(path)
    with path_obj.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return RQSuiteConfig.model_validate(data)


def apply_overrides(config: PipelineConfig, overrides: dict[str, Any]) -> PipelineConfig:
    dumped = config.model_dump(mode="python")
    for key, value in overrides.items():
        set_dotted_key(dumped, key, value)
    return PipelineConfig.model_validate(dumped)


def set_dotted_key(target: dict[str, Any], dotted_key: str, value: Any) -> None:
    parts = dotted_key.split(".")
    node: dict[str, Any] = target
    for part in parts[:-1]:
        if part not in node or not isinstance(node[part], dict):
            node[part] = {}
        node = node[part]
    node[parts[-1]] = value


def sanitize_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_").lower()
