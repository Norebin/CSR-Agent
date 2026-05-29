"""Configuration loading and ablation profile overlay."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .exceptions import CSRConfigError


class ConfigBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectConfig(ConfigBaseModel):
    data_root: str
    repo_root: str
    graph_root: str
    output_root: str


class TaskSelectionConfig(ConfigBaseModel):
    dataset_split: str = "test"
    smell_types: list[str]
    projects: list[str]
    limit: int | None = None


class ModelsConfig(ConfigBaseModel):
    planner_backend: str
    executor_backend: str
    reviewer_backend: str
    planner_model: str | None = None
    executor_model: str | None = None
    reviewer_model: str | None = None
    temperature: float = 0.2


class LLMApiConfig(ConfigBaseModel):
    enabled: bool = False
    provider: str = "openai_compatible"
    base_url: str = "https://api.chatanywhere.tech/v1"
    endpoint: str = "/chat/completions"
    api_key_env: str = "OPENAI_API_KEY"
    api_key: str | None = None
    timeout_sec: int = 120
    max_retries: int = 2
    use_response_format_json: bool = True
    extra_headers: dict[str, str] = Field(default_factory=dict)


class RetrievalWeights(ConfigBaseModel):
    semantic: float = 0.45
    structure: float = 0.35
    refactor_prior: float = 0.20

    @model_validator(mode="after")
    def validate_non_negative(self) -> "RetrievalWeights":
        for field, value in self.model_dump().items():
            if value < 0:
                raise ValueError(f"retrieval.weights.{field} must be >= 0")
        return self


class RetrievalConfig(ConfigBaseModel):
    enabled: bool = True
    mode: str = "semantic_plus_context_plus_refactor_prior"
    top_n_recall: int = 50
    top_k_evidence: int = 5
    weights: RetrievalWeights = Field(default_factory=RetrievalWeights)
    fallback_on_missing_graph: str = "renormalize_remaining_weights"


class MemoryConfig(ConfigBaseModel):
    semantic_memory: bool = True
    episode_memory: bool = True
    skill_memory: bool = True


class AgentsConfig(ConfigBaseModel):
    planner_orchestrator: bool = True
    method_refactorer: bool = True
    move_refactorer: bool = True
    class_harmonizer: bool = True
    reviewer_verifier: bool = True


class PromptingConfig(ConfigBaseModel):
    strategy: str = "few_shot"
    use_cot: bool = True
    use_react: bool = False
    use_tot: bool = False


class ToolsConfig(ConfigBaseModel):
    git_tool: bool = True
    repo_browser_tool: bool = True
    ast_tool: bool = True
    entity_tracker_tool: bool = True
    patch_tool: bool = True
    build_tool: bool = True
    test_tool: bool = True
    smell_detector_tool: bool = True
    metrics_tool: bool = True


class ToolRuntimeConfig(ConfigBaseModel):
    use_real_tools: bool = True
    default_timeout_sec: int = 600
    git_bin: str = "git"
    maven_bin: str = "mvn"
    maven_wrapper_cmd: str = "mvnw.cmd"
    maven_wrapper_sh: str = "mvnw"
    gradle_bin: str = "gradle"
    gradle_wrapper: str = "gradlew.bat"
    rg_bin: str = "rg"
    java_home: str | None = None
    maven_settings_file: str | None = None
    maven_local_repo: str | None = None
    pmd_command: str | None = None
    designite_command: str | None = None


class ValidationConfig(ConfigBaseModel):
    compile: bool = True
    targeted_tests: bool = False
    generated_assertions: str = "never"
    smell_redetect: bool = True
    max_review_loops: int = 3


class EvaluationConfig(ConfigBaseModel):
    metrics: list[str]
    group_by: list[str]
    save_task_artifacts: bool = True


class PipelineConfig(ConfigBaseModel):
    project: ProjectConfig
    task_selection: TaskSelectionConfig
    models: ModelsConfig
    llm_api: LLMApiConfig = Field(default_factory=LLMApiConfig)
    retrieval: RetrievalConfig
    memory: MemoryConfig
    agents: AgentsConfig
    prompting: PromptingConfig
    tools: ToolsConfig
    tool_runtime: ToolRuntimeConfig = Field(default_factory=ToolRuntimeConfig)
    validation: ValidationConfig
    evaluation: EvaluationConfig
    ablation_profiles: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: Path | str, profile: str | None = None) -> "PipelineConfig":
        raw = _load_yaml(path)
        cfg = cls.model_validate(raw)
        if profile:
            return cfg.with_ablation_profile(profile)
        return cfg

    def with_ablation_profile(self, profile_name: str) -> "PipelineConfig":
        if profile_name not in self.ablation_profiles:
            raise CSRConfigError(f"Ablation profile not found: {profile_name}")
        merged = self.model_dump(mode="python")
        profile_map = self.ablation_profiles[profile_name]
        for key, value in profile_map.items():
            _set_dotted_key(merged, key, value)
        return PipelineConfig.model_validate(merged)


def load_pipeline_config(path: Path | str, profile: str | None = None) -> PipelineConfig:
    """Load the pipeline config and optionally apply one ablation profile."""
    return PipelineConfig.from_yaml(path, profile=profile)


def _load_yaml(path: Path | str) -> dict[str, Any]:
    path_obj = Path(path)
    if not path_obj.exists():
        raise CSRConfigError(f"Config file not found: {path_obj}")
    with path_obj.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise CSRConfigError("Config root must be a mapping")
    return data


def deep_merge_dict(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deep merge dictionaries and return a new object."""
    result = deepcopy(base)
    for key, value in overlay.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = deep_merge_dict(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _set_dotted_key(target: dict[str, Any], dotted_key: str, value: Any) -> None:
    """Set keys like 'retrieval.mode' in nested dictionaries."""
    parts = dotted_key.split(".")
    node: dict[str, Any] = target
    for part in parts[:-1]:
        if part not in node or not isinstance(node[part], dict):
            node[part] = {}
        node = node[part]
    node[parts[-1]] = value
