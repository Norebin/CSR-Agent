from __future__ import annotations

from pathlib import Path

import yaml

from csr_agent.config import PipelineConfig
from csr_agent.runner import RQSuiteRunner
from conftest import make_task


def test_rq_suite_runner_generates_summary_artifacts(test_config, workspace_tmp_root):
    dumped = test_config.model_dump(mode="python")
    dumped["llm_api"]["enabled"] = False
    cfg = PipelineConfig.model_validate(dumped)
    cfg_path = workspace_tmp_root / "rq_suite_config.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False), encoding="utf-8")

    matrix = {
        "rq1": {"description": "t", "methods": [{"name": "m1", "profile": None, "overrides": {}}]},
        "rq2": {"description": "t", "methods": [{"name": "m2", "profile": None, "overrides": {}}]},
        "rq3": {"description": "t", "methods": [{"name": "m3", "profile": None, "overrides": {}}]},
        "rq4": {"description": "t", "methods": [{"name": "m4", "profile": None, "overrides": {}}]},
    }
    matrix_path = workspace_tmp_root / "rq_suite_matrix.yaml"
    matrix_path.write_text(yaml.safe_dump(matrix, sort_keys=False), encoding="utf-8")

    runner = RQSuiteRunner(
        base_config_path=cfg_path,
        contracts_path="configs/agent_contracts.yaml",
        schema_paths=[
            "schemas/refactoring_task.schema.json",
            "schemas/review_feedback.schema.json",
        ],
        matrix_path=matrix_path,
    )
    summary = runner.run_suite(
        tasks=[
            make_task(task_id="rq_suite_lm"),
            make_task(task_id="rq_suite_fe", smell="FeatureEnvy"),
        ],
        suite_id="rq_suite_test",
    )

    assert summary["suite_id"] == "rq_suite_test"
    out = Path(cfg.project.output_root) / "experiments" / "rq_suite_test"
    assert (out / "rq_all_task_metrics.csv").exists()
    assert (out / "rq_by_method_smell.csv").exists()
