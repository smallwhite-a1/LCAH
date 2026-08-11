import json

import pytest

from lcah.evaluation.real_agent.provider import (
    ProviderConfigurationError,
    build_deepseek_client,
)


def test_deepseek_factory_uses_flash_and_never_serializes_key():
    client, metadata = build_deepseek_client(
        start=".", model="deepseek-v4-flash", base_url="https://api.deepseek.com/anthropic",
        api_key="secret-value", temperature=0.0, timeout=300,
    )
    assert client.model == "deepseek-v4-flash"
    assert metadata["model"] == "deepseek-v4-flash"
    assert "secret-value" not in json.dumps(metadata)


def test_deepseek_factory_rejects_wrong_model_and_missing_key(tmp_path):
    with pytest.raises(ProviderConfigurationError, match="deepseek-v4-flash"):
        build_deepseek_client(start=".", model="deepseek-v4-pro", api_key="key")
    with pytest.raises(ProviderConfigurationError, match="API key"):
        build_deepseek_client(start=tmp_path, model="deepseek-v4-flash", api_key="")
