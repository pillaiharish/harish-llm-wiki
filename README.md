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
- **Deduplication**: Detects duplicates by URL/content hash
- **LLM Notes**: Generates Karpathy-style explanations with provenance
- **Citations**: Timestamp citations for YouTube, section/paragraph for text
- **Timeline**: Chronological learning trail
- **Tags**: Browse resources by topic
- **Concepts**: Auto-extracted concept pages
- **Gaps**: Knowledge gaps that need attention
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

### 2. Configuration

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```env
# Required: Data directory
LLM_WIKI_DATA_DIR=/Users/harishkumarpillai/llm-wiki-data

# Default provider (uses Ollama Cloud API)
LLM_PROVIDER=ollama_cloud
OLLAMA_CLOUD_API_KEY=your_api_key_here
OLLAMA_CLOUD_MODEL=qwen2.5:7b
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
# Generate static site
python -m wiki build-site

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

# Skip confirmation for LLM calls
python -m wiki process-new --yes

# Force reprocess already-processed resources
python -m wiki process-new --force

# Generate notes only for a specific resource
python -m wiki generate-notes --resource youtube:abc123

# Generate notes with limit
python -m wiki generate-notes --limit 3 --yes
```

### Site and Validation

```bash
# Build the VitePress site
python -m wiki build-site

# Validate configuration and content
python -m wiki validate

# Full pipeline: process + build + validate
python -m wiki full-run
```

## LLM Providers

### Ollama Cloud (Default)

Requires API key from [ollama.com](https://ollama.com/settings/api):

```env
LLM_PROVIDER=ollama_cloud
OLLAMA_CLOUD_API_KEY=your_api_key
OLLAMA_CLOUD_MODEL=qwen2.5:7b
```

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
└── site_generated/      # Generated VitePress content
```

**Important**: Raw transcripts, HTML, and LLM-generated notes contain copyrighted content. Do not publish the external data directory publicly.

## Testing

```bash
# Run all tests
make test
# or
pytest tests/ -q

# Test with mock provider
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