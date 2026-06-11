"""Prompt 52D local provider/model control-plane checks."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from typer.testing import CliRunner

import wiki.cli as cli
from wiki import control_plane


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "http://example.test/models")
            response = httpx.Response(self.status_code, request=request, text=self.text)
            raise httpx.HTTPStatusError("boom", request=request, response=response)


def test_control_plane_cli_defaults_and_rejects_lan_without_flag(monkeypatch):
    runner = CliRunner()
    started: dict[str, object] = {}

    def fake_serve_control_plane(*, host: str, port: int) -> None:
        started["host"] = host
        started["port"] = port

    monkeypatch.setattr(cli, "serve_control_plane", fake_serve_control_plane)

    result = runner.invoke(cli.app, ["control-plane"])
    assert result.exit_code == 0
    assert started == {"host": "127.0.0.1", "port": 8765}

    rejected = runner.invoke(cli.app, ["control-plane", "--host", "0.0.0.0"])
    assert rejected.exit_code == 1
    assert "Refusing non-loopback bind" in rejected.output


def test_redaction_removes_secret_like_values(monkeypatch):
    monkeypatch.setattr(control_plane.config, "OPENAI_COMPATIBLE_API_KEY", "sk-test-secret")
    monkeypatch.setattr(control_plane.config, "OPENAI_COMPATIBLE_BASE_URL", "https://secret.example")

    payload = {
        "message": "Authorization: Bearer sk-test-secret against https://secret.example",
        "nested": {"api_key": "sk-test-secret", "token": "abc123"},
    }

    redacted = json.dumps(control_plane.redact_payload(payload))
    assert "sk-test-secret" not in redacted
    assert "https://secret.example" not in redacted
    assert "[redacted]" in redacted


def test_mock_provider_check_is_metadata_only_and_available():
    result = control_plane.check_provider("mock")

    assert result["ok"] is True
    assert result["connectivity"] == "ok"
    assert result["keyPresent"] is False
    assert result["availableModels"] == ["mock-model"]
    assert result["modelAvailable"] is True


def test_ollama_local_check_uses_tags_metadata_endpoint(monkeypatch):
    calls: list[str] = []

    def fake_get(url: str, **kwargs):
        calls.append(url)
        return FakeResponse({"models": [{"name": "qwen2.5:7b"}, {"name": "llama3"}]})

    monkeypatch.setattr(control_plane.httpx, "get", fake_get)
    monkeypatch.setattr(control_plane.config, "OLLAMA_LOCAL_BASE_URL", "http://localhost:11434")
    monkeypatch.setattr(control_plane.config, "OLLAMA_LOCAL_MODEL", "qwen2.5:7b")

    result = control_plane.check_provider("ollama_local")

    assert calls == ["http://localhost:11434/api/tags"]
    assert result["ok"] is True
    assert result["connectivity"] == "ok"
    assert result["modelAvailable"] is True


def test_openai_compatible_check_uses_models_metadata_and_redacts(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_get(url: str, **kwargs):
        calls.append((url, kwargs.get("headers") or {}))
        return FakeResponse({"data": [{"id": "glm-4.5"}, {"id": "other-model"}]})

    monkeypatch.setattr(control_plane.httpx, "get", fake_get)
    monkeypatch.setattr(control_plane.config, "OPENAI_COMPATIBLE_BASE_URL", "https://api.secret.test/v1")
    monkeypatch.setattr(control_plane.config, "OPENAI_COMPATIBLE_API_KEY", "sk-openai-secret")
    monkeypatch.setattr(control_plane.config, "OPENAI_COMPATIBLE_MODEL", "glm-4.5")

    result = control_plane.check_provider("openai_compatible")
    payload_text = json.dumps(control_plane.redact_payload(result))

    assert calls[0][0] == "https://api.secret.test/v1/models"
    assert calls[0][1]["Authorization"] == "Bearer sk-openai-secret"
    assert result["ok"] is True
    assert result["modelAvailable"] is True
    assert "sk-openai-secret" not in payload_text
    assert "https://api.secret.test" not in payload_text


def test_ollama_cloud_check_does_not_call_generation_or_metadata_when_no_safe_endpoint(monkeypatch):
    def fail_get(*args, **kwargs):  # pragma: no cover - should not be called
        raise AssertionError("ollama_cloud should not call httpx.get in Prompt52D")

    monkeypatch.setattr(control_plane.httpx, "get", fail_get)
    monkeypatch.setattr(control_plane.config, "OLLAMA_CLOUD_API_KEY", "cloud-secret")
    monkeypatch.setattr(control_plane.config, "OLLAMA_CLOUD_MODEL", "glm-5.1:cloud")
    monkeypatch.setattr(control_plane.config, "OLLAMA_CLOUD_BASE_URL", "https://ollama.com/api")

    result = control_plane.check_provider("ollama_cloud")

    assert result["ok"] is True
    assert result["connectivity"] == "unknown"
    assert "No safe non-generating" in result["message"]


def test_dispatch_api_responses_do_not_leak_secret_values(monkeypatch):
    monkeypatch.setattr(control_plane.config, "OPENAI_COMPATIBLE_API_KEY", "sk-dispatch-secret")
    monkeypatch.setattr(control_plane.config, "OPENAI_COMPATIBLE_BASE_URL", "https://secret.dispatch")
    monkeypatch.setattr(control_plane.config, "OPENAI_COMPATIBLE_MODEL", "secret-model")

    for method, path, body in [
        ("GET", "/api/status", None),
        ("GET", "/api/providers", None),
        ("GET", "/api/models", None),
        ("POST", "/api/providers/check", {"provider": "mock"}),
        ("POST", "/api/models/check", {"provider": "mock"}),
    ]:
        status, payload = control_plane.dispatch_api(method, path, body)
        assert status == 200
        text = json.dumps(control_plane.redact_payload(payload))
        assert "sk-dispatch-secret" not in text
        assert "https://secret.dispatch" not in text


def test_control_page_component_nav_and_route_verifier_are_registered():
    page = Path("site/docs/control/index.md").read_text(encoding="utf-8")
    component = Path(
        "site/docs/.vitepress/theme/components/ControlPlaneStatus.vue"
    ).read_text(encoding="utf-8")
    theme = Path("site/docs/.vitepress/theme/index.ts").read_text(encoding="utf-8")
    config = Path("site/docs/.vitepress/config.ts").read_text(encoding="utf-8")
    verifier = Path("scripts/verify_site_static_routes.py").read_text(encoding="utf-8")

    assert "<ControlPlaneStatus />" in page
    assert 'data-testid="control-plane"' in component
    assert "http://127.0.0.1:8765" in component
    assert "ControlPlaneStatus" in theme
    assert "{ text: 'Control plane', link: '/control/' }" in config
    assert '"/control/"' in verifier
    for forbidden in ["chat/completions", "/api/generate", "process-new", "reprocess"]:
        assert forbidden not in Path("wiki/control_plane.py").read_text(encoding="utf-8")
