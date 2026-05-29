from __future__ import annotations

from pathlib import Path

from csr_agent.config import load_pipeline_config
from csr_agent.runner.rq_suite import apply_overrides, load_rq_suite_config


def test_load_rq_suite_config():
    cfg = load_rq_suite_config(Path("configs/rq_suite.template.yaml"))
    assert len(cfg.rq1.methods) >= 3
    assert any(m.name == "gpt-5.2" for m in cfg.rq1.methods)


def test_apply_overrides_on_pipeline_config(config_template_path):
    base = load_pipeline_config(config_template_path)
    updated = apply_overrides(
        base,
        {
            "llm_api.enabled": True,
            "models.planner_model": "gpt-5.2",
            "tools.git_tool": False,
        },
    )
    assert updated.llm_api.enabled is True
    assert updated.models.planner_model == "gpt-5.2"
    assert updated.tools.git_tool is False
