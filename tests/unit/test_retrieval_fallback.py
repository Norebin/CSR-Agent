from __future__ import annotations

from csr_agent.kb import RCKBBuilder
from csr_agent.retrieval import RetrievalEngine
from conftest import make_task


def test_retrieval_renormalizes_when_graph_missing(test_config, workspace_tmp_root):
    train_task = make_task(task_id="train1", split="train", graph_available=True)
    store = RCKBBuilder().build_and_persist(
        [train_task], output_dir=workspace_tmp_root / "unit_rckb"
    )

    query_task = make_task(task_id="query1", graph_available=False)
    pack = RetrievalEngine().retrieve(query_task, store, test_config.retrieval)
    assert pack.items
    assert any("weights renormalized" in note for note in pack.notes)
