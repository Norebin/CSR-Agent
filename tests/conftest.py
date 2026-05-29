from __future__ import annotations

from pathlib import Path

import pytest

from csr_agent.config import PipelineConfig, load_pipeline_config
from csr_agent.models import RefactoringTask, SmellType, TaskContext, VersionInfo
from csr_agent.models.core import LocationInfo


@pytest.fixture
def config_template_path() -> Path:
    return Path("configs/pipeline_config.template.yaml")


@pytest.fixture
def workspace_tmp_root() -> Path:
    root = Path(".test_tmp")
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def test_config(workspace_tmp_root: Path, config_template_path: Path) -> PipelineConfig:
    cfg = load_pipeline_config(config_template_path)
    dumped = cfg.model_dump(mode="python")
    dumped["project"]["output_root"] = str(workspace_tmp_root / "outputs")
    dumped["task_selection"]["projects"] = ["demo"]
    return PipelineConfig.model_validate(dumped)


def make_task(
    task_id: str = "t1",
    smell: SmellType = SmellType.LONG_METHOD,
    graph_available: bool = True,
    split: str = "test",
) -> RefactoringTask:
    return RefactoringTask(
        task_id=task_id,
        dataset_split=split,
        project="demo",
        version=VersionInfo(version_hint="1.0.0"),
        location=LocationInfo(
            package_name="demo.pkg",
            type_name="DemoClass",
            method_name="compute",
            file_path="src/DemoClass.java",
        ),
        file_path="src/DemoClass.java",
        smell_type=smell,
        smell_metadata={},
        context=TaskContext(
            raw_code="public class DemoClass { int compute(){ return 1; } }",
            graph_available=graph_available,
            graph_context_path=None,
        ),
        expected_outputs=[],
    )
