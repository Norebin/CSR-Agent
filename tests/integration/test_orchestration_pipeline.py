from __future__ import annotations

from pathlib import Path
import zipfile

from csr_agent.config import PipelineConfig
from csr_agent.kb import RCKBBuilder
from csr_agent.memory import EpisodicStore, MemoryManager, SkillStore
from csr_agent.models import SmellType, TaskState, ToolObservation
from csr_agent.orchestration import Orchestrator
from csr_agent.tools import build_default_tool_registry
from conftest import make_task


def _build_orchestrator(config: PipelineConfig, tmp_path: Path, semantic_store=None) -> Orchestrator:
    episodic = EpisodicStore(tmp_path / "episodic.sqlite")
    memory = MemoryManager(
        semantic_store=semantic_store,
        episodic_store=episodic,
        skill_store=SkillStore(None),
    )
    return Orchestrator(config=config, tool_registry=build_default_tool_registry(), memory_manager=memory)


def test_long_method_full_pipeline_success(test_config, workspace_tmp_root):
    task = make_task(task_id="long_method_1", smell=SmellType.LONG_METHOD)
    orchestrator = _build_orchestrator(test_config, workspace_tmp_root / "lm", semantic_store=None)
    result = orchestrator.execute_task(task)
    assert result.accepted is True
    assert result.final_state == TaskState.ACCEPTED
    artifact = Path(test_config.project.output_root) / "demo" / "long_method_1" / "final_result.json"
    assert artifact.exists()


def test_feature_envy_routes_to_move_refactorer(test_config, workspace_tmp_root):
    task = make_task(task_id="feature_envy_1", smell=SmellType.FEATURE_ENVY)
    orchestrator = _build_orchestrator(test_config, workspace_tmp_root / "fe", semantic_store=None)
    result = orchestrator.execute_task(task)
    assert result.patch_bundle is not None
    assert any(p.agent_name == "move_refactorer" for p in result.patch_bundle.proposals)


def test_graph_missing_does_not_crash(test_config, workspace_tmp_root):
    train_task = make_task(task_id="train_case", split="train", graph_available=True)
    semantic_store = RCKBBuilder().build_and_persist(
        [train_task], output_dir=workspace_tmp_root / "graph_missing" / "rckb"
    )

    task = make_task(task_id="graph_missing", graph_available=False)
    orchestrator = _build_orchestrator(
        test_config, workspace_tmp_root / "graph_missing", semantic_store=semantic_store
    )
    result = orchestrator.execute_task(task)
    assert result.evidence_pack is not None
    assert any("weights renormalized" in n for n in result.evidence_pack.notes)


def test_review_loop_stops_at_max_loops(test_config, workspace_tmp_root):
    dumped = test_config.model_dump(mode="python")
    dumped["validation"]["max_review_loops"] = 2
    cfg = PipelineConfig.model_validate(dumped)

    task = make_task(task_id="force_retry", smell=SmellType.LONG_METHOD)
    orchestrator = _build_orchestrator(cfg, workspace_tmp_root / "loop", semantic_store=None)
    original_execute = orchestrator.tools.execute

    def failing_execute(tool_name, operation, payload=None):
        if tool_name == "build_tool" and operation in {"compile_module", "compile_project"}:
            return ToolObservation(
                tool_name=tool_name,
                operation=operation,
                status="error",
                error_code="COMPILE_FAILED",
                message="forced failure for integration test",
                artifacts={"passed": False},
            )
        if tool_name == "test_tool" and operation in {"run_targeted_tests", "run_generated_assertions"}:
            return ToolObservation(
                tool_name=tool_name,
                operation=operation,
                status="error",
                error_code="TEST_FAILED",
                message="forced failure for integration test",
                artifacts={"passed": False},
            )
        return original_execute(tool_name, operation, payload)

    orchestrator.tools.execute = failing_execute

    result = orchestrator.execute_task(task)
    assert result.accepted is False
    assert result.loop_count == 2
    assert result.final_state == TaskState.FAILED


def test_disable_move_agent_via_ablation_flag(test_config, workspace_tmp_root):
    dumped = test_config.model_dump(mode="python")
    dumped["agents"]["move_refactorer"] = False
    cfg = PipelineConfig.model_validate(dumped)

    task = make_task(task_id="feature_envy_no_move", smell=SmellType.FEATURE_ENVY)
    orchestrator = _build_orchestrator(cfg, workspace_tmp_root / "ablation", semantic_store=None)
    result = orchestrator.execute_task(task)
    assert result.patch_bundle is not None
    assert all(p.agent_name != "move_refactorer" for p in result.patch_bundle.proposals)


def test_orchestrator_resolves_graph_from_zip(test_config, workspace_tmp_root):
    dumped = test_config.model_dump(mode="python")
    dumped["project"]["graph_root"] = str(workspace_tmp_root / "graph_data")
    cfg = PipelineConfig.model_validate(dumped)

    graph_project_dir = Path(cfg.project.graph_root) / "demo"
    graph_project_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(graph_project_dir / "demo-1.0.0.zip", "w") as zf:
        zf.writestr("demo-t_graph.graphml", "<graphml></graphml>")

    task = make_task(task_id="t_graph", graph_available=False)
    task.version.version_hint = "1.0.0"
    orchestrator = _build_orchestrator(cfg, workspace_tmp_root / "graph_zip", semantic_store=None)
    result = orchestrator.execute_task(task)

    assert result.evidence_pack is not None
    assert result.evidence_pack.graph_available is True
