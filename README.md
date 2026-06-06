# Harish LLM Wiki

A personal static learning wiki generated from YouTube transcripts, blog posts, and LLM-generated notes.

## Overview

Harish LLM Wiki is a Python pipeline that:

1. **Ingests** learning resources (YouTube videos, blog posts, Markdown files)
2. **Deduplicates** resources using canonical IDs
3. **Normalizes** content into citeable chunks
4. **Generates** LLM-powered learning notes with proper citations
5. **Builds** a static VitePress website for browsing

## Features

- **YouTube Integration**: Extract transcripts with timestamp citations
- **Blog Scraping**: Public webpage extraction (no paywall bypass)
- **Markdown Import**: Manual import of articles and notes
- **Local PDF Import**: Page-wise text extraction with page-citation chunks
- **Deduplication**: Detects duplicates by URL/content hash
- **LLM Notes**: Generates Karpathy-inspired first-principles explanations with provenance
- **Citations**: Timestamp citations for YouTube, section/paragraph for text, page numbers for PDFs
- **Timeline**: Chronological learning trail
- **Tags**: Browse resources by topic
- **Concepts**: Auto-extracted concept pages
- **Gaps**: Knowledge gaps that need attention
- **Knowledge Graph**: Deterministic nodes/edges exported as JSON
- **Graph Viewer**: Static page with search, filters, and neighbor explorer
- **Resource Relationships**: Deterministic same-source-type / shared-topic edges
- **Chunk Index**: Deterministic, citation-aware chunk index for future search and retrieval
- **BM25 Search**: Deterministic lexical search backend over the chunk index (no embeddings, no vector DB)
- **Search**: VitePress built-in search
- **Static Site**: No backend required for reading

## Quick Start

### 1. Installation

```bash
git clone git@github.com:pillaiharish/harish-llm-wiki.git
cd harish-llm-wiki

python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Optional installs:

```bash
# Development/test tools
pip install -e ".[dev]"

# Local Whisper ASR only
pip install -e ".[asr-whisper]"

# faster-whisper ASR only
pip install -e ".[asr-faster-whisper]"

# All local media transcription providers
pip install -e ".[media]"

# All optional runtime providers
pip install -e ".[all]"
```

The base install is enough for URLs, Markdown, Medium Markdown, imported transcripts, mock LLM runs, and Ollama Cloud note generation. Install an ASR extra only when you want to transcribe local audio/video files on this machine.

### 2. Configuration

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```env
# Required: Data directory
LLM_WIKI_DATA_DIR=~/llm-wiki-data

# Default provider (uses Ollama Cloud API)
LLM_PROVIDER=ollama_cloud
OLLAMA_API_KEY=your_api_key_here
OLLAMA_CLOUD_MODEL=qwen2.5:7b
LLM_NOTE_REPAIR_RETRIES=1
```

### 3. Initialize

```bash
python -m wiki init
```

This creates the external data directory at `~/llm-wiki-data/` (or your configured path).

### 4. Add Resources

Create a batch file with URLs:

```bash
mkdir -p ~/llm-wiki-data/inbox/urls
```

Then add URLs to `~/llm-wiki-data/inbox/urls/batch_2026-05-30.txt`:

```text
# YouTube videos
https://www.youtube.com/watch?v=r2m9DbEmeqI
https://www.youtube.com/watch?v=v6g8eo86T8A

# Blog posts
https://www.aleksagordic.com/blog/vllm
```

Add them to the registry:

```bash
# Preview what would be added (no changes made)
python -m wiki add-batch --file ~/llm-wiki-data/inbox/urls/batch_2026-05-30.txt --dry-run

# Actually add the resources
python -m wiki add-batch --file ~/llm-wiki-data/inbox/urls/batch_2026-05-30.txt
```

Or add a single resource:

```bash
python -m wiki add-resource --url "https://www.youtube.com/watch?v=example"
```

Or import a Markdown file:

```bash
python -m wiki import-markdown --file path/to/article.md --url "https://original-source.com"
```

### 5. Process Resources

**For testing (uses mock provider, no API costs):**

```bash
LLM_PROVIDER=mock python -m wiki process-new --limit 2 --yes
```

**For production (uses Ollama Cloud, costs tokens):**

```bash
# Process all new resources (prompts confirmation if > 2)
python -m wiki process-new

# Skip confirmation prompt
python -m wiki process-new --yes

# Process a limited number
python -m wiki process-new --limit 3 --yes

# Preview what would be done (no changes made)
python -m wiki process-new --dry-run
```

### 6. Build and View Site

```bash
# Generate static site; --refresh regenerates derived views without LLM calls
python -m wiki build-site --refresh

# View locally (development server with hot reload)
cd site
npm install
npm run docs:dev

# Or build for production
cd site
npm run docs:build
# Output is in ../dist/
```

## CLI Commands

### Resource Management

```bash
# Add a single URL
python -m wiki add-resource --url "https://..."

# Add URLs from a batch file
python -m wiki add-batch --file ~/llm-wiki-data/inbox/urls/batch_2026-05-30.txt

# Dry-run: preview what would be added (no changes)
python -m wiki add-batch --file path/to/urls.txt --dry-run

# Import a Markdown file
python -m wiki import-markdown --file path/to/article.md --url "https://..."

# List all resources
python -m wiki list-resources

# List pending resources (need processing)
python -m wiki list-pending
```

### Processing

```bash
# Process new resources through the pipeline
python -m wiki process-new

# Dry-run: show what would be processed (no changes)
python -m wiki process-new --dry-run

# Limit to N resources
python -m wiki process-new --limit 2

# Process exactly one known resource
python -m wiki process-new --force --limit 1 --resource-id webpage:abc123

# Skip confirmation for LLM calls
python -m wiki process-new --yes

# Force reprocess already-processed resources
python -m wiki process-new --force

# Bypass the real-provider quality gate only after review
python -m wiki process-new --force --yes --allow-untitled
python -m wiki process-new --force --yes --skip-quality-gate

# Generate notes only for a specific resource
python -m wiki generate-notes --resource youtube:abc123

# Generate notes with limit
python -m wiki generate-notes --limit 3 --yes
```

### Site and Validation

```bash
# Build the VitePress site
python -m wiki build-site

# Regenerate timeline, topics, tags, concepts, gaps, and site docs without LLM calls
python -m wiki regenerate-views

# Alias: regenerate-derived (same as regenerate-views)
python -m wiki regenerate-derived

# Refresh derived views before building the VitePress mirror
python -m wiki build-site --refresh

# Smoke-test provider configuration without touching resource data
python -m wiki test-llm --provider mock
python -m wiki test-llm --provider ollama_cloud

# Validate configuration and content
python -m wiki validate

# Smoke-test the built static site
python -m wiki smoke-site

# Full pipeline: process + build + validate
python -m wiki full-run
```

### BM25 Search Backend

The BM25 lexical search backend (Prompt 28) consumes the chunk index
and produces a deterministic inverted index for keyword search. It
is the lexical half of the planned hybrid retrieval router; the
vector half (embeddings) and the graph retriever belong to later
prompts.

The BM25 backend:

- depends on **no new runtime libraries**; the scorer is a small
  pure-Python module under `wiki/search/`;
- uses the same tokenizer at index time and query time (lowercasing,
  punctuation stripping, bundled stopword list, length filter);
- is byte-stable: same chunk index + same query = same ranking;
- ties broken deterministically by `chunk_id` ascending.

CLI commands:

```bash
# Build the BM25 index (rebuilds the chunk index first by default).
python -m wiki build-bm25-index

# Skip the chunk-index rebuild (assumes it is already current).
python -m wiki build-bm25-index --no-build-chunk-index

# Search the BM25 index. The default is a Rich table; pass --json
# to emit a JSON array on stdout.
python -m wiki search-bm25 "attention transformer"
python -m wiki search-bm25 "scaled dot-product attention" --json
python -m wiki search-bm25 "embeddings retrieval" --limit 5
python -m wiki search-bm25 "vllm paged attention" --source-type youtube
python -m wiki search-bm25 "rag evaluation" --resource-id pdf:abc...
```

The on-disk BM25 index lives under
`data/processed/bm25/index.json` (gitignored; regenerated on every
build). A small public copy is written to
`data/site_generated/docs/public/search/bm25_*.json` and a static
report page to `data/site_generated/docs/search/bm25.md` so the
VitePress site can link to it. The static report page is at
`/search/bm25` in the built site.

Example queries (also in the static report page):

- `attention transformer` – top result is the
  "Attention Is All You Need" paper chunk.
- `scaled dot-product attention` – top result is the
  `Scaled Dot-Product Attention` section.
- `embeddings retrieval` – top result is an embeddings resource.
- `vllm paged attention` – top result is a vLLM resource.
- `rag evaluation` – top result is an evals resource.

Manual verification:

```bash
# Run the full BM25 search flow against a real PDF.
.venv/bin/python scripts/verify_bm25_search.py

# Verify that the expected static routes exist on the built site.
.venv/bin/python scripts/verify_site_static_routes.py
```

## LLM Providers

### Ollama Cloud (Default)

Requires API key from [ollama.com](https://ollama.com/settings/api):

```env
LLM_PROVIDER=ollama_cloud
OLLAMA_API_KEY=your_api_key
OLLAMA_CLOUD_MODEL=qwen2.5:7b
```

`OLLAMA_API_KEY` is the preferred variable. `OLLAMA_CLOUD_API_KEY` is still accepted as a backward-compatible alias.

### Mock Provider (For Testing)

No API key needed. Generates deterministic placeholder content for testing the site structure:

```bash
LLM_PROVIDER=mock python -m wiki process-new --limit 2 --yes
```

The mock provider generates notes with all required sections:
- Source-backed notes with mock citations
- LLM-added explanations (marked as generated by mock)
- Related concepts
- Revision questions
- Provenance section

### Local Ollama (Optional Fallback)

```env
LLM_PROVIDER=ollama_local
OLLAMA_LOCAL_BASE_URL=http://localhost:11434
OLLAMA_LOCAL_MODEL=qwen2.5:7b
```

Requires local Ollama server:

```bash
ollama serve
ollama pull qwen2.5:7b
```

### OpenAI-Compatible (GLM Cloud, Kimi, Minimax, OpenRouter)

```env
LLM_PROVIDER=openai_compatible
OPENAI_COMPATIBLE_BASE_URL=https://api.example.com/v1
OPENAI_COMPATIBLE_API_KEY=your_key
OPENAI_COMPATIBLE_MODEL=model-name
```

## Safety Features

### LLM Cost Protection

The pipeline protects against accidental token consumption:

1. **Mock provider**: Test the entire pipeline without any API costs
2. **Dry-run mode**: Preview what would be processed
3. **Limit mode**: Process only N resources at a time
4. **Confirmation prompt**: If processing > 2 resources with a real provider, requires `--yes`
5. **LLM caching**: Skips regeneration if content hasn't changed
6. **Quality gate**: Before `process-new --force --yes` with a real provider, checks metadata coverage, untitled resources, webpage extraction, transcript chunks, and source URLs. Use `--allow-untitled` or `--skip-quality-gate` only when intentional.
7. **Contract repair**: If a generated note fails validation, the pipeline retries with a strict repair prompt. `LLM_NOTE_REPAIR_RETRIES=1` by default. If repair still fails, debug artifacts are written under `~/llm-wiki-data/debug/failed_notes/` and the resource is marked `failed_retryable` with `requires_human_review=true`.

```bash
# Safe testing - no API costs
LLM_PROVIDER=mock python -m wiki process-new --dry-run
LLM_PROVIDER=mock python -m wiki process-new --limit 2 --yes

# Production - with safety checks
python -m wiki process-new --limit 3 --yes   # Process 3 resources
python -m wiki process-new                     # Prompts if > 2 resources
python -m wiki process-new --yes               # Skip prompt
```

### Deduplication

- YouTube URLs are identified by video ID only
- Same video with different timestamps merges timestamps, doesn't create duplicates
- Webpage URLs are normalized (tracking params removed)
- Markdown files are identified by content hash

## Directory Structure

### Git Repository

```
harish-llm-wiki/
├── wiki/                 # Python pipeline code
├── site/                 # VitePress templates and config
├── inputs/               # Sample input files
├── tests/                # Test suite
├── pyproject.toml
├── .env.example
├── Makefile
└── README.md
```

### External Data Directory (not in Git)

```
~/llm-wiki-data/
├── inbox/               # Drop new URLs and Markdown files here
│   ├── urls/            # Batch URL files
│   └── markdown/        # Manually saved articles
├── registry/            # SQLite database for resource tracking
├── raw/                 # Downloaded transcripts and HTML
├── normalized/          # Cleaned and chunked content
├── processed/           # Generated LLM notes
│   ├── topics/          # Rule-based topic map pages
│   ├── timeline/        # Grouped timeline views
│   ├── tags/            # Tag views
│   └── concepts/        # Concept pages
└── site_generated/      # Generated VitePress content
```

`python -m wiki build-site --refresh` regenerates derived views and mirrors generated Markdown into ignored `site/docs` paths so VitePress can serve it locally. Those files are reproducible from `~/llm-wiki-data` and should remain uncommitted.

**Important**: Raw transcripts, HTML, and LLM-generated notes contain copyrighted content. Do not publish the external data directory publicly.

## Testing

```bash
# Run all tests
make test
# or
pytest tests/ -q

# Test with mock provider
LLM_PROVIDER=mock python -m wiki test-llm --provider mock
LLM_PROVIDER=mock python -m wiki process-new --dry-run
LLM_PROVIDER=mock python -m wiki process-new --limit 1 --yes
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Format code
make format

# Lint code
make lint

# Clean generated files
make clean
```

## Deployment

### Local Browsing (Default, Safest)

```bash
python -m wiki build-site
cd site && npm install && npm run docs:dev
```

### GitHub Pages (Only if content is safe to share publicly)

```bash
cd site && npm run docs:build
# Deploy dist/ to GitHub Pages
```

### Cloudflare Pages (Only if content is safe to share publicly)

```bash
cd site && npm run docs:build
# Deploy dist/ to Cloudflare Pages
```

## Citation Format

### YouTube

```markdown
This video explains tokenization.  
**Citation:** YouTube, 00:03:12-00:04:08
```

### Blog/Article

```markdown
The article argues for semantic chunking.  
**Citation:** RAG Chunking Guide, section "Chunk Size", paragraph 6
```

### Local Media/Transcripts

```markdown
The lecture explains retrieval latency.  
**Citation:** local media timestamp: 00:02:00-00:02:35
```

### LLM-Added Explanations

```markdown
## LLM-added explanations

Generated by: ollama_cloud / qwen2.5:7b

The original resource did not explain hybrid retrieval.
```

## Privacy and Safety

- Only processes **public** YouTube transcripts
- Only scrapes **public** webpages (no paywall bypass)
- Manual Markdown import for paywalled content
- External data directory keeps Git repo clean
- Generated notes may contain copyrighted material
- **Do not publish generated content publicly** without review

## Architecture

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Inputs    │───▶│   Registry   │───▶│   Ingest    │───▶│  Normalize  │
│  (URLs/MD)  │    │  (SQLite)   │    │  (Fetch)    │    │   (Chunk)   │
└─────────────┘    └─────────────┘    └─────────────┘    └──────┬──────┘
                                                                  │
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌──────┴──────┐
│    dist/     │◀───│    Site     │◀───│  Generate   │◀───│     LLM     │
│  (Static)   │    │  (VitePress)│    │   (Notes)   │    │  (Provider)  │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
```

Providers: `ollama_cloud` (default) | `ollama_local` | `openai_compatible` | `mock`

## Dependency Extras

The optional dependency groups are intentionally small:

- `.[dev]`: test/lint tooling (`pytest`, `ruff`)
- `.[asr-whisper]`: local OpenAI Whisper transcription
- `.[asr-faster-whisper]`: local faster-whisper transcription
- `.[media]`: both local ASR providers
- `.[all]`: all optional runtime providers

`ffmpeg` is still a system dependency, not a Python package. Check it with:

```bash
ffmpeg -version
```

Install it with `brew install ffmpeg` on macOS or `sudo apt-get install ffmpeg` on Ubuntu.

## Medium

Public Medium URLs are fetched only if publicly accessible. The wiki does not bypass login walls or paywalls. If a Medium page is not fully available, it is marked `needs_manual_markdown` and you can import copied/exported Markdown:

```bash
python -m wiki add-resource --url "https://medium.com/..."
python -m wiki import-medium-markdown --file article.md --original-url "https://medium.com/..."
python -m wiki process-new --only-stale --skip-ingest --provider ollama_cloud --resource-id medium_markdown:<hash> --yes
python -m wiki build-site --refresh
```

The imported resource ID is printed by the command as `medium_markdown:<hash>`. Use that exact ID for `process-new` if you want to process only that article.

## Local Video/Audio

Ollama Cloud is not used for raw MP3/video transcription. Extract/transcribe locally first, then send transcript chunks to the LLM note pipeline.

```bash
python -m wiki add-media --file ~/Videos/talk.mp4
python -m wiki transcribe-media --resource-id media:<hash> --provider whisper
python -m wiki process-new --only-stale --skip-ingest --provider ollama_cloud --resource-id media:<hash> --yes
python -m wiki build-site --refresh
```

The `add-media` command prints the `media:<hash>` resource ID. Use that exact ID in `transcribe-media` and `process-new`.

Transcription uses `ffmpeg` to normalize audio to 16 kHz mono WAV. Local Whisper support requires `pip install -e ".[asr-whisper]"`; faster-whisper requires `pip install -e ".[asr-faster-whisper]"`. For a dependency-free smoke test of the media pipeline, use `--provider mock`.

## Local PDF

Local PDFs are read with `pypdf` and ingested as a first-class resource type. Page text is extracted deterministically; chunks are grouped by contiguous page ranges with stable page-level citations.

```bash
python -m wiki import-pdf --file ./inputs/papers/attention.pdf --title "Attention Is All You Need"
python -m wiki import-pdf --file ./inputs/papers/attention.pdf --title "Attention Is All You Need" --copy-file
python -m wiki process-new --only-stale --skip-ingest --provider ollama_cloud --resource-id pdf:<sha256> --yes
python -m wiki build-site --refresh
```

Optional flags:

- `--title` — override the title (otherwise the PDF's `/Title` metadata is used, falling back to the filename stem).
- `--source-url` — record a canonical online URL for the PDF when one is available.
- `--tags` — comma-separated tags written to the record.
- `--copy-file` / `--no-copy-file` — opt-in copy of the original PDF into `~/llm-wiki-data/media/pdfs/<sha256>.pdf`. The default is `--no-copy-file`; the SHA-256 ties subsequent imports of the same path to the same record.
- `--force` — re-ingest even if a record with the same canonical id already exists.

The `import-pdf` command prints the `pdf:<sha256>` resource ID. Use that exact ID in `process-new` if you want to process only that resource.

Encrypted or scanned PDFs are not supported in this prompt; image-only pages are recorded in `extraction_warnings` but not OCR'd.

## Existing Transcript

Use this when you already have a transcript from Colab, Whisper, or manual notes:

```bash
python -m wiki import-transcript --file transcript.txt --source-title "My Lecture"
python -m wiki process-new --only-stale --skip-ingest --provider ollama_cloud --resource-id transcript:<hash> --yes
python -m wiki build-site --refresh
```

The `import-transcript` command prints the `transcript:<hash>` resource ID. Imported transcripts do not require Whisper or ffmpeg.

## Daily Workflow

```bash
python -m wiki add-resource --url "https://example.com/article"
python -m wiki daily --provider ollama_cloud --yes
cd site && npm run docs:dev
```

Safe defaults:

```bash
python -m wiki daily --provider mock --limit 1
python -m wiki daily --skip-llm
```

## Review, Search, Revision, Learn

`build-site --refresh` regenerates the full static wiki surface: resource pages, topics, Learn chapters, review dashboard, search indexes, Explorer, Sources, revision questions, flashcards, tags, timeline, concepts, and gaps.

You can also run these pieces directly:

```bash
python -m wiki generate-review-pages
python -m wiki generate-search-index
python -m wiki generate-revision
python -m wiki export-flashcards --format json
python -m wiki export-flashcards --format csv
```

### CLI Command Aliases

| Alias | Canonical Command |
|---|---|
| `regenerate-derived` | `regenerate-views` |
| `regenerate-revision` | `generate-revision` |
| `regenerate-notes` | `generate-notes` |

## Doctor

```bash
python -m wiki doctor
python -m wiki doctor --check-asr
python -m wiki doctor --check-llm
```

## Status Report

```bash
python -m wiki status-report
```

Reports are written under `~/llm-wiki-data/reports/`.

## Backup

```bash
python -m wiki backup
python -m wiki backup --include-debug
python -m wiki backup --include-media
```

Backups include the external wiki data folder, not the Git repo.

## Restore

```bash
python -m wiki restore --file backup.tar.gz --target-dir ~/llm-wiki-data-restored
python -m wiki restore --file backup.tar.gz --target-dir ~/llm-wiki-data-restored --yes
```

## Makefile Commands

```bash
make init          # Initialize directory structure
make install       # Install package
make dev-install   # Install with dev dependencies
make ingest        # Ingest resources
make normalize     # Normalize raw data
make notes         # Generate LLM notes
make site          # Build static site
make full          # Run complete pipeline
make validate      # Validate content
make test          # Run tests
make lint          # Lint code
make format        # Format code
make clean         # Clean generated files
make dev-server    # Start VitePress dev server
make build-site-npm # Build site with npm
```
