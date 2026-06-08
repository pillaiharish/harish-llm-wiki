#!/usr/bin/env python3
"""Prompt 34 MVP release gate.

This script verifies the deterministic no-LLM V1 MVP closure artifacts.

It intentionally does not call any LLM provider, external API, or network service.
It checks that the CLI/static-site/browser-test release files exist and that
the generated static pages contain the required MVP markers.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


REQUIRED_FILES = [
    "wiki/context_pack/__init__.py",
    "wiki/rag_template/__init__.py",
    "wiki/mock_answer/__init__.py",
    "wiki/rag_eval/__init__.py",
    "wiki/cli.py",
    "wiki/site/builder.py",
    "site/docs/search/context.md",
    "site/docs/search/rag-report.md",
    "site/playwright.config.ts",
    "site/tests/e2e/mvp.spec.ts",
    "site/package.json",
]


REQUIRED_PAGE_MARKERS = {
    "site/docs/search/context.md": [
        "# Context Pack",
        "## Query",
        "Chunks",
        "Sources",
        "Reproduce with the CLI",
        "no LLM",
    ],
    "site/docs/search/rag-report.md": [
        "# RAG Eval Report",
        "Mock / No-LLM",
        "Score:",
        "Checks",
        "Mock / No-LLM answer body",
        "Reproduce with the CLI",
    ],
}


FORBIDDEN_RUNTIME_PATTERNS = [
    "OpenAICompatibleProvider",
    "OllamaCloudProvider",
    "OllamaLocalProvider",
    "Gemini",
    "ask_llm",
    "generate_with_llm",
    "chat.completions",
    "client.chat",
]


PROMPT34_PACKAGES = [
    "wiki/rag_template",
    "wiki/mock_answer",
    "wiki/rag_eval",
]


def fail(message: str) -> None:
    print(f"❌ {message}")
    raise SystemExit(1)


def check_required_files() -> int:
    checks = 0
    for rel in REQUIRED_FILES:
        path = REPO_ROOT / rel
        checks += 1
        if not path.exists():
            fail(f"Missing required file: {rel}")
    return checks


def check_pages() -> int:
    checks = 0
    for rel, markers in REQUIRED_PAGE_MARKERS.items():
        path = REPO_ROOT / rel
        if not path.exists():
            fail(f"Missing generated page: {rel}")
        text = path.read_text(encoding="utf-8")
        for marker in markers:
            checks += 1
            if marker not in text:
                fail(f"Missing marker {marker!r} in {rel}")
    return checks


def check_no_provider_calls() -> int:
    checks = 0
    for rel in PROMPT34_PACKAGES:
        root = REPO_ROOT / rel
        if not root.exists():
            fail(f"Missing Prompt 34 package: {rel}")
        for path in sorted(root.rglob("*.py")):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for pattern in FORBIDDEN_RUNTIME_PATTERNS:
                checks += 1
                if pattern in text:
                    fail(f"Forbidden provider/model pattern {pattern!r} in {path.relative_to(REPO_ROOT)}")
    return checks


def check_cli_help() -> int:
    cmd = [sys.executable, "-m", "wiki", "--help"]
    result = subprocess.run(cmd, cwd=REPO_ROOT, text=True, capture_output=True)
    if result.returncode != 0:
        fail("wiki --help failed")
    output = result.stdout + result.stderr
    checks = 0
    for marker in ["build-context", "build-rag-prompt", "mock-answer", "eval-rag"]:
        checks += 1
        if marker not in output:
            fail(f"CLI command missing from help: {marker}")
    return checks


def check_browser_test_script() -> int:
    package_json = (REPO_ROOT / "site" / "package.json").read_text(encoding="utf-8")
    checks = 0
    for marker in ["test:e2e", "playwright"]:
        checks += 1
        if marker not in package_json:
            fail(f"site/package.json missing marker: {marker}")
    return checks


def main() -> None:
    print("Verifying Prompt 34 MVP release gate...")
    checks = 0
    checks += check_required_files()
    checks += check_pages()
    checks += check_no_provider_calls()
    checks += check_cli_help()
    checks += check_browser_test_script()
    print(f"Checks: {checks}")
    print("✅ MVP release gate passed")


if __name__ == "__main__":
    main()
