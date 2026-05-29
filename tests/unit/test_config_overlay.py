from __future__ import annotations

from csr_agent.config import load_pipeline_config


def test_apply_ablation_profile(config_template_path):
    cfg = load_pipeline_config(config_template_path, profile="rq4_loop_1")
    assert cfg.validation.max_review_loops == 1


def test_overlay_turns_off_move_agent(config_template_path):
    cfg = load_pipeline_config(config_template_path, profile="rq3_no_move_agent")
    assert cfg.agents.move_refactorer is False
