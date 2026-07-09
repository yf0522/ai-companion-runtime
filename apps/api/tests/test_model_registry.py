from __future__ import annotations

import pytest

from app.models import registry
from app.models.registry import ModelRegistry


@pytest.mark.asyncio
async def test_model_registry_falls_back_to_settings_api_key(tmp_path, monkeypatch):
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        """
models:
  fast:
    provider: "qwen"
    model: "qwen-turbo"
    api_key_env: "QWEN_API_KEY"
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
""",
    )
    captured: dict[str, object] = {}

    class FakeAdapter:
        def __init__(
            self,
            provider: str,
            model_name: str,
            api_key: str,
            base_url: str,
            max_tokens: int = 2048,
            temperature: float = 0.8,
        ) -> None:
            captured["provider"] = provider
            captured["model_name"] = model_name
            captured["api_key"] = api_key
            captured["base_url"] = base_url

    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.setattr(registry.settings, "qwen_api_key", "settings-qwen-key")
    monkeypatch.setattr(registry, "OpenAICompatibleAdapter", FakeAdapter)

    model_registry = ModelRegistry(str(config_path))
    adapter = await model_registry.get_adapter("fast")

    assert isinstance(adapter, FakeAdapter)
    assert captured["provider"] == "qwen"
    assert captured["model_name"] == "qwen-turbo"
    assert captured["api_key"] == "settings-qwen-key"
