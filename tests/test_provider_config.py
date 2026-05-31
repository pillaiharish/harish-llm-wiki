"""Tests for provider configuration behavior."""

from wiki.config import Config


def test_ollama_api_key_alias_is_preferred(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama_cloud")
    monkeypatch.setenv("OLLAMA_API_KEY", "preferred-key")
    monkeypatch.setenv("OLLAMA_CLOUD_API_KEY", "legacy-key")
    monkeypatch.setenv("OLLAMA_CLOUD_MODEL", "qwen")

    cfg = Config()

    assert cfg.OLLAMA_CLOUD_API_KEY == "preferred-key"
    assert cfg.validate() == []


def test_legacy_ollama_cloud_api_key_still_supported(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama_cloud")
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.setenv("OLLAMA_CLOUD_API_KEY", "legacy-key")
    monkeypatch.setenv("OLLAMA_CLOUD_MODEL", "qwen")

    cfg = Config()

    assert cfg.OLLAMA_CLOUD_API_KEY == "legacy-key"
    assert cfg.validate() == []
