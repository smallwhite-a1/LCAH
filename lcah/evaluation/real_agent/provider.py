"""Safe DeepSeek client construction for real evaluation runs."""

from __future__ import annotations

from ...config import resolve_provider_config
from ...providers import AnthropicCompatibleModelClient

FLASH_MODEL = "deepseek-v4-flash"


class ProviderConfigurationError(ValueError):
    pass


def build_deepseek_client(*, start=".", model=None, base_url=None, api_key=None,
                          temperature=0.0, timeout=300):
    config = resolve_provider_config("deepseek", start=start, model=model,
                                     base_url=base_url, api_key=api_key)
    if config.model != FLASH_MODEL:
        raise ProviderConfigurationError(f"real evaluation requires model {FLASH_MODEL}")
    if not config.api_key:
        raise ProviderConfigurationError("DeepSeek API key is not configured")
    if config.protocol != "anthropic":
        raise ProviderConfigurationError("DeepSeek evaluation requires anthropic protocol")
    client = AnthropicCompatibleModelClient(config.model, config.base_url, config.api_key,
                                            temperature, timeout)
    metadata = {"provider": "deepseek", "protocol": config.protocol, "model": config.model,
                "base_url_configured": bool(config.base_url), "temperature": temperature,
                "timeout_seconds": timeout, "api_key_configured": True}
    return client, metadata
