from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import yaml

from app.config.settings import settings
from app.models.adapters.base import ModelAdapter
from app.models.adapters.openai_adapter import OpenAICompatibleAdapter

logger = logging.getLogger(__name__)

# Map provider names to API key resolution
_API_KEY_MAP = {
    "qwen": lambda: settings.qwen_api_key,
    "deepseek": lambda: settings.deepseek_api_key,
    "openai": lambda: settings.openai_api_key,
    "gemini": lambda: settings.gemini_api_key,
    "local": lambda: "not-needed",
}

# Default base URLs per provider
_DEFAULT_BASE_URLS = {
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "openai": "https://api.openai.com/v1",
    "local": "http://localhost:8080/v1",
}


def _resolve_api_key(provider: str, api_key_env: str) -> str:
    if api_key_env:
        value = os.environ.get(api_key_env, "")
        if value:
            return value
    key_fn = _API_KEY_MAP.get(provider, lambda: "")
    return key_fn()


class ModelRegistry:
    """Loads model configs from YAML and creates adapters. Supports hot-reload."""

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = str(Path(__file__).parent.parent / "config" / "models.yaml")
        self._config_path = config_path
        self._adapters: dict[str, ModelAdapter] = {}
        self._role_map: dict[str, str] = {}  # role -> adapter_key
        self._last_modified: float = 0

    async def get_adapter(self, role: str) -> ModelAdapter:
        """Get adapter by role (primary / fallback / fast / analyzer)."""
        await self._reload_if_changed()

        # analyzer defaults to fast
        effective_role = role if role in self._role_map else "fast" if role == "analyzer" else "primary"

        key = self._role_map.get(effective_role)
        if not key or key not in self._adapters:
            raise ValueError(f"No model configured for role: {role}")

        return self._adapters[key]

    async def _reload_if_changed(self):
        try:
            mtime = os.path.getmtime(self._config_path)
        except OSError:
            return

        if mtime <= self._last_modified:
            return

        logger.info(f"Reloading model config from {self._config_path}")
        self._last_modified = mtime
        self._adapters.clear()
        self._role_map.clear()

        try:
            with open(self._config_path) as f:
                config = yaml.safe_load(f)

            models = config.get("models", {})
            for role, model_cfg in models.items():
                provider = model_cfg.get("provider", "")
                model_name = model_cfg.get("model", "")

                # Resolve API key
                api_key = _resolve_api_key(provider, model_cfg.get("api_key_env", ""))

                base_url = model_cfg.get("base_url", _DEFAULT_BASE_URLS.get(provider, ""))
                max_tokens = model_cfg.get("max_tokens", 2048)
                temperature = model_cfg.get("temperature", 0.8)

                adapter_key = f"{provider}:{model_name}"

                if adapter_key not in self._adapters:
                    self._adapters[adapter_key] = OpenAICompatibleAdapter(
                        provider=provider,
                        model_name=model_name,
                        api_key=api_key,
                        base_url=base_url,
                        max_tokens=max_tokens,
                        temperature=temperature,
                    )

                self._role_map[role] = adapter_key
                logger.info(f"Model role '{role}' -> {adapter_key}")

        except Exception as e:
            logger.error(f"Failed to load model config: {e}")

    def list_models(self) -> dict[str, str]:
        """Return current role -> model mapping."""
        return dict(self._role_map)
