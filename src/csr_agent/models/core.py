"""Pydantic models shared across the whole pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CSRBaseModel(BaseModel):
    """Base model with strict field handling and stable JSON output."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=False)


class SmellType(str, Enum):
    LONG_METHOD = "LongMethod"
    COMPLEX_METHOD = "ComplexMethod"
    LONG_PARAMETER_LIST = "LongParameterList"
    FEATURE_ENVY = "FeatureEnvy"


class ReviewDecision(str, Enum):
    ACCEPT = "accept"
    RETRY = "retry"
    FAIL = "fail"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskState(str, Enum):
    TASK_LOADED = "task_loaded"
    VERSION_RESOLVED = "version_resolved"
    ENTITY_LOCATED = "entity_located"
    EVIDENCE_RETRIEVED = "evidence_retrieved"
    PLAN_GENERATED = "plan_generated"
    PATCH_GENERATED = "patch_generated"
    PATCH_INTEGRATED = "patch_integrated"
    STATIC_VALIDATED = "static_validated"
    DYNAMIC_VALIDATED = "dynamic_validated"
    SMELL_RECHECKED = "smell_rechecked"
    REVIEWED = "reviewed"
    ACCEPTED = "accepted"
    REPLAN = "replan"
    FAILED = "failed"


class VersionInfo(CSRBaseModel):
    version_hint: str | None = None
    begin_tag: str | None = None
    end_tag: str | None = None
    disappear_tag: str | None = None
    resolved_begin_tag: str | None = None
    resolved_disappear_tag: str | None = None


class LocationInfo(CSRBaseModel):
    package_name: str | None = None
    type_name: str | None = None
    method_name: str | None = None
    file_path: str


class TaskContext(CSRBaseModel):
    raw_code: str | None = None
    comment: str | None = None
    diff: str | None = None
    commit_history: str | list[str] | None = None
    refactorings: str | list[str] | None = None
    graph_context_path: str | None = None
    graph_available: bool = False


class RefactoringTask(CSRBaseModel):
    task_id: str
    dataset_split: Literal["train", "test"] | None = None
    project: str
    version: VersionInfo
    location: LocationInfo | None = None
    file_path: str
    smell_type: SmellType
    smell_metadata: dict[str, Any] = Field(default_factory=dict)
    context: TaskContext
    expected_outputs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def ensure_location_defaults(self) -> "RefactoringTask":
        if self.location is None:
            self.location = LocationInfo(file_path=self.file_path)
        return self


class EntityCandidate(CSRBaseModel):
    entity_id: str
    file_path: str | None = None
    method_signature: str | None = None
    score: float
    rationale: str


class EntityMapping(CSRBaseModel):
    anchored: bool
    best_match: EntityCandidate | None = None
    alternatives: list[EntityCandidate] = Field(default_factory=list)
    confidence: float = 0.0
    mapping_rationale: str = ""
    recoverable: bool = True


class EvidenceItem(CSRBaseModel):
    case_id: str
    source_project: str
    smell_type: SmellType
    score: float
    semantic_score: float = 0.0
    structure_score: float = 0.0
    refactor_prior_score: float = 0.0
    payload: dict[str, Any] = Field(default_factory=dict)


class EvidencePack(CSRBaseModel):
    task_id: str
    retrieval_mode: str
    graph_available: bool
    items: list[EvidenceItem] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PlanNode(CSRBaseModel):
    node_id: str
    kind: str
    description: str
    required_tools: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlanEdge(CSRBaseModel):
    source: str
    target: str
    edge_type: Literal[
        "serial",
        "parallel",
        "conditional_on_failure",
        "conditional_on_smell_type",
    ] = "serial"


class PlanGraph(CSRBaseModel):
    task_summary: str
    smell_diagnosis: str
    risk_assessment: str
    selected_agents: list[str]
    execution_order: list[str]
    required_tools: list[str]
    stop_conditions: list[str]
    acceptance_criteria: list[str]
    nodes: list[PlanNode] = Field(default_factory=list)
    edges: list[PlanEdge] = Field(default_factory=list)


class PatchProposal(CSRBaseModel):
    agent_name: str
    proposed_refactor_actions: list[str]
    unified_diff: str
    rationale: str
    expected_smell_effect: str | None = None
    possible_side_effects: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PatchBundle(CSRBaseModel):
    task_id: str
    merged_diff: str
    proposals: list[PatchProposal] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class ToolObservation(CSRBaseModel):
    tool_name: str
    operation: str
    status: Literal["ok", "degraded", "error"]
    error_code: str | None = None
    message: str = ""
    artifacts: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class ValidationBundle(CSRBaseModel):
    task_id: str
    parser_pass: bool = False
    module_compile_pass: bool = False
    project_compile_pass: bool = False
    targeted_tests_pass: bool | None = None
    generated_assertions_pass: bool | None = None
    target_smell_removed: bool = False
    newly_introduced_smells: list[dict[str, Any]] = Field(default_factory=list)
    observations: list[ToolObservation] = Field(default_factory=list)


class ReviewLocation(CSRBaseModel):
    file_path: str | None = None
    class_name: str | None = None
    method_name: str | None = None
    line_span: str | None = None


class ReviewFeedback(CSRBaseModel):
    task_id: str
    decision: ReviewDecision
    failure_stage: Literal[
        "entity_location",
        "retrieval",
        "patch_generation",
        "patch_merge",
        "static_validation",
        "dynamic_validation",
        "smell_redetect",
        "review",
    ]
    symptom: str
    location: ReviewLocation | None = None
    risk_level: RiskLevel
    suggested_fix: str = ""
    should_retry: bool
    recommended_agent: str | None = None
    forbidden_actions_next_round: list[str] = Field(default_factory=list)
    tool_observations: list[ToolObservation] = Field(default_factory=list)


class AgentMessage(CSRBaseModel):
    task_id: str
    agent_name: str
    input_payload: dict[str, Any] = Field(default_factory=dict)
    output_payload: dict[str, Any] = Field(default_factory=dict)


class MetricsRecord(CSRBaseModel):
    task_id: str
    smell_type: SmellType
    srr: float
    csr: float
    binary_sir: float
    count_sir: float
    assertion_pass_rate: float | None = None
    token_cost: float = 0.0
    time_cost: float = 0.0
    codebleu: float | None = None
    loop_count: int = 0
    extra: dict[str, Any] = Field(default_factory=dict)


class TaskResult(CSRBaseModel):
    task_id: str
    project: str
    smell_type: SmellType
    final_state: TaskState
    accepted: bool
    loop_count: int
    evidence_pack: EvidencePack | None = None
    plan: PlanGraph | None = None
    patch_bundle: PatchBundle | None = None
    review_feedback: ReviewFeedback | None = None
    validation: ValidationBundle | None = None
    metrics: MetricsRecord | None = None
    warnings: list[str] = Field(default_factory=list)


class RefactoringCase(CSRBaseModel):
    case_id: str
    unique_id: str
    project: str
    smell_type: SmellType
    source_snippet: str
    target_snippet_candidates: list[str] = Field(default_factory=list)
    refactor_action_sequence: list[str] = Field(default_factory=list)
    context_summary: dict[str, Any] = Field(default_factory=dict)
    mapping_confidence: float = 0.0
    data_noise_flags: list[str] = Field(default_factory=list)
    code_embedding: list[float] = Field(default_factory=list)
    context_embedding: list[float] = Field(default_factory=list)
    refactor_pattern_embedding: list[float] = Field(default_factory=list)


class ExperimentReport(CSRBaseModel):
    experiment_id: str
    profile_name: str | None = None
    total_tasks: int
    accepted_tasks: int
    failed_tasks: int
    aggregated_metrics: dict[str, Any] = Field(default_factory=dict)
    task_results: list[TaskResult] = Field(default_factory=list)
    artifacts_root: str
