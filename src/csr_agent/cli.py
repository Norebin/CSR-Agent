"""Command line entrypoints."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from csr_agent.config import load_pipeline_config
from csr_agent.dataset import discover_csvs, load_tasks_from_csvs
from csr_agent.llm import build_llm_client
from csr_agent.memory import EpisodicStore, MemoryManager, SkillStore
from csr_agent.models import RefactoringTask
from csr_agent.orchestration import Orchestrator
from csr_agent.runner import ExperimentRunner, RQSuiteRunner
from csr_agent.tools import build_default_tool_registry


def main() -> None:
    parser = argparse.ArgumentParser(description="CSR-Agent CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    exp = sub.add_parser("run-experiment", help="Run batch experiment from dataset CSV")
    exp.add_argument("--config", required=True)
    exp.add_argument("--contracts", required=True)
    exp.add_argument("--dataset-csv", required=True)
    exp.add_argument("--profile")
    exp.add_argument("--experiment-id")
    exp.add_argument(
        "--schemas",
        nargs="+",
        default=[
            "schemas/refactoring_task.schema.json",
            "schemas/review_feedback.schema.json",
        ],
    )

    rq = sub.add_parser("run-rq-suite", help="Run complete RQ1-RQ4 matrix experiments")
    rq.add_argument("--config", required=True)
    rq.add_argument("--contracts", required=True)
    rq.add_argument("--matrix", required=True)
    rq.add_argument("--dataset-csvs", nargs="+")
    rq.add_argument("--dataset-dir")
    rq.add_argument("--suite-id")
    rq.add_argument(
        "--schemas",
        nargs="+",
        default=[
            "schemas/refactoring_task.schema.json",
            "schemas/review_feedback.schema.json",
        ],
    )

    task_cmd = sub.add_parser("run-task", help="Run a single task JSON")
    task_cmd.add_argument("--config", required=True)
    task_cmd.add_argument("--task-json", required=True)

    args = parser.parse_args()
    if args.command == "run-experiment":
        _run_experiment(args)
    elif args.command == "run-rq-suite":
        _run_rq_suite(args)
    elif args.command == "run-task":
        _run_task(args)


def _run_experiment(args: argparse.Namespace) -> None:
    runner = ExperimentRunner.from_paths(
        config_path=args.config,
        contracts_path=args.contracts,
        schema_paths=args.schemas,
        profile=args.profile,
    )
    report = runner.run_from_csv(
        dataset_csv=args.dataset_csv,
        experiment_id=args.experiment_id,
        profile_name=args.profile,
    )
    print(json.dumps(report.to_json_dict(), ensure_ascii=False, indent=2))


def _run_rq_suite(args: argparse.Namespace) -> None:
    if args.dataset_csvs:
        csv_paths = [Path(p) for p in args.dataset_csvs]
    elif args.dataset_dir:
        csv_paths = discover_csvs(args.dataset_dir)
    else:
        cfg = load_pipeline_config(args.config)
        csv_paths = discover_csvs(cfg.project.data_root)

    if not csv_paths:
        raise ValueError("No dataset CSV found. Please pass --dataset-csvs or --dataset-dir.")

    tasks = load_tasks_from_csvs(csv_paths)
    runner = RQSuiteRunner(
        base_config_path=args.config,
        contracts_path=args.contracts,
        schema_paths=args.schemas,
        matrix_path=args.matrix,
    )
    summary = runner.run_suite(tasks, suite_id=args.suite_id)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _run_task(args: argparse.Namespace) -> None:
    config = load_pipeline_config(args.config)
    with Path(args.task_json).open("r", encoding="utf-8-sig") as fh:
        task_data = json.load(fh)
    task = RefactoringTask.model_validate(task_data)

    output_root = Path(config.project.output_root)
    episodic = EpisodicStore(output_root / "single_run_episodic.sqlite")
    memory = MemoryManager(semantic_store=None, episodic_store=episodic, skill_store=SkillStore(None))
    orchestrator = Orchestrator(
        config,
        build_default_tool_registry(
            config.tool_runtime,
            tool_enabled=config.tools.model_dump(mode="python"),
        ),
        memory,
        llm_client=build_llm_client(config.models, config.llm_api),
    )
    result = orchestrator.execute_task(task)
    print(json.dumps(result.to_json_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
