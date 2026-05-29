"""OpenAI-compatible LLM client with structured JSON output."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from csr_agent.config import LLMApiConfig, ModelsConfig
from csr_agent.exceptions import CSRConfigError


RoleName = Literal["planner", "executor", "reviewer"]


@dataclass(slots=True)
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMClient(Protocol):
    def generate_json(
        self,
        *,
        role: RoleName,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], LLMUsage]:
        """Generate one JSON object for the requested role."""


class OpenAICompatibleLLMClient:
    """HTTP client for OpenAI-compatible chat completion APIs."""

    def __init__(self, models: ModelsConfig, api: LLMApiConfig) -> None:
        self.models = models
        self.api = api

    def generate_json(
        self,
        *,
        role: RoleName,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], LLMUsage]:
        api_key = self.api.api_key or os.getenv(self.api.api_key_env)
        if not api_key:
            raise CSRConfigError(
                f"LLM API enabled but key missing. Set llm_api.api_key or env {self.api.api_key_env}."
            )

        model_name = _pick_model(self.models, role)
        url = f"{self.api.base_url.rstrip('/')}/{self.api.endpoint.lstrip('/')}"
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.models.temperature,
        }
        if self.api.use_response_format_json:
            payload["response_format"] = {"type": "json_object"}

        if schema:
            payload["messages"][0]["content"] += (
                "\n\nReturn only one JSON object that conforms to this JSON Schema:\n"
                f"{json.dumps(schema, ensure_ascii=False)}"
            )

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        headers.update(self.api.extra_headers)

        max_attempts = max(1, self.api.max_retries + 1)
        last_error: Exception | None = None
        for attempt in range(max_attempts):
            try:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                req = urllib.request.Request(url=url, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=self.api.timeout_sec) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                return _parse_chat_completion_response(raw)
            except urllib.error.HTTPError as exc:
                response_text = exc.read().decode("utf-8", errors="replace")
                # Some compatible providers do not support response_format.
                if (
                    self.api.use_response_format_json
                    and "response_format" in response_text.lower()
                    and "unsupported" in response_text.lower()
                ):
                    payload.pop("response_format", None)
                last_error = CSRConfigError(
                    f"LLM API HTTP {exc.code}: {response_text[:1200]}"
                )
                if exc.code >= 500 and attempt < max_attempts - 1:
                    continue
                break
            except urllib.error.URLError as exc:
                last_error = CSRConfigError(f"LLM API network error: {exc}")
                if attempt < max_attempts - 1:
                    continue
                break
            except Exception as exc:  # pragma: no cover - defensive safety
                last_error = exc
                break
        assert last_error is not None
        raise last_error


def build_llm_client(models: ModelsConfig, api: LLMApiConfig) -> LLMClient | None:
    """Build the configured LLM client. Returns None when disabled."""
    if not api.enabled:
        return None
    if api.provider != "openai_compatible":
        raise CSRConfigError(f"Unsupported llm_api.provider: {api.provider}")
    return OpenAICompatibleLLMClient(models=models, api=api)


def _pick_model(models: ModelsConfig, role: RoleName) -> str:
    if role == "planner":
        return models.planner_model or models.planner_backend
    if role == "reviewer":
        return models.reviewer_model or models.reviewer_backend
    return models.executor_model or models.executor_backend


def _parse_chat_completion_response(raw: str) -> tuple[dict[str, Any], LLMUsage]:
    data = json.loads(raw)
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise CSRConfigError("LLM API response has no choices.")

    message = choices[0].get("message", {})
    content = message.get("content")
    text = _normalize_content_text(content)
    parsed = _parse_json_from_text(text)

    usage_dict = data.get("usage") or {}
    usage = LLMUsage(
        prompt_tokens=int(usage_dict.get("prompt_tokens", 0) or 0),
        completion_tokens=int(usage_dict.get("completion_tokens", 0) or 0),
        total_tokens=int(usage_dict.get("total_tokens", 0) or 0),
    )
    return parsed, usage


def _normalize_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item.get("content"), str):
                    parts.append(item["content"])
        return "\n".join(parts)
    return str(content)


def _parse_json_from_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise CSRConfigError("LLM response content is empty.")

    # Direct parse first.
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    # Parse fenced JSON blocks: ```json ... ```
    block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.S | re.I)
    if block_match:
        parsed = json.loads(block_match.group(1))
        if isinstance(parsed, dict):
            return parsed

    # Parse first top-level JSON object slice.
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        parsed = json.loads(stripped[start : end + 1])
        if isinstance(parsed, dict):
            return parsed

    raise CSRConfigError("LLM response is not a valid JSON object.")
