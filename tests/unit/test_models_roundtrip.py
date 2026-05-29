from __future__ import annotations

from csr_agent.models import ReviewDecision, ReviewFeedback, RiskLevel
from conftest import make_task


def test_refactoring_task_roundtrip():
    task = make_task()
    payload = task.to_json_dict()
    restored = task.__class__.model_validate(payload)
    assert restored.task_id == task.task_id
    assert restored.smell_type == task.smell_type


def test_review_feedback_roundtrip():
    feedback = ReviewFeedback(
        task_id="t1",
        decision=ReviewDecision.ACCEPT,
        failure_stage="review",
        symptom="ok",
        risk_level=RiskLevel.LOW,
        should_retry=False,
    )
    payload = feedback.to_json_dict()
    restored = ReviewFeedback.model_validate(payload)
    assert restored.decision == ReviewDecision.ACCEPT
