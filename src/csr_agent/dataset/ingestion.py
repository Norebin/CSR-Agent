"""Dataset ingestion and normalization."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from csr_agent.models import RefactoringTask, SmellType, TaskContext, VersionInfo
from csr_agent.models.core import LocationInfo

DEFAULT_COLUMN_ALIASES: dict[str, list[str]] = {
    "task_id": ["unique_id", "task_id", "id"],
    "dataset_split": ["dataset_split", "split"],
    "project": ["project", "Project"],
    "smell_type": ["smell_type", "Smell Type", "smell"],
    "file_path": ["file_path", "File Path", "path"],
    "package_name": ["package_name", "Package Name"],
    "type_name": ["type_name", "Type Name", "class_name"],
    "method_name": ["method_name", "Method Name"],
    "version_hint": ["version", "Version", "version_hint"],
    "begin_tag": ["begin", "begin_tag"],
    "disappear_tag": ["disappear", "disappear_tag", "end_tag"],
    "raw_code": ["raw_code", "code_before_refactor", "code_before"],
    "comment": ["comment", "Comment"],
    "diff": ["diff", "Diff"],
    "commit_history": ["commit_history", "history"],
    "refactorings": ["refactorings", "refactoring_hints"],
    "graph_context_path": ["graph_context_path", "graph_path"],
    "graph_available": ["graph_available", "has_graph"],
}


def load_tasks_from_csv(
    csv_path: Path | str,
    dataset_split: str | None = None,
    column_aliases: dict[str, list[str]] | None = None,
) -> list[RefactoringTask]:
    """Load CSV rows into normalized RefactoringTask objects."""
    path_obj = Path(csv_path)
    frame = pd.read_csv(path_obj)
    aliases = column_aliases or DEFAULT_COLUMN_ALIASES

    tasks: list[RefactoringTask] = []
    for _, row in frame.iterrows():
        row_dict = row.to_dict()
        task = _row_to_task(row_dict, aliases)
        if dataset_split and task.dataset_split and task.dataset_split != dataset_split:
            continue
        tasks.append(task)
    return tasks


def load_tasks_from_csvs(
    csv_paths: list[Path | str],
    dataset_split: str | None = None,
    column_aliases: dict[str, list[str]] | None = None,
) -> list[RefactoringTask]:
    """Load and concatenate tasks from multiple CSV files."""
    tasks: list[RefactoringTask] = []
    for path in csv_paths:
        tasks.extend(
            load_tasks_from_csv(
                path,
                dataset_split=dataset_split,
                column_aliases=column_aliases,
            )
        )
    return tasks


def discover_csvs(data_dir: Path | str) -> list[Path]:
    """Discover dataset CSV files under one directory."""
    root = Path(data_dir)
    if not root.exists():
        return []
    return sorted([p for p in root.glob("*.csv") if p.is_file()])


def _row_to_task(
    row: dict[str, Any],
    aliases: dict[str, list[str]],
) -> RefactoringTask:
    value = lambda key, default=None: _pick(row, aliases.get(key, [key]), default)

    graph_path = value("graph_context_path")
    graph_available = _to_bool(value("graph_available", graph_path is not None))

    raw_smell = str(value("smell_type", "LongMethod")).strip()
    smell_type = SmellType(raw_smell) if raw_smell in SmellType._value2member_map_ else SmellType.LONG_METHOD

    file_path = str(value("file_path", "") or "")
    location = LocationInfo(
        file_path=file_path,
        package_name=_to_optional_str(value("package_name")),
        type_name=_to_optional_str(value("type_name")),
        method_name=_to_optional_str(value("method_name")),
    )

    return RefactoringTask(
        task_id=str(value("task_id", "")),
        dataset_split=_to_optional_str(value("dataset_split")),
        project=str(value("project", "unknown")),
        version=VersionInfo(
            version_hint=_to_optional_str(value("version_hint")),
            begin_tag=_to_optional_str(value("begin_tag")),
            disappear_tag=_to_optional_str(value("disappear_tag")),
        ),
        location=location,
        file_path=file_path,
        smell_type=smell_type,
        smell_metadata={},
        context=TaskContext(
            raw_code=_to_optional_str(value("raw_code")),
            comment=_to_optional_str(value("comment")),
            diff=_to_optional_str(value("diff")),
            commit_history=value("commit_history"),
            refactorings=value("refactorings"),
            graph_context_path=_to_optional_str(graph_path),
            graph_available=graph_available,
        ),
        expected_outputs=[
            "task_input.json",
            "retrieval_evidence.json",
            "plan.json",
            "candidate_patch.diff",
            "review_feedback.json",
            "final_result.json",
            "metrics.json",
        ],
    )


def _pick(row: dict[str, Any], candidates: list[str], default: Any = None) -> Any:
    for key in candidates:
        if key in row:
            value = row[key]
            if pd.isna(value):
                continue
            return value
    return default


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y"}


def _to_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None
