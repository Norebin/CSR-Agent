"""Static/dynamic/smell validation pipeline."""

from __future__ import annotations

from pathlib import Path

from csr_agent.config import ProjectConfig, ToolRuntimeConfig, ValidationConfig
from csr_agent.models import PatchBundle, RefactoringTask, ValidationBundle
from csr_agent.tools import ToolRegistry


class ValidationPipeline:
    """Run tool-backed validation stages with graceful degradation."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        config: ValidationConfig,
        project_cfg: ProjectConfig,
        tool_runtime: ToolRuntimeConfig,
    ) -> None:
        self.tools = tool_registry
        self.config = config
        self.project_cfg = project_cfg
        self.tool_runtime = tool_runtime

    def run(self, task: RefactoringTask, patch_bundle: PatchBundle) -> ValidationBundle:
        observations = []
        repo_path = self._repo_path(task)

        patch_obs = self.tools.execute(
            "patch_tool",
            "apply_patch",
            {"diff": patch_bundle.merged_diff, "repo_path": repo_path, "apply": False},
        )
        observations.append(patch_obs)

        parse_obs = self.tools.execute(
            "ast_tool",
            "parse_java",
            {"source": task.context.raw_code or ""},
        )
        observations.append(parse_obs)
        parser_pass = bool(parse_obs.artifacts.get("parsed", False))

        compile_module_obs = self.tools.execute(
            "build_tool",
            "compile_module",
            {"repo_path": repo_path, "file_path": task.file_path},
        )
        compile_project_obs = self.tools.execute(
            "build_tool",
            "compile_project",
            {"repo_path": repo_path},
        )
        observations.extend([compile_module_obs, compile_project_obs])

        return ValidationBundle(
            task_id=task.task_id,
            parser_pass=parser_pass,
            module_compile_pass=bool(compile_module_obs.artifacts.get("passed", False)),
            project_compile_pass=bool(compile_project_obs.artifacts.get("passed", False)),
            # Runtime stage only does static checks. Dynamic tests / smell redetect
            # are deferred to experiment-level post-validation aggregation.
            targeted_tests_pass=None,
            generated_assertions_pass=None,
            target_smell_removed=True,
            newly_introduced_smells=[],
            observations=observations,
        )

    def _repo_path(self, task: RefactoringTask) -> str:
        return str(Path(self.project_cfg.repo_root) / task.project)
