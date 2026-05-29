"""Task execution state machine."""

from __future__ import annotations

from dataclasses import dataclass

from csr_agent.models import TaskState


VALID_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.TASK_LOADED: {TaskState.VERSION_RESOLVED, TaskState.FAILED},
    TaskState.VERSION_RESOLVED: {TaskState.ENTITY_LOCATED, TaskState.FAILED},
    TaskState.ENTITY_LOCATED: {TaskState.EVIDENCE_RETRIEVED, TaskState.FAILED},
    TaskState.EVIDENCE_RETRIEVED: {TaskState.PLAN_GENERATED, TaskState.FAILED},
    TaskState.PLAN_GENERATED: {TaskState.PATCH_GENERATED, TaskState.FAILED},
    TaskState.PATCH_GENERATED: {TaskState.PATCH_INTEGRATED, TaskState.FAILED},
    TaskState.PATCH_INTEGRATED: {TaskState.STATIC_VALIDATED, TaskState.FAILED},
    TaskState.STATIC_VALIDATED: {TaskState.DYNAMIC_VALIDATED, TaskState.FAILED},
    TaskState.DYNAMIC_VALIDATED: {TaskState.SMELL_RECHECKED, TaskState.FAILED},
    TaskState.SMELL_RECHECKED: {TaskState.REVIEWED, TaskState.FAILED},
    TaskState.REVIEWED: {TaskState.ACCEPTED, TaskState.REPLAN, TaskState.FAILED},
    TaskState.REPLAN: {TaskState.PLAN_GENERATED, TaskState.FAILED},
}


@dataclass
class TaskStateMachine:
    current: TaskState = TaskState.TASK_LOADED

    def transition(self, target: TaskState) -> None:
        allowed = VALID_TRANSITIONS.get(self.current, set())
        if target not in allowed:
            raise ValueError(f"Invalid transition: {self.current.value} -> {target.value}")
        self.current = target
