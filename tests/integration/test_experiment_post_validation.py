from __future__ import annotations

from csr_agent.runner import ExperimentRunner
from conftest import make_task


def test_smell_detection_runs_in_post_validation_stage(test_config):
    runner = ExperimentRunner(
        config=test_config,
        contracts_path="configs/agent_contracts.yaml",
        schema_paths=[
            "schemas/refactoring_task.schema.json",
            "schemas/review_feedback.schema.json",
        ],
    )

    original_execute = runner.tool_registry.execute
    smell_calls: list[tuple[str, str]] = []

    def wrapped_execute(tool_name, operation, payload=None):  # noqa: ANN001
        if tool_name == "smell_detector_tool":
            smell_calls.append((tool_name, operation))
        return original_execute(tool_name, operation, payload)

    runner.tool_registry.execute = wrapped_execute

    task = make_task(task_id="post_validate_case")
    report = runner.run_experiment([task], experiment_id="it_post_validate")

    assert report.total_tasks == 1
    assert ("smell_detector_tool", "detect_target_smell") in smell_calls
    assert ("smell_detector_tool", "detect_new_smells") in smell_calls
