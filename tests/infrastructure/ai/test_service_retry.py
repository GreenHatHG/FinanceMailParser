from __future__ import annotations

from types import SimpleNamespace

import tenacity.nap

import financemailparser.infrastructure.ai.service as service_module
from financemailparser.infrastructure.ai.service import AIService


def _make_dummy_response(content: str) -> SimpleNamespace:
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    usage = SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3)
    return SimpleNamespace(choices=[choice], usage=usage)


class _FakeAiConfig:
    def __init__(self, *, max_retries: int, retry_interval: int):
        self.provider = "openai"
        self.model = "gpt-4o-mini"
        self.max_retries = int(max_retries)
        self.retry_interval = int(retry_interval)

    def to_litellm_completion_kwargs(self, *, messages: list[dict], **extra):
        # Only fields needed by our mocked `litellm.completion` in tests.
        return {"messages": messages, **extra}


class _FakeConfigManager:
    def __init__(self, *, max_retries: int, retry_interval: int):
        self._cfg = _FakeAiConfig(
            max_retries=max_retries, retry_interval=retry_interval
        )

    def load_config_strict(self) -> _FakeAiConfig:
        return self._cfg


def test_call_completion_retries_on_any_exception(monkeypatch):
    # Avoid real sleeps during retry loops.
    monkeypatch.setattr(tenacity.nap.time, "sleep", lambda _seconds: None)

    calls: dict[str, int] = {"n": 0}

    def fake_completion(**_kwargs):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise ValueError("boom")
        return _make_dummy_response("ok")

    monkeypatch.setattr(service_module.litellm, "completion", fake_completion)

    service = AIService(_FakeConfigManager(max_retries=2, retry_interval=1))
    stats = service.call_completion("hello")

    assert stats.success is True
    assert stats.response == "ok"
    assert stats.retry_count == 2
    assert calls["n"] == 3


def test_call_completion_stops_after_max_retries(monkeypatch):
    monkeypatch.setattr(tenacity.nap.time, "sleep", lambda _seconds: None)

    calls: dict[str, int] = {"n": 0}

    def fake_completion(**_kwargs):
        calls["n"] += 1
        raise RuntimeError("nope")

    monkeypatch.setattr(service_module.litellm, "completion", fake_completion)

    service = AIService(_FakeConfigManager(max_retries=2, retry_interval=1))
    stats = service.call_completion("hello")

    assert stats.success is False
    assert stats.retry_count == 2
    assert calls["n"] == 3
    assert "nope" in (stats.error_message or "")
