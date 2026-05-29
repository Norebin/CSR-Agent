"""Metrics computation for tasks and experiments."""

from __future__ import annotations

from statistics import mean
from typing import Any

from csr_agent.models import MetricsRecord, RefactoringTask, TaskResult


class MetricsEngine:
    """Compute RQ-aligned metrics from runtime outputs."""

    def compute_task_metrics(
        self,
        task: RefactoringTask,
        result: TaskResult,
        wall_time_seconds: float,
        token_cost: float = 0.0,
    ) -> MetricsRecord:
        validation = result.validation
        if validation is None:
            return MetricsRecord(
                task_id=task.task_id,
                smell_type=task.smell_type,
                srr=0.0,
                csr=0.0,
                binary_sir=0.0,
                count_sir=0.0,
                assertion_pass_rate=None,
                token_cost=token_cost,
                time_cost=wall_time_seconds,
                codebleu=None,
                loop_count=result.loop_count,
            )

        srr = 1.0 if validation.target_smell_removed else 0.0
        csr = 1.0 if validation.project_compile_pass else 0.0
        binary_sir = 1.0 if validation.newly_introduced_smells else 0.0
        count_sir = float(len(validation.newly_introduced_smells))

        assertion_scores: list[float] = []
        if validation.targeted_tests_pass is not None:
            assertion_scores.append(1.0 if validation.targeted_tests_pass else 0.0)
        if validation.generated_assertions_pass is not None:
            assertion_scores.append(1.0 if validation.generated_assertions_pass else 0.0)
        assertion_rate = mean(assertion_scores) if assertion_scores else None

        codebleu = self._pseudo_codebleu(task.context.raw_code or "", result.patch_bundle.merged_diff if result.patch_bundle else "")

        return MetricsRecord(
            task_id=task.task_id,
            smell_type=task.smell_type,
            srr=srr,
            csr=csr,
            binary_sir=binary_sir,
            count_sir=count_sir,
            assertion_pass_rate=assertion_rate,
            token_cost=token_cost,
            time_cost=wall_time_seconds,
            codebleu=codebleu,
            loop_count=result.loop_count,
        )

    def aggregate(self, task_results: list[TaskResult]) -> dict[str, Any]:
        metrics = [r.metrics for r in task_results if r.metrics is not None]
        if not metrics:
            return {
                "mean_srr": 0.0,
                "mean_csr": 0.0,
                "mean_binary_sir": 0.0,
                "mean_count_sir": 0.0,
                "mean_time_cost": 0.0,
            }
        return {
            "mean_srr": mean(m.srr for m in metrics),
            "mean_csr": mean(m.csr for m in metrics),
            "mean_binary_sir": mean(m.binary_sir for m in metrics),
            "mean_count_sir": mean(m.count_sir for m in metrics),
            "mean_time_cost": mean(m.time_cost for m in metrics),
            "mean_token_cost": mean(m.token_cost for m in metrics),
        }

    def _pseudo_codebleu(self, original: str, diff: str) -> float:
        if not original or not diff:
            return 0.0
        o_tokens = set(original.split())
        d_tokens = set(diff.split())
        if not o_tokens:
            return 0.0
        overlap = len(o_tokens & d_tokens)
        return overlap / max(1, len(o_tokens))
