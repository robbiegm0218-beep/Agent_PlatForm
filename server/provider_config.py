"""Validated configuration for optional OpenAI-compatible model providers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse


_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_ENV_VAR_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")


@dataclass(frozen=True)
class ProviderConfig:
    provider_id: str
    display_name: str
    api_key_env: str
    base_url: str
    models: tuple[str, ...]


def _valid_id(value: object) -> bool:
    return isinstance(value, str) and bool(_ID_PATTERN.fullmatch(value))


def _require_https_url(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("base_url must be an HTTPS URL")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("base_url must be an HTTPS URL")
    return value.rstrip("/")


def parse_provider_configs(raw: str) -> list[ProviderConfig]:
    """Parse ``AGENT_MODEL_PROVIDERS`` without resolving or exposing secrets.

    Example: ``[{\"provider_id\": \"openai\", \"api_key_env\": \"OPENAI_API_KEY\",
    \"base_url\": \"https://api.openai.com/v1\", \"models\": [\"gpt-4.1\"]}]``.
    """
    if not raw or not raw.strip():
        return []
    try:
        records = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("AGENT_MODEL_PROVIDERS must be valid JSON") from exc
    if not isinstance(records, list):
        raise ValueError("AGENT_MODEL_PROVIDERS must be a JSON list")

    configs: list[ProviderConfig] = []
    seen_ids: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("each provider configuration must be an object")
        provider_id = record.get("provider_id")
        display_name = record.get("display_name")
        api_key_env = record.get("api_key_env")
        models = record.get("models")
        if not _valid_id(provider_id):
            raise ValueError("provider_id is invalid")
        if provider_id in seen_ids:
            raise ValueError(f"duplicate provider_id {provider_id!r}")
        if not isinstance(display_name, str) or not display_name.strip():
            raise ValueError("display_name must be non-empty")
        if not isinstance(api_key_env, str) or not _ENV_VAR_PATTERN.fullmatch(api_key_env):
            raise ValueError("api_key_env must be an uppercase environment-variable name")
        if not isinstance(models, list) or not models or not all(_valid_id(model) for model in models):
            raise ValueError("models must be a non-empty list of valid model ids")
        if len(set(models)) != len(models):
            raise ValueError("models must not contain duplicates")
        configs.append(ProviderConfig(provider_id, display_name.strip(), api_key_env, _require_https_url(record.get("base_url")), tuple(models)))
        seen_ids.add(provider_id)
    return configs
