from __future__ import annotations

from csr_agent.resolver import EntityTracker, VersionResolver
from conftest import make_task


def test_version_resolver_ranks_candidates():
    task = make_task()
    task.version.begin_tag = "v1.2.0"
    resolver = VersionResolver()
    out = resolver.resolve(task, tags=["v1.0.0", "v1.2.1", "release-2"])
    assert out["resolved_begin_tag"] == "v1.2.1"
    assert out["confidence"] > 0


def test_entity_tracker_returns_best_match():
    task = make_task()
    tracker = EntityTracker()
    mapping = tracker.track(
        task,
        tracked_candidates=[
            {"method_signature": "compute", "file_path": "src/DemoClass.java"},
            {"method_signature": "other", "file_path": "src/Other.java"},
        ],
    )
    assert mapping.anchored is True
    assert mapping.best_match is not None
    assert mapping.best_match.method_signature == "compute"
