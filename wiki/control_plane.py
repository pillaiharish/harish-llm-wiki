"""Local-only provider/model control plane for the static wiki UI."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

import httpx

from wiki.config import config
from wiki.runs import get_run, read_processing_runs, read_token_ledger, token_ledger_summary

CONTROL_PLANE_VERSION = "prompt52e"
SUPPORTED_PROVIDERS = ("mock", "ollama_local", "ollama_cloud", "openai_compatible")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def utc_now() -> str:
    """Return an ISO timestamp for API responses."""

    return datetime.now(timezone.utc).isoformat()


def is_loopback_host(host: str) -> bool:
    """Return True if a host is loopback-only."""

    normalized = (host or "").strip().lower()
    return normalized in {"127.0.0.1", "localhost", "::1"} or normalized.startswith("127.")


def _known_secret_values() -> list[str]:
    values = [
        config.OLLAMA_API_KEY,
        config.OLLAMA_CLOUD_API_KEY,
        config.OPENAI_COMPATIBLE_API_KEY,
        config.OLLAMA_CLOUD_BASE_URL,
        config.OPENAI_COMPATIBLE_BASE_URL,
    ]
    return [value for value in values if value and len(value) >= 4]


def redact_text(value: Any) -> str:
    """Redact secret-like fragments from a string."""

    text = str(value)
    for secret in _known_secret_values():
        text = text.replace(secret, "[redacted]")
    patterns = [
        r"Bearer\s+[A-Za-z0-9._~+/=-]+",
        r"(?i)(api[_-]?key|token|authorization)(\s*[:=]\s*)[A-Za-z0-9._~+/=-]+",
        r"sk-[A-Za-z0-9]{8,}",
    ]
    for pattern in patterns:
        text = re.sub(pattern, r"\1\2[redacted]" if "(" in pattern else "[redacted]", text)
    return text


def redact_payload(payload: Any) -> Any:
    """Recursively redact a JSON-like payload."""

    if isinstance(payload, dict):
        redacted: dict[str, Any] = {}
        for key, value in payload.items():
            lower = str(key).lower()
            if any(marker in lower for marker in ("api_key", "apikey", "token", "secret", "authorization")):
                redacted[key] = bool(value) if isinstance(value, bool) else "[redacted]"
            else:
                redacted[key] = redact_payload(value)
        return redacted
    if isinstance(payload, list):
        return [redact_payload(item) for item in payload]
    if isinstance(payload, str):
        return redact_text(payload)
    return payload


def provider_config(provider: str) -> dict[str, Any]:
    """Return redacted provider configuration status."""

    if provider == "mock":
        return {
            "provider": "mock",
            "label": "Mock provider",
            "tokenKind": "none",
            "configured": True,
            "keyPresent": False,
            "modelConfigured": True,
            "configuredModel": "mock-model",
            "metadataEndpoint": None,
        }
    if provider == "ollama_local":
        return {
            "provider": provider,
            "label": "Ollama local",
            "tokenKind": "none",
            "configured": True,
            "keyPresent": False,
            "modelConfigured": bool(config.OLLAMA_LOCAL_MODEL),
            "configuredModel": config.OLLAMA_LOCAL_MODEL or "",
            "metadataEndpoint": "ollama /api/tags",
        }
    if provider == "ollama_cloud":
        model = config.OLLAMA_CLOUD_MODEL or ""
        key_present = bool(config.OLLAMA_CLOUD_API_KEY)
        return {
            "provider": provider,
            "label": "Ollama Cloud",
            "tokenKind": "cloud",
            "configured": bool(key_present and model and config.OLLAMA_CLOUD_BASE_URL),
            "keyPresent": key_present,
            "modelConfigured": bool(model),
            "configuredModel": model,
            "metadataEndpoint": None,
        }
    if provider == "openai_compatible":
        model = config.OPENAI_COMPATIBLE_MODEL or ""
        key_present = bool(config.OPENAI_COMPATIBLE_API_KEY)
        return {
            "provider": provider,
            "label": "OpenAI-compatible",
            "tokenKind": "cloud",
            "configured": bool(key_present and model and config.OPENAI_COMPATIBLE_BASE_URL),
            "keyPresent": key_present,
            "modelConfigured": bool(model),
            "configuredModel": model,
            "metadataEndpoint": "openai-compatible /models",
        }
    return {
        "provider": provider,
        "label": provider,
        "tokenKind": "unknown",
        "configured": False,
        "keyPresent": False,
        "modelConfigured": False,
        "configuredModel": "",
        "metadataEndpoint": None,
    }


def provider_summaries() -> list[dict[str, Any]]:
    """Return all supported provider summaries."""

    return [provider_config(provider) for provider in SUPPORTED_PROVIDERS]


def configured_provider_summary() -> dict[str, Any]:
    """Return current configured provider/model summary."""

    provider = config.LLM_PROVIDER if config.LLM_PROVIDER in SUPPORTED_PROVIDERS else config.LLM_PROVIDER
    summary = provider_config(provider)
    return {
        "provider": provider,
        "configured": bool(summary.get("configured")),
        "configuredModel": summary.get("configuredModel") or "",
        "modelConfigured": bool(summary.get("modelConfigured")),
    }


def _model_names_from_ollama_tags(data: dict[str, Any]) -> list[str]:
    return sorted(
        str(item.get("name"))
        for item in data.get("models", [])
        if isinstance(item, dict) and item.get("name")
    )


def _model_names_from_openai_models(data: dict[str, Any]) -> list[str]:
    return sorted(
        str(item.get("id"))
        for item in data.get("data", [])
        if isinstance(item, dict) and item.get("id")
    )


def _error_payload(error_type: str, message: str) -> dict[str, str]:
    return {"type": error_type, "message": redact_text(message)}


def _base_check_payload(provider: str) -> dict[str, Any]:
    summary = provider_config(provider)
    return {
        "provider": provider,
        "checkedAt": utc_now(),
        "configured": bool(summary.get("configured")),
        "keyPresent": bool(summary.get("keyPresent")),
        "modelConfigured": bool(summary.get("modelConfigured")),
        "configuredModel": summary.get("configuredModel") or "",
        "availableModels": [],
        "modelAvailable": None,
        "connectivity": "unknown",
        "ok": False,
        "error": None,
        "message": "",
    }


def check_provider(provider: str, *, model: str | None = None, timeout: float = 5.0) -> dict[str, Any]:
    """Run a metadata-only provider check."""

    provider = provider.strip()
    result = _base_check_payload(provider)
    target_model = model or str(result.get("configuredModel") or "")

    if provider not in SUPPORTED_PROVIDERS:
        result["connectivity"] = "failed"
        result["error"] = _error_payload("unsupported_provider", f"Unsupported provider: {provider}")
        result["message"] = "Unsupported provider."
        return result

    if provider == "mock":
        result.update(
            {
                "configured": True,
                "keyPresent": False,
                "modelConfigured": True,
                "configuredModel": "mock-model",
                "availableModels": ["mock-model"],
                "modelAvailable": target_model in {"", "mock-model"},
                "connectivity": "ok",
                "ok": True,
                "message": "Mock provider is always available and uses no tokens.",
            }
        )
        return result

    if provider == "ollama_cloud":
        if not result["configured"]:
            result["connectivity"] = "failed"
            result["error"] = _error_payload(
                "missing_config",
                "OLLAMA_API_KEY/OLLAMA_CLOUD_API_KEY and OLLAMA_CLOUD_MODEL are required.",
            )
            result["message"] = "Ollama Cloud configuration is incomplete."
            return result
        result["connectivity"] = "unknown"
        result["ok"] = True
        result["modelAvailable"] = None
        result["message"] = "No safe non-generating Ollama Cloud metadata endpoint is configured."
        return result

    try:
        if provider == "ollama_local":
            response = httpx.get(
                f"{config.OLLAMA_LOCAL_BASE_URL.rstrip('/')}/api/tags",
                timeout=timeout,
            )
            response.raise_for_status()
            available = _model_names_from_ollama_tags(response.json())
        elif provider == "openai_compatible":
            if not result["configured"]:
                result["connectivity"] = "failed"
                result["error"] = _error_payload(
                    "missing_config",
                    "OPENAI_COMPATIBLE_BASE_URL, OPENAI_COMPATIBLE_API_KEY, and OPENAI_COMPATIBLE_MODEL are required.",
                )
                result["message"] = "OpenAI-compatible configuration is incomplete."
                return result
            response = httpx.get(
                f"{str(config.OPENAI_COMPATIBLE_BASE_URL).rstrip('/')}/models",
                headers={"Authorization": f"Bearer {config.OPENAI_COMPATIBLE_API_KEY}"},
                timeout=timeout,
            )
            response.raise_for_status()
            available = _model_names_from_openai_models(response.json())
        else:  # pragma: no cover - guarded above
            available = []
    except httpx.TimeoutException:
        result["connectivity"] = "failed"
        result["error"] = _error_payload("timeout", "Metadata request timed out.")
        result["message"] = "Metadata endpoint timed out."
        return result
    except httpx.HTTPStatusError as exc:
        result["connectivity"] = "failed"
        status = getattr(exc.response, "status_code", "unknown")
        result["error"] = _error_payload(
            "http_status",
            f"Metadata endpoint returned HTTP {status}.",
        )
        result["message"] = "Metadata endpoint returned an HTTP error."
        return result
    except httpx.RequestError:
        result["connectivity"] = "failed"
        result["error"] = _error_payload("request_error", "Metadata endpoint request failed.")
        result["message"] = "Metadata endpoint request failed."
        return result
    except Exception as exc:  # pragma: no cover - defensive
        result["connectivity"] = "failed"
        result["error"] = _error_payload("unexpected_error", str(exc))
        result["message"] = "Metadata check failed."
        return result

    result["availableModels"] = available
    result["modelAvailable"] = target_model in available if target_model else None
    result["connectivity"] = "ok"
    result["ok"] = bool(result["configured"] and (result["modelAvailable"] is not False))
    result["message"] = "Metadata endpoint is reachable."
    return result


def check_model(provider: str, model: str | None = None) -> dict[str, Any]:
    """Check a configured or requested model using metadata-only provider checks."""

    provider_result = check_provider(provider, model=model)
    return {
        "provider": provider_result["provider"],
        "checkedAt": provider_result["checkedAt"],
        "configuredModel": provider_result.get("configuredModel") or "",
        "requestedModel": model or provider_result.get("configuredModel") or "",
        "availableModels": provider_result.get("availableModels") or [],
        "modelAvailable": provider_result.get("modelAvailable"),
        "connectivity": provider_result.get("connectivity"),
        "ok": provider_result.get("ok"),
        "error": provider_result.get("error"),
        "message": provider_result.get("message"),
    }


def status_payload(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> dict[str, Any]:
    """Return control plane status payload."""

    return {
        "status": "ok",
        "version": CONTROL_PLANE_VERSION,
        "host": host,
        "port": port,
        "checkedAt": utc_now(),
        "currentProvider": configured_provider_summary(),
    }


def providers_payload() -> dict[str, Any]:
    """Return provider summaries."""

    return {"providers": provider_summaries(), "checkedAt": utc_now()}


def models_payload() -> dict[str, Any]:
    """Return configured model summaries without consuming tokens."""

    models = []
    for provider in SUPPORTED_PROVIDERS:
        summary = provider_config(provider)
        models.append(
            {
                "provider": provider,
                "configuredModel": summary.get("configuredModel") or "",
                "modelConfigured": bool(summary.get("modelConfigured")),
                "availableModels": ["mock-model"] if provider == "mock" else [],
                "metadataAvailable": provider in {"mock", "ollama_local", "openai_compatible"},
            }
        )
    return {"models": models, "checkedAt": utc_now()}


def runs_payload(limit: int = 25) -> dict[str, Any]:
    """Return recent local processing runs."""

    runs = list(reversed(read_processing_runs(limit=limit)))
    return {
        "runs": runs,
        "summary": token_ledger_summary(),
        "checkedAt": utc_now(),
    }


def run_payload(run_id: str) -> tuple[int, dict[str, Any]]:
    """Return one processing run."""

    run = get_run(run_id)
    if not run:
        return 404, {"error": {"type": "not_found", "message": "Run not found."}}
    return 200, {"run": run, "checkedAt": utc_now()}


def token_ledger_payload(limit: int = 100) -> dict[str, Any]:
    """Return recent local token ledger rows."""

    entries = list(reversed(read_token_ledger(limit=limit)))
    return {
        "entries": entries,
        "summary": token_ledger_summary(),
        "checkedAt": utc_now(),
    }


def token_ledger_summary_payload() -> dict[str, Any]:
    """Return token ledger totals."""

    return {"summary": token_ledger_summary(), "checkedAt": utc_now()}


def dispatch_api(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> tuple[int, dict[str, Any]]:
    """Dispatch an API request to a response payload."""

    body = body or {}
    if method == "GET" and path == "/api/status":
        return 200, status_payload(host=host, port=port)
    if method == "GET" and path == "/api/providers":
        return 200, providers_payload()
    if method == "GET" and path == "/api/models":
        return 200, models_payload()
    if method == "GET" and path == "/api/runs":
        return 200, runs_payload()
    if method == "GET" and path.startswith("/api/runs/"):
        return run_payload(path.rsplit("/", 1)[-1])
    if method == "GET" and path == "/api/token-ledger":
        return 200, token_ledger_payload()
    if method == "GET" and path == "/api/token-ledger/summary":
        return 200, token_ledger_summary_payload()
    if method == "POST" and path == "/api/providers/check":
        provider = str(body.get("provider") or "")
        return 200, check_provider(provider)
    if method == "POST" and path == "/api/models/check":
        provider = str(body.get("provider") or "")
        model = body.get("model")
        return 200, check_model(provider, str(model) if model else None)
    return 404, {"error": {"type": "not_found", "message": "Unknown control-plane endpoint."}}


def is_allowed_origin(origin: str | None) -> bool:
    """Return True for localhost-only browser origins."""

    if not origin:
        return False
    parsed = urlparse(origin)
    return parsed.scheme in {"http", "https"} and parsed.hostname in {
        "localhost",
        "127.0.0.1",
        "::1",
    }


class ControlPlaneRequestHandler(BaseHTTPRequestHandler):
    """HTTP handler for the local control-plane API."""

    server_version = "LLMWikiControlPlane/1.0"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Suppress noisy per-request stdlib logs."""

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        redacted = redact_payload(payload)
        raw = json.dumps(redacted, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(raw)

    def _send_cors_headers(self) -> None:
        origin = self.headers.get("Origin")
        if is_allowed_origin(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        self._handle_api_request("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._handle_api_request("POST")

    def _handle_api_request(self, method: str) -> None:
        parsed = urlparse(self.path)
        body: dict[str, Any] = {}
        if method == "POST":
            length = int(self.headers.get("Content-Length") or "0")
            if length:
                try:
                    body = json.loads(self.rfile.read(length).decode("utf-8"))
                except json.JSONDecodeError:
                    self._send_json(
                        400,
                        {"error": {"type": "invalid_json", "message": "Request body must be JSON."}},
                    )
                    return
        host = getattr(self.server, "control_plane_host", DEFAULT_HOST)
        port = int(getattr(self.server, "control_plane_port", DEFAULT_PORT))
        status, payload = dispatch_api(method, parsed.path, body, host=host, port=port)
        self._send_json(status, payload)


def serve_control_plane(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    """Run the local control-plane HTTP server."""

    server = ThreadingHTTPServer((host, port), ControlPlaneRequestHandler)
    server.control_plane_host = host  # type: ignore[attr-defined]
    server.control_plane_port = port  # type: ignore[attr-defined]
    try:
        server.serve_forever()
    finally:
        server.server_close()
