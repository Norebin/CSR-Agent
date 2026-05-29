from __future__ import annotations

from csr_agent.agents import AgentContext, MethodRefactorerAgent
from csr_agent.config import PromptingConfig
from csr_agent.logging import StructuredLogger
from csr_agent.memory import MemoryManager
from csr_agent.tools import build_default_tool_registry


def test_prompting_strategy_is_applied():
    agent = MethodRefactorerAgent()
    ctx = AgentContext(
        tool_registry=build_default_tool_registry(),
        memory_manager=MemoryManager(None, None, None),
        logger=StructuredLogger(),
        prompting=PromptingConfig(
            strategy="one_shot",
            use_cot=False,
            use_react=True,
            use_tot=True,
        ),
    )
    prompt = agent.apply_prompting_strategy(ctx, "core prompt")
    assert "one-shot style" in prompt
    assert "tool-aware reasoning" in prompt
    assert "multiple candidate plans" in prompt
