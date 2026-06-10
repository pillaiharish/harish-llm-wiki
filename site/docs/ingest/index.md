---
title: Ingest & Processing
---

# Ingest & Processing

This page is a static local runbook. It helps you choose safe CLI commands, but it does not upload files, store browser-side secrets, or run provider calls from the webapp.

## Choose Your Processing Mode

<div class="ingest-mode-grid">
  <section class="wiki-card ingest-mode-card">
    <span class="wiki-chip">No cloud tokens</span>
    <h2>Safe demo mode</h2>
    <p>Use deterministic mock output for demos, UI checks, and pipeline validation.</p>
    <pre class="ingest-command"><code>LLM_PROVIDER=mock
.venv/bin/python -m wiki process-new --provider mock</code></pre>
  </section>
  <section class="wiki-card ingest-mode-card">
    <span class="wiki-chip">Local only</span>
    <h2>Local model mode</h2>
    <p>Use a local Ollama server. No cloud API token is used by this mode.</p>
    <pre class="ingest-command"><code>LLM_PROVIDER=ollama_local
.venv/bin/python -m wiki process-new --provider ollama_local</code></pre>
  </section>
  <section class="wiki-card ingest-mode-card">
    <span class="wiki-chip">Cloud token</span>
    <h2>Cloud provider mode</h2>
    <p>Uses API keys configured in local `.env`. Dry-run first; larger real runs require `--yes`.</p>
    <pre class="ingest-command"><code>.venv/bin/python -m wiki process-new --dry-run --provider ollama_cloud
.venv/bin/python -m wiki process-new --provider ollama_cloud --yes</code></pre>
  </section>
  <section class="wiki-card ingest-mode-card">
    <span class="wiki-chip">Configured endpoint</span>
    <h2>OpenAI-compatible mode</h2>
    <p>Uses your configured base URL, API key, and model from `.env`.</p>
    <pre class="ingest-command"><code>LLM_PROVIDER=openai_compatible
.venv/bin/python -m wiki process-new --dry-run --provider openai_compatible</code></pre>
  </section>
</div>

## Where API Tokens Are Enabled Or Disabled

<div class="wiki-card ingest-safety-card">
  <h2>Token boundary</h2>
  <p>The browser never accepts API keys and never starts provider calls. Token use is controlled only by local CLI options and `.env` provider settings.</p>
  <table>
    <thead>
      <tr><th>Goal</th><th>Use this</th><th>What happens</th></tr>
    </thead>
    <tbody>
      <tr><td>Disable cloud token use</td><td><code>LLM_PROVIDER=mock</code> or <code>--provider mock</code></td><td>Runs deterministic mock processing.</td></tr>
      <tr><td>Use local non-cloud processing</td><td><code>LLM_PROVIDER=ollama_local</code> or <code>--provider ollama_local</code></td><td>Uses your local Ollama server.</td></tr>
      <tr><td>Enable Ollama Cloud</td><td>Edit <code>.env</code>, set <code>LLM_PROVIDER=ollama_cloud</code> and API key/model</td><td>Uses configured cloud token after you run the CLI.</td></tr>
      <tr><td>Enable OpenAI-compatible provider</td><td>Edit <code>.env</code>, set <code>OPENAI_COMPATIBLE_BASE_URL</code>, key, and model</td><td>Uses configured endpoint after you run the CLI.</td></tr>
    </tbody>
  </table>
</div>

## Copyable Command Flow

Run these from the nested repo folder, not from the parent workspace.

<div class="ingest-command-flow">
  <section class="wiki-card ingest-command-card">
    <h2>Add one URL</h2>
    <pre class="ingest-command"><code>.venv/bin/python -m wiki add-resource --url "https://example.com/article"</code></pre>
  </section>
  <section class="wiki-card ingest-command-card">
    <h2>Add a batch file</h2>
    <pre class="ingest-command"><code>.venv/bin/python -m wiki add-batch --file inputs/batch_urls.example.txt --dry-run
.venv/bin/python -m wiki add-batch --file inputs/batch_urls.example.txt</code></pre>
  </section>
  <section class="wiki-card ingest-command-card">
    <h2>Preview processing</h2>
    <pre class="ingest-command"><code>.venv/bin/python -m wiki process-new --dry-run --provider mock</code></pre>
  </section>
  <section class="wiki-card ingest-command-card">
    <h2>Process safely with mock</h2>
    <pre class="ingest-command"><code>.venv/bin/python -m wiki process-new --provider mock</code></pre>
  </section>
  <section class="wiki-card ingest-command-card">
    <h2>Cloud dry-run</h2>
    <pre class="ingest-command"><code>.venv/bin/python -m wiki process-new --dry-run --provider ollama_cloud</code></pre>
  </section>
  <section class="wiki-card ingest-command-card">
    <h2>Cloud process with confirmation</h2>
    <pre class="ingest-command"><code>.venv/bin/python -m wiki process-new --only-stale --skip-ingest --provider ollama_cloud --yes</code></pre>
  </section>
  <section class="wiki-card ingest-command-card">
    <h2>Refresh generated site</h2>
    <pre class="ingest-command"><code>.venv/bin/python -m wiki build-site --refresh</code></pre>
  </section>
  <section class="wiki-card ingest-command-card">
    <h2>Validate before sharing</h2>
    <pre class="ingest-command"><code>.venv/bin/python -m pytest
.venv/bin/python -m wiki smoke-site
.venv/bin/python -m wiki validate</code></pre>
  </section>
</div>

## Supported Inputs

- Single URLs through `add-resource`.
- URL batches through `add-batch --file inputs/batch_urls.example.txt`.
- YAML-style resource examples in `inputs/resources.example.yaml`.
- Local/provider configuration through `.env`, based on `.env.example`.

Example files:

- [`.env.example`](https://github.com/pillaiharish/harish-llm-wiki/blob/main/.env.example)
- [`inputs/batch_urls.example.txt`](https://github.com/pillaiharish/harish-llm-wiki/blob/main/inputs/batch_urls.example.txt)
- [`inputs/resources.example.yaml`](https://github.com/pillaiharish/harish-llm-wiki/blob/main/inputs/resources.example.yaml)

## After Ingest

<div class="wiki-card-grid ingest-after-grid">
  <a class="wiki-card ingest-link-card" href="/review/">Review queue</a>
  <a class="wiki-card ingest-link-card" href="/timeline#needs-classification">Timeline classification</a>
  <a class="wiki-card ingest-link-card" href="/resources/">Resources</a>
  <a class="wiki-card ingest-link-card" href="/graph/graphify">Graphify graph</a>
  <a class="wiki-card ingest-link-card" href="/explorer/">Explorer search</a>
</div>

## Common Mistakes

- Running commands from the parent workspace instead of the nested repo folder.
- Using `python` instead of `.venv/bin/python`.
- Forgetting `--dry-run` before a real provider run.
- Setting a cloud provider in `.env` and assuming it is still mock mode.
- Expecting the browser to ingest data or store API keys.

## What The Webapp Does Not Do

- It does not accept API keys in the browser.
- It does not upload files or URLs to a backend.
- It does not trigger provider calls from a page button.
- It does not hide real-provider processing behind a UI toggle.

Those boundaries are intentional so a public demo can explain the data flow without risking accidental token use.
