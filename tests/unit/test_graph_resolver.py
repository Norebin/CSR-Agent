from __future__ import annotations

import zipfile
from pathlib import Path

from conftest import make_task
from csr_agent.resolver import GraphResolver


def test_graph_resolver_extracts_graphml_from_project_zip(workspace_tmp_root):
    graph_root = workspace_tmp_root / "graph_data"
    project_dir = graph_root / "demo"
    project_dir.mkdir(parents=True, exist_ok=True)
    zip_path = project_dir / "demo-1.0.0.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("nested/demo-t1.graphml", "<graphml></graphml>")

    task = make_task(task_id="t1", graph_available=False)
    task.version.version_hint = "1.0.0"
    resolver = GraphResolver(graph_root=graph_root, cache_root=workspace_tmp_root / "cache")
    resolved = resolver.resolve(task)

    assert resolved.graph_available is True
    assert resolved.graph_context_path is not None
    assert Path(resolved.graph_context_path).exists()
    assert resolved.source_zip is not None


def test_graph_resolver_gracefully_handles_missing_graph(workspace_tmp_root):
    graph_root = workspace_tmp_root / "graph_data"
    graph_root.mkdir(parents=True, exist_ok=True)
    task = make_task(task_id="t_missing", graph_available=False)
    resolver = GraphResolver(graph_root=graph_root, cache_root=workspace_tmp_root / "cache")
    resolved = resolver.resolve(task)

    assert resolved.graph_available is False
    assert resolved.graph_context_path is None
    assert resolved.recoverable is True
