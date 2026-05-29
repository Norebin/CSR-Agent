from __future__ import annotations

import pytest

from csr_agent.models import TaskState
from csr_agent.orchestration import TaskStateMachine


def test_state_machine_valid_path():
    machine = TaskStateMachine()
    machine.transition(TaskState.VERSION_RESOLVED)
    machine.transition(TaskState.ENTITY_LOCATED)
    machine.transition(TaskState.EVIDENCE_RETRIEVED)
    machine.transition(TaskState.PLAN_GENERATED)
    assert machine.current == TaskState.PLAN_GENERATED


def test_state_machine_invalid_transition():
    machine = TaskStateMachine()
    with pytest.raises(ValueError):
        machine.transition(TaskState.REVIEWED)
