from __future__ import annotations

import json

from csr_agent.config import LLMApiConfig, ModelsConfig
from csr_agent.llm import OpenAICompatibleLLMClient


class _DummyHTTPResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_openai_compatible_client_parses_json(monkeypatch):
    models = ModelsConfig(
        planner_backend="llm_api",
        executor_backend="llm_api",
        reviewer_backend="llm_api",
        planner_model="gpt-4.1-mini",
        executor_model="gpt-4.1-mini",
        reviewer_model="gpt-4.1-mini",
    )
    api = LLMApiConfig(enabled=True, api_key_env="UT_API_KEY")
    client = OpenAICompatibleLLMClient(models=models, api=api)

    monkeypatch.setenv("UT_API_KEY", "dummy")

    def fake_urlopen(req, timeout):  # noqa: ANN001
        body = json.loads(req.data.decode("utf-8"))
        assert body["model"] == "gpt-4.1-mini"
        assert body["response_format"]["type"] == "json_object"
        return _DummyHTTPResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"task_summary":"ok","smell_diagnosis":"x","risk_assessment":"low","selected_agents":["method_refactorer"],"execution_order":["planner_orchestrator","method_refactorer"],"required_tools":[],"stop_conditions":[],"acceptance_criteria":[],"nodes":[],"edges":[]}'
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 7,
                    "total_tokens": 18,
                },
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    output, usage = client.generate_json(
        role="planner",
        system_prompt="sys",
        user_prompt="usr",
    )
    assert output["task_summary"] == "ok"
    assert usage.total_tokens == 18
