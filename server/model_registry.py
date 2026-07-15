"""Deterministic, secret-free model provider and model registry."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterator


_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
_ENV_VAR_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_TASK_TIERS = {"quick", "standard", "deep"}


def _validate_id(value: str, label: str) -> None:
    if not value or not _ID_PATTERN.fullmatch(value):
        raise ValueError(f"invalid {label}: use 1-64 alphanumeric, dot, underscore, or hyphen characters")


@dataclass(frozen=True)
class ModelCapabilities:
    streaming: bool = False
    tool_calling: bool = False
    vision: bool = False
    structured_output: bool = False


@dataclass(frozen=True)
class ProviderInfo:
    """A provider descriptor holding an environment-variable name, never its secret."""

    provider_id: str
    display_name: str
    env_var: str
    base_url: str | None = None

    def __post_init__(self) -> None:
        _validate_id(self.provider_id, "provider_id")
        if not self.display_name.strip():
            raise ValueError("display_name must be non-empty")
        if not _ENV_VAR_PATTERN.fullmatch(self.env_var):
            raise ValueError("env_var must be an uppercase environment-variable name, not a secret")


@dataclass(frozen=True)
class ModelInfo:
    provider_id: str
    model_id: str
    display_name: str
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    task_tier: str = "standard"
    enabled: bool = True
    context_window: int | None = None
    max_output_tokens: int | None = None

    @property
    def key(self) -> tuple[str, str]:
        return self.provider_id, self.model_id

    def __post_init__(self) -> None:
        _validate_id(self.provider_id, "provider_id")
        _validate_id(self.model_id, "model_id")
        if not self.display_name.strip():
            raise ValueError("display_name must be non-empty")
        if self.task_tier not in _TASK_TIERS:
            raise ValueError("task_tier must be quick, standard, or deep")
        if self.context_window is not None and self.context_window <= 0:
            raise ValueError("context_window must be positive")
        if self.max_output_tokens is not None and self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")


class ModelRegistry:
    """In-memory registry with deterministic insertion-order listing."""

    def __init__(self) -> None:
        self._providers: dict[str, ProviderInfo] = {}
        self._models: dict[tuple[str, str], ModelInfo] = {}

    def register_provider(self, provider: ProviderInfo) -> None:
        if provider.provider_id in self._providers:
            raise ValueError(f"duplicate provider_id {provider.provider_id!r}")
        self._providers[provider.provider_id] = provider

    def get_provider(self, provider_id: str) -> ProviderInfo | None:
        return self._providers.get(provider_id)

    def list_providers(self) -> list[ProviderInfo]:
        return list(self._providers.values())

    def register_model(self, model: ModelInfo) -> None:
        if model.provider_id not in self._providers:
            raise ValueError(f"unknown provider_id {model.provider_id!r}")
        if model.key in self._models:
            raise ValueError(f"duplicate model {model.provider_id!r}/{model.model_id!r}")
        self._models[model.key] = model

    def lookup(self, provider_id: str, model_id: str) -> ModelInfo | None:
        return self._models.get((provider_id, model_id))

    def list_models(self, provider_id: str | None = None, enabled_only: bool = True) -> list[ModelInfo]:
        models: Iterator[ModelInfo] = iter(self._models.values())
        if provider_id is not None:
            models = (model for model in models if model.provider_id == provider_id)
        if enabled_only:
            models = (model for model in models if model.enabled)
        return list(models)
