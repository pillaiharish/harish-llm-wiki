"""Prompt 34 MVP closure tests.

These tests verify the deterministic no-LLM RAG MVP closure:
static context/RAG pages, CLI surface, release gate, browser test files,
and provider/runtime boundaries.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from wiki import cli


REPO_ROOT = Path(__file__).resolve().parents[1]


class TestPrompt34Files:
    def test_required_packages_exist(self):
        for rel in (
            "wiki/rag_template/__init__.py",
            "wiki/mock_answer/__init__.py",
            "wiki/rag_eval/__init__.py",
            "scripts/verify_mvp_release.py",
            "site/playwright.config.ts",
            "site/tests/e2e/mvp.spec.ts",
        ):
            assert (REPO_ROOT / rel).exists(), f"missing Prompt 34 file: {rel}"

    def test_static_pages_exist(self):
        for rel in (
            "site/docs/search/context.md",
            "site/docs/search/rag-report.md",
        ):
            assert (REPO_ROOT / rel).exists(), f"missing static page: {rel}"


class TestPrompt34Cli:
    def test_cli_help_lists_mvp_commands(self):
        result = CliRunner().invoke(cli.app, ["--help"])
        assert result.exit_code == 0
        for marker in ("build-rag-prompt", "mock-answer", "eval-rag"):
            assert marker in result.output

    def test_build_rag_prompt_json(self):
        result = CliRunner().invoke(
            cli.app, ["build-rag-prompt", "attention transformer", "--json"]
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["query"] == "attention transformer"
        assert payload["is_mock"] is True
        assert payload["mock_tag"] == "no-llm-template"

    def test_mock_answer_json(self):
        result = CliRunner().invoke(
            cli.app, ["mock-answer", "attention transformer", "--json"]
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["query"] == "attention transformer"
        assert payload["is_mock"] is True
        assert payload["mock_tag"] == "no-llm-mock"
        assert "MOCK / NO-LLM ANSWER" in payload["body"]

    def test_eval_rag_json(self):
        result = CliRunner().invoke(
            cli.app, ["eval-rag", "attention transformer", "--json"]
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["query"] == "attention transformer"
        assert payload["is_mock"] is True
        assert payload["mock_tag"] == "no-llm-mock"
        assert payload["total_checks"] >= 1
        assert payload["failed_checks"] == 0


class TestPrompt34StaticPages:
    def test_context_page_markers(self):
        text = (REPO_ROOT / "site/docs/search/context.md").read_text(
            encoding="utf-8"
        )
        for marker in (
            "# Context Pack",
            "## Query",
            "## Chunks",
            "## Sources",
            "Reproduce with the CLI",
        ):
            assert marker in text

    def test_rag_report_markers(self):
        text = (REPO_ROOT / "site/docs/search/rag-report.md").read_text(
            encoding="utf-8"
        )
        for marker in (
            "# RAG Eval Report",
            "Mock / No-LLM",
            "Score:",
            "## Checks",
            "Mock / No-LLM answer body",
            "Reproduce with the CLI",
        ):
            assert marker in text


class TestPrompt34ReleaseGate:
    def test_release_gate_passes(self):
        result = subprocess.run(
            [".venv/bin/python", "scripts/verify_mvp_release.py"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "MVP release gate passed" in result.stdout


class TestPrompt34BrowserFiles:
    def test_playwright_config_uses_dev_server(self):
        text = (REPO_ROOT / "site/playwright.config.ts").read_text(
            encoding="utf-8"
        )
        assert "docs:dev" in text
        assert "127.0.0.1:5173" in text

    def test_browser_spec_has_mvp_routes(self):
        text = (REPO_ROOT / "site/tests/e2e/mvp.spec.ts").read_text(
            encoding="utf-8"
        )
        for route in (
            "/",
            "/search/retrieval",
            "/search/eval",
            "/search/context",
            "/search/rag-report",
        ):
            assert route in text


class TestPrompt34Boundaries:
    @pytest.mark.parametrize(
        "rel",
        [
            "wiki/rag_template",
            "wiki/mock_answer",
            "wiki/rag_eval",
        ],
    )
    def test_no_provider_runtime_symbols_in_prompt34_packages(self, rel):
        root = REPO_ROOT / rel
        forbidden = (
            "OpenAICompatibleProvider",
            "OllamaLocalProvider",
            "OllamaCloudProvider",
            "chat.completions",
            "client.chat",
            "ask_llm",
            "generate_with_llm",
        )
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for needle in forbidden:
                assert needle not in text, (
                    f"forbidden provider/runtime symbol {needle!r} in {path}"
                )

    def test_no_v2_provider_router_added(self):
        for rel in (
            "wiki/provider_router.py",
            "wiki/llm_router.py",
            "tests/test_prompt35_provider_router.py",
        ):
            assert not (REPO_ROOT / rel).exists(), (
                f"V2 provider work should not exist in Prompt 34: {rel}"
            )
