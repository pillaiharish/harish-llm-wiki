"""CLI for Harish LLM Wiki."""

from pathlib import Path
from typing import Optional, List
from datetime import datetime, timezone
import hashlib
import json
import re
import shutil
import sys
import tarfile
from collections import Counter

import typer
from rich.console import Console
from rich.table import Table
from rich import box

from wiki.config import config
from wiki.schemas import ResourceIdentity, ResourceRecord, ResourceStatus, SourceType
from wiki.registry import registry
from wiki.dedupe import deduplicator
from wiki.ingest.youtube import youtube_ingestor
from wiki.ingest.webpage import webpage_ingestor
from wiki.ingest.markdown import markdown_ingestor
from wiki.ingest.media import extract_audio_to_wav, media_ingestor
from wiki.ingest.pdf import PdfEncryptedError, pdf_ingestor
from wiki.normalize.pdf import pdf_normalizer
from wiki.normalize.transcript import youtube_normalizer
from wiki.normalize.webpage import webpage_normalizer
from wiki.normalize.markdown import markdown_normalizer
from wiki.normalize.transcript_media import (
    parse_transcript_text,
    transcript_media_normalizer,
)
from wiki.asr.providers import get_asr_provider
from wiki.llm.ollama_cloud import OllamaCloudProvider
from wiki.llm.ollama_local import OllamaLocalProvider
from wiki.llm.openai_compatible import OpenAICompatibleProvider
from wiki.llm.mock import MockProvider
from wiki.llm.base import LLMProvider
from wiki.generate.notes import get_note_generator, load_chunks, compute_chunks_hash
from wiki.llm.prompts import PROMPT_VERSION
from wiki.generate.concepts import concept_extractor
from wiki.generate.timeline import timeline_generator
from wiki.generate.gaps import gaps_generator
from wiki.generate.tags import tags_generator
from wiki.generate.topics import topic_generator
from wiki.generate.learn import learn_generator
from wiki.generate.review import review_generator
from wiki.generate.search import search_index_generator
from wiki.generate.revision import revision_generator
from wiki.chunks import (
    build_chunk_index as build_chunk_index_fn,
    write_chunk_index as write_chunk_index_files,
    write_public_copy as write_public_chunk_copy,
    chunk_index_output_paths,
)
from wiki.site.builder import site_builder
from wiki.enrich.metadata import youtube_metadata_enricher, webpage_metadata_enricher
from wiki.resource_utils import is_replaceable_title, topic_matches
from wiki.storage import Storage


def normalize_provider_name(name: str | None) -> str:
    """Normalize a provider name to its canonical underscore-separated form.

    Handles legacy values stored without underscores (e.g. "ollamacloud")
    as well as the canonical forms (e.g. "ollama_cloud").
    """
    if not name:
        return ""
    n = name.lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "ollamacloud": "ollama_cloud",
        "ollama_cloud": "ollama_cloud",
        "ollamalocal": "ollama_local",
        "ollama_local": "ollama_local",
        "ollama-local": "ollama_local",
        "openai": "openai_compatible",
        "openai_compatible": "openai_compatible",
        "openaicompatible": "openai_compatible",
        "mock": "mock",
    }
    return aliases.get(n, n)


def stale_reasons(record, target_provider: str, target_model: str) -> list[str]:
    """Return a list of human-readable reasons why a note is stale.

    A note is current only when ALL conditions are met:
    - prompt_version == current
    - llm_provider == target_provider (after normalization)
    - llm_model == target_model
    - generated_note_path exists
    - status != failed_retryable
    """
    reasons: list[str] = []
    if record.status.value == "failed_retryable":
        reasons.append("failed_retryable")
    if not record.generated_note_path or not record.generated_note_path.exists():
        reasons.append("missing_note_path")
    if record.prompt_version != PROMPT_VERSION:
        reasons.append(f"prompt_version:{record.prompt_version or 'none'}")
    rec_prov = normalize_provider_name(record.llm_provider)
    if target_provider != "mock" and rec_prov == "mock":
        reasons.append("provider_mismatch:mock→real")
    elif rec_prov != target_provider:
        reasons.append(f"provider_mismatch:{rec_prov or 'none'}→{target_provider}")
    elif target_model and record.llm_model and record.llm_model != target_model:
        reasons.append(f"model_mismatch:{record.llm_model}→{target_model}")
    return reasons


app = typer.Typer(
    name="wiki",
    help="Harish LLM Wiki - Personal static learning wiki",
    no_args_is_help=True,
)
console = Console()


def get_provider() -> LLMProvider:
    """Get the configured LLM provider."""
    provider_name = config.LLM_PROVIDER
    
    if provider_name == "ollama_cloud":
        return OllamaCloudProvider()
    elif provider_name == "ollama_local":
        return OllamaLocalProvider()
    elif provider_name == "openai_compatible":
        return OpenAICompatibleProvider()
    elif provider_name == "mock":
        return MockProvider()
    else:
        raise ValueError(f"Unknown LLM provider: {provider_name}")


def get_provider_by_name(provider_name: str) -> LLMProvider:
    """Get an LLM provider by name, overriding the config default."""
    if provider_name == "ollama_cloud":
        if not config.OLLAMA_CLOUD_API_KEY:
            console.print("[red]OLLAMA_API_KEY or OLLAMA_CLOUD_API_KEY is not set[/red]")
            raise typer.Exit(1)
        if not config.OLLAMA_CLOUD_MODEL:
            console.print("[red]OLLAMA_CLOUD_MODEL is not set[/red]")
            raise typer.Exit(1)
        return OllamaCloudProvider()
    elif provider_name == "ollama_local":
        return OllamaLocalProvider()
    elif provider_name == "openai_compatible":
        if not config.OPENAI_COMPATIBLE_BASE_URL:
            console.print("[red]OPENAI_COMPATIBLE_BASE_URL is not set[/red]")
            raise typer.Exit(1)
        if not config.OPENAI_COMPATIBLE_API_KEY:
            console.print("[red]OPENAI_COMPATIBLE_API_KEY is not set[/red]")
            raise typer.Exit(1)
        if not config.OPENAI_COMPATIBLE_MODEL:
            console.print("[red]OPENAI_COMPATIBLE_MODEL is not set[/red]")
            raise typer.Exit(1)
        return OpenAICompatibleProvider()
    elif provider_name == "mock":
        return MockProvider()
    else:
        console.print(f"[red]Unknown provider: {provider_name}[/red]")
        console.print("Available: ollama_cloud, ollama_local, openai_compatible, mock")
        raise typer.Exit(1)


def configured_provider_model() -> tuple[str, str]:
    """Return provider/model from config without creating network clients."""
    if config.LLM_PROVIDER == "ollama_cloud":
        return config.LLM_PROVIDER, config.OLLAMA_CLOUD_MODEL or ""
    if config.LLM_PROVIDER == "ollama_local":
        return config.LLM_PROVIDER, config.OLLAMA_LOCAL_MODEL
    if config.LLM_PROVIDER == "openai_compatible":
        return config.LLM_PROVIDER, config.OPENAI_COMPATIBLE_MODEL or ""
    if config.LLM_PROVIDER == "mock":
        return "mock", "mock-model"
    return config.LLM_PROVIDER, ""


def would_regenerate_note(record, *, force: bool = False) -> bool:
    """Estimate whether note generation would call the LLM."""
    if force:
        return True
    if not record.generated_note_path or not record.generated_note_path.exists():
        return True
    if record.prompt_version != PROMPT_VERSION:
        return True
    _, configured_model = configured_provider_model()
    if configured_model and record.llm_model != configured_model:
        return True
    if record.local_normalized_path:
        chunks = list(load_chunks(Path(record.local_normalized_path)))
        if chunks and record.source_chunks_hash != compute_chunks_hash(chunks):
            return True
    return False


def is_note_stale(record, target_provider: str, target_model: str) -> bool:
    """Return True if a resource's note is stale relative to a target provider and model.

    Uses normalize_provider_name() so legacy stored values like "ollamacloud"
    compare equal to canonical "ollama_cloud".
    """
    return bool(stale_reasons(record, target_provider, target_model))


def _count_files(directory: Path, pattern: str = "*.md") -> int:
    if not directory.exists():
        return 0
    return len(list(directory.glob(pattern)))


def _timeline_counts(periods) -> tuple[int, int]:
    """Return timeline period and entry counts from generated periods."""
    if periods is None:
        timeline_json = config.get_data_path("processed", "timeline", "timeline.json")
        if not timeline_json.exists():
            return 0, 0
        try:
            data = Storage.read_json(timeline_json)
            loaded_periods = data.get("periods", [])
            return len(loaded_periods), sum(len(period.get("entries", [])) for period in loaded_periods)
        except Exception:
            return 0, 0
    return len(periods), sum(len(period.entries) for period in periods)


def _resource_route_target_exists(local_page: str, site_dir: Path) -> bool:
    """Return whether a generated route path has a matching Markdown page."""
    if not local_page.startswith("/"):
        return False
    if local_page.endswith(".md"):
        return False
    rel = local_page.strip("/")
    candidates = [site_dir / f"{rel}.md", site_dir / rel / "index.md"]
    return any(path.exists() for path in candidates)


def write_generation_manifest(records, *, concepts=None, tags=None, topics=None,
                               learn=None, gaps=None, review=None, revision=None,
                               indexes=None, timeline=None, graph=None,
                               chunks=None) -> Path:
    """Write generated_manifest.json after all derived views finish."""
    timeline_period_count, timeline_entry_count = _timeline_counts(timeline)
    graph_stats = (graph or {}).get("stats", {}) if isinstance(graph, dict) else {}
    chunk_count = 0
    chunk_resource_count = 0
    if chunks is not None:
        chunk_count = len(chunks.chunks)
        chunk_resource_count = len(chunks.chunk_count_by_resource)
    manifest = {
        "generated_at": datetime.utcnow().isoformat(),
        "resource_count": len(list(records)) if records else 0,
        "concept_count": len(concepts) if concepts else _count_files(config.get_data_path("processed", "concepts"), "*.md"),
        "tag_count": len(tags) if tags else 0,
        "topic_count": len(topics) if topics else _count_files(config.get_data_path("processed", "topics"), "*.md"),
        "learn_page_count": len(learn) if learn else _count_files(config.get_data_path("processed", "learn"), "*.md"),
        "review_item_count": sum(len(v) for v in (review or {}).values()) if isinstance(review, dict) else 0,
        "revision_question_count": len(revision.get("questions", [])) if isinstance(revision, dict) and revision else 0,
        "search_index_items": len((indexes or {}).get("all", [])),
        "gaps_count": len(gaps.needs_verification) + len(gaps.weak_examples) + len(gaps.missing_project_connection) + len(gaps.resources_missing_metadata) if gaps else 0,
        "timeline_periods": timeline_period_count,
        "timeline_entries": timeline_entry_count,
        "graph_node_count": graph_stats.get("node_count", 0),
        "graph_edge_count": graph_stats.get("edge_count", 0),
        "chunk_count": chunk_count,
        "chunk_resource_count": chunk_resource_count,
        "outputs": {
            "concepts": str(config.get_data_path("processed", "concepts")),
            "timeline": str(config.get_data_path("processed", "timeline", "timeline.md")),
            "tags": str(config.get_data_path("processed", "tags", "tags.md")),
            "topics": str(config.get_data_path("processed", "topics")),
            "gaps": str(config.get_data_path("processed", "gaps", "gaps.md")),
            "learn": str(config.get_data_path("processed", "learn")),
            "review": str(config.get_data_path("processed", "review")),
            "search": str(config.get_data_path("processed", "search")),
            "revision": str(config.get_data_path("processed", "revision")),
            "explorer": str(config.get_data_path("site_generated", "docs", "explorer", "index.md")),
            "sources": str(config.get_data_path("site_generated", "docs", "sources", "index.md")),
            "graph": str(config.get_data_path("site_generated", "docs", "public", "graph")),
            "chunks": str(config.get_data_path("processed", "chunk_index")),
            "chunks_public": str(config.get_data_path("site_generated", "docs", "public", "chunks")),
        },
    }
    manifest_path = config.get_data_path("processed", "generated_manifest.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    Storage.write_json(manifest, manifest_path)
    return manifest_path


def _build_knowledge_graph_for_manifest(records):
    """Build and export the knowledge graph (Prompt 23).

    Returns the in-memory graph dict, or ``{}`` if the build fails
    (in which case a warning is logged but execution continues).
    """
    from wiki.graph import GraphBuilder
    from wiki.graph.export import export_graph

    try:
        graph = GraphBuilder().build(records)
        export_graph(graph)
    except Exception as exc:  # pragma: no cover - defensive
        console.print(f"  [yellow]⚠[/yellow] Knowledge graph build failed: {exc}")
        return {}
    return graph


def _build_chunk_index_for_manifest(records):
    """Build and export the chunk index (Prompt 27).

    Returns the :class:`wiki.chunks.ChunkIndexResult` envelope, or
    ``None`` if the build fails. On failure a warning is logged but
    the overall build continues, matching the defensive pattern used
    by the knowledge graph step.
    """
    try:
        result = build_chunk_index_fn(records)
        write_chunk_index_files(result)
        # Also write a small public copy so VitePress can serve it.
        try:
            write_public_chunk_copy()
        except Exception as exc:  # pragma: no cover - defensive
            console.print(
                f"  [yellow]⚠[/yellow] Chunk index public copy failed: {exc}"
            )
    except Exception as exc:  # pragma: no cover - defensive
        console.print(f"  [yellow]⚠[/yellow] Chunk index build failed: {exc}")
        return None
    return result


def generate_derived_views(records=None) -> dict:
    """Regenerate derived views without calling an LLM.

    Returns the manifest dict with counts.
    """
    records = list(records or registry.get_all())

    console.print("Generating concepts...")
    concept_extractor.concepts = {}
    concept_extractor.aggregate(records)
    concept_extractor.save()
    console.print("  [green]✓[/green] Concepts saved")

    console.print("Generating tags...")
    tags = tags_generator.generate(records)
    tags_generator.save(tags)
    console.print("  [green]✓[/green] Tags saved")

    console.print("Generating topics...")
    topics = topic_generator.generate(records)
    topic_generator.save(topics)
    console.print("  [green]✓[/green] Topics saved")

    console.print("Generating timeline...")
    periods = timeline_generator.generate(records)
    timeline_generator.save(periods)
    console.print("  [green]✓[/green] Timeline saved")

    console.print("Generating gaps report...")
    gaps = gaps_generator.generate(records)
    gaps_generator.save(gaps)
    console.print("  [green]✓[/green] Gaps saved")

    console.print("Generating learn chapters...")
    learn = learn_generator.generate(records)
    learn_generator.save(learn)
    console.print("  [green]✓[/green] Learn chapters saved")

    console.print("Generating review pages...")
    review = review_generator.generate(records)
    review_generator.save(review)
    console.print("  [green]✓[/green] Review pages saved")

    console.print("Generating search indexes...")
    indexes = search_index_generator.generate(records)
    search_index_generator.save(indexes)
    console.print("  [green]✓[/green] Search indexes saved")

    console.print("Generating revision pages...")
    revision = revision_generator.generate(records)
    revision_generator.save(revision)
    console.print("  [green]✓[/green] Revision pages saved")

    console.print("Generating knowledge graph...")
    graph_data = _build_knowledge_graph_for_manifest(records)
    console.print("  [green]✓[/green] Knowledge graph saved")

    console.print("Generating chunk index...")
    chunk_result = _build_chunk_index_for_manifest(records)
    if chunk_result is not None:
        console.print("  [green]✓[/green] Chunk index saved")
    else:
        console.print("  [yellow]⚠[/yellow] Chunk index not built")

    console.print("Writing generation manifest...")
    manifest_path = write_generation_manifest(
        records, concepts=concept_extractor.concepts, tags=tags, topics=topics,
        learn=learn, gaps=gaps, review=review, revision=revision, indexes=indexes,
        timeline=periods, graph=graph_data, chunks=chunk_result,
    )
    console.print("  [green]✓[/green] Manifest saved")

    manifest = Storage.read_json(manifest_path)
    console.print(f"\n  Resources: {manifest['resource_count']}")
    console.print(f"  Tags: {manifest['tag_count']}")
    console.print(f"  Gaps: {manifest['gaps_count']}")
    console.print(f"  Learn pages: {manifest['learn_page_count']}")
    console.print(f"  Search index items: {manifest['search_index_items']}")
    console.print(f"  Graph nodes: {manifest.get('graph_node_count', 0)}")
    console.print(f"  Graph edges: {manifest.get('graph_edge_count', 0)}")
    console.print(f"  Chunk index chunks: {manifest.get('chunk_count', 0)}")
    console.print(f"  Chunk index resources: {manifest.get('chunk_resource_count', 0)}")

    return manifest


def quality_gate_issues(records) -> list[str]:
    """Return quality gate issues for real bulk processing."""
    records = list(records)
    if not records:
        return []
    untitled = [r for r in records if is_replaceable_title(r.title)]
    with_metadata = [r for r in records if not is_replaceable_title(r.title) and r.original_url]
    coverage = len(with_metadata) / len(records)
    issues: list[str] = []
    if coverage <= 0.90:
        issues.append(f"metadata coverage is {coverage:.0%}; required > 90%")
    if len(untitled) > 2:
        issues.append(f"{len(untitled)} resources have replaceable titles; maximum allowed is 2")
    for record in records:
        if not record.original_url:
            issues.append(f"{record.id}: missing source URL")
        if record.source_type.value == "youtube":
            chunks_path = Path(record.local_normalized_path or "") / "chunks.jsonl"
            if record.local_normalized_path and not chunks_path.exists():
                issues.append(f"{record.id}: transcript chunks missing")
        if record.source_type.value == "webpage":
            status = record.extra.get("metadata_status")
            if status == "failed_retryable":
                issues.append(f"{record.id}: webpage metadata failed")
            if record.local_raw_path and not (Path(record.local_raw_path) / "extracted.md").exists():
                issues.append(f"{record.id}: webpage extracted content missing")
    return issues


@app.command()
def init():
    """Initialize the wiki directory structure."""
    console.print("[bold blue]Initializing Harish LLM Wiki...[/bold blue]")
    
    # Validate config
    errors = config.validate()
    if errors:
        console.print("[bold red]Configuration errors:[/bold red]")
        for error in errors:
            console.print(f"  - {error}")
        raise typer.Exit(1)
    
    # Create directories
    config.ensure_directories()
    
    console.print(f"[green]✓[/green] Data directory: {config.LLM_WIKI_DATA_DIR}")
    console.print(f"[green]✓[/green] LLM Provider: {config.LLM_PROVIDER}")
    console.print("[green]✓[/green] Initialization complete!")
    console.print("\nNext steps:")
    console.print("  1. Add resources: wiki add-batch --file <path>")
    console.print("  2. Process new: wiki process-new")
    console.print("  3. Build site: wiki build-site")


@app.command()
def add_resource(
    url: str = typer.Option(..., "--url", "-u", help="URL to add"),
    tags: Optional[List[str]] = typer.Option(None, "--tag", "-t", help="Tags for the resource"),
):
    """Add a single resource to the registry."""
    console.print(f"[bold blue]Adding resource:[/bold blue] {url}")
    
    # Canonicalize
    identity = deduplicator.canonicalize(url)
    if not identity:
        console.print(f"[red]✗[/red] Could not canonicalize URL: {url}")
        raise typer.Exit(1)
    
    # Check for duplicate
    existing = registry.get_by_canonical_id(identity.canonical_id)
    if existing:
        console.print(f"[yellow]⚠[/yellow] Resource already exists: {existing.id}")
        console.print(f"  Status: {existing.status.value}")
        
        # Update timestamps if it's a YouTube video with timestamp
        if identity.start_time_seconds and existing.extra.get('important_timestamps'):
            registry.update_timestamps(existing.id, identity.start_time_seconds)
            console.print("  Updated timestamps")
        
        return
    
    # Insert new resource
    record = registry.insert(identity, status=ResourceStatus.NEW)
    if tags:
        record.tags = list(tags)
        registry.update(record)
    
    console.print(f"[green]✓[/green] Added: {record.id}")


@app.command()
def add_batch(
    file: Path = typer.Option(..., "--file", "-f", help="Path to batch file with URLs"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be added without modifying"),
):
    """Add resources from a batch file."""
    console.print(f"[bold blue]Processing batch:[/bold blue] {file}")
    
    if dry_run:
        console.print("[yellow]DRY RUN - No changes will be made[/yellow]\n")
    
    if not file.exists():
        console.print(f"[red]✗[/red] File not found: {file}")
        raise typer.Exit(1)
    
    # Read and parse file
    lines = file.read_text(encoding="utf-8").strip().split("\n")
    
    total = 0
    valid = 0
    new = 0
    duplicates = 0
    youtube_videos = 0
    blog_resources = 0
    unsupported = 0
    errors: List[str] = []
    
    # Track what would be added
    to_add: List[tuple[str, str]] = []  # (url, canonical_id)
    duplicate_ids: List[tuple[str, str]] = []  # (url, existing_id)
    
    for line in lines:
        line = line.strip()
        total += 1
        
        # Skip empty lines and comments
        if not line or line.startswith("#"):
            continue
        
        valid += 1
        
        # Canonicalize
        identity = deduplicator.canonicalize(line)
        if not identity:
            unsupported += 1
            errors.append(f"Unsupported URL: {line}")
            continue
        
        # Check for duplicate
        existing = registry.get_by_canonical_id(identity.canonical_id)
        if existing:
            duplicates += 1
            duplicate_ids.append((line, existing.id))
            
            if not dry_run:
                # Update timestamps if it's a YouTube video with timestamp
                if identity.start_time_seconds:
                    registry.update_timestamps(existing.id, identity.start_time_seconds)
            
            continue
        
        # Track counts by type
        if identity.source_type.value == "youtube":
            youtube_videos += 1
        else:
            blog_resources += 1
        
        # Track new resource
        to_add.append((line, identity.canonical_id))
        
        if not dry_run:
            # Insert new resource
            try:
                registry.insert(identity, status=ResourceStatus.NEW)
                new += 1
            except Exception as e:
                errors.append(f"Failed to add {line}: {e}")
        else:
            new += 1  # For dry-run count
    
    # Print results
    console.print("\n[bold]Batch Results:[/bold]")
    console.print(f"  Total lines: {total}")
    console.print(f"  Valid URLs: {valid}")
    console.print(f"  [green]New resources: {new}[/green]")
    console.print(f"    - YouTube videos: {youtube_videos}")
    console.print(f"    - Blog/resources: {blog_resources}")
    console.print(f"  [yellow]Duplicates skipped: {duplicates}[/yellow]")
    if unsupported > 0:
        console.print(f"  [red]Unsupported URLs: {unsupported}[/red]")
    
    # In dry-run mode, show details
    if dry_run:
        if to_add:
            console.print("\n[dim]Resources that would be added:[/dim]")
            for url, canonical_id in to_add[:10]:  # Show first 10
                console.print(f"  [green]+[/green] {url[:60]}...")
                console.print(f"      → {canonical_id}")
            if len(to_add) > 10:
                console.print(f"  ... and {len(to_add) - 10} more")
        
        if duplicate_ids:
            console.print("\n[dim]Duplicates that would be skipped:[/dim]")
            for url, existing_id in duplicate_ids[:5]:  # Show first 5
                console.print(f"  [yellow]-[/yellow] {url[:60]}...")
                console.print(f"      → Already exists as: {existing_id}")
            if len(duplicate_ids) > 5:
                console.print(f"  ... and {len(duplicate_ids) - 5} more duplicates")
        
        console.print("\n[dim]No changes made (dry-run mode)[/dim]")
    elif errors:
        console.print("\n[red]Errors:[/red]")
        for error in errors[:10]:
            console.print(f"  - {error}")


@app.command()
def list_resources(
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status"),
    limit: int = typer.Option(50, "--limit", "-n", help="Maximum number to show"),
):
    """List all resources in the registry."""
    console.print("[bold blue]Resources[/bold blue]\n")
    
    # Get filter
    status_filter = None
    if status:
        try:
            status_filter = ResourceStatus(status)
        except ValueError:
            console.print(f"[red]Invalid status: {status}[/red]")
            raise typer.Exit(1)
    
    # Get records
    records = list(registry.get_all(status_filter))
    
    # Create table
    table = Table(box=box.SIMPLE)
    table.add_column("ID", style="cyan")
    table.add_column("Type", style="green")
    table.add_column("Status", style="yellow")
    table.add_column("Prompt", style="magenta")
    table.add_column("Title", style="white")
    table.add_column("First Seen", style="dim")
    
    for record in records[:limit]:
        title = (record.title or "Untitled")[:40]
        if len(record.title or "") > 40:
            title += "..."
        
        pv = record.prompt_version or "-"
        if pv != "-" and pv != PROMPT_VERSION:
            pv = f"[yellow]{pv}[/yellow]"
        
        table.add_row(
            record.id[:30],
            record.source_type.value,
            record.status.value,
            pv,
            title,
            record.first_seen_at.strftime("%Y-%m-%d")
        )
    
    console.print(table)
    console.print(f"\nShowing {min(limit, len(records))} of {len(records)} resources")


@app.command()
def list_pending():
    """List resources waiting to be processed."""
    console.print("[bold blue]Pending Resources[/bold blue]\n")
    
    records = list(registry.get_pending())
    
    if not records:
        console.print("[dim]No pending resources.[/dim]")
        return
    
    table = Table(box=box.SIMPLE)
    table.add_column("ID", style="cyan")
    table.add_column("Type", style="green")
    table.add_column("Status", style="yellow")
    table.add_column("URL", style="white")
    
    for record in records:
        url = record.original_url[:50]
        if len(record.original_url) > 50:
            url += "..."
        
        table.add_row(
            record.id[:30],
            record.source_type.value,
            record.status.value,
            url
        )
    
    console.print(table)
    console.print(f"\n{len(records)} resource(s) pending")


@app.command()
def list_stale_notes(
    provider: Optional[str] = typer.Option(None, "--provider", help="Check staleness relative to this provider (mock, ollama_cloud, ollama_local, openai_compatible)"),
    limit: int = typer.Option(50, "--limit", "-n", help="Maximum number to show"),
):
    """List resources whose generated notes need regeneration.

    Without --provider, shows notes with prompt_version != current.
    With --provider, shows notes that are stale for that provider
    (e.g., mock-generated notes are stale for ollama_cloud).

    Use this before running:
      python -m wiki process-new --only-stale --skip-ingest --provider <provider>
    """
    console.print("[bold blue]Stale Notes[/bold blue]\n")
    console.print(f"[dim]Current prompt version: {PROMPT_VERSION}[/dim]\n")

    all_records = list(registry.get_all())

    if provider:
        # Provider-aware staleness: check if the note needs (re-)generation for this provider
        target_model = ""
        if provider == "mock":
            target_model = "mock-model"
        elif provider == "ollama_cloud":
            target_model = config.OLLAMA_CLOUD_MODEL or ""
        elif provider == "ollama_local":
            target_model = config.OLLAMA_LOCAL_MODEL
        elif provider == "openai_compatible":
            target_model = config.OPENAI_COMPATIBLE_MODEL or ""

        stale = [r for r in all_records if is_note_stale(r, provider, target_model)]
        current = [r for r in all_records if not is_note_stale(r, provider, target_model)]

        console.print(f"[dim]Checking staleness for provider: {provider}[/dim]")
        if target_model:
            console.print(f"[dim]Target model: {target_model}[/dim]")
        console.print()
    else:
        # Simple prompt-version check
        stale = [r for r in all_records if r.prompt_version != PROMPT_VERSION]
        current = [r for r in all_records if r.prompt_version == PROMPT_VERSION]
        provider = None
        target_model = ""

    if not stale:
        console.print("[green]All notes are at current version for this provider.[/green]")
        return

    table = Table(box=box.SIMPLE)
    table.add_column("ID", style="cyan")
    table.add_column("Status", style="yellow")
    table.add_column("Provider", style="magenta")
    table.add_column("Model", style="dim")
    table.add_column("PV", style="dim")
    if provider:
        table.add_column("Stale reason", style="red")
    table.add_column("Title", style="white")

    for record in stale[:limit]:
        title = (record.title or "Untitled")[:35]
        if len(record.title or "") > 35:
            title += "..."
        pv = record.prompt_version or "none"
        prov = normalize_provider_name(record.llm_provider) or "none"
        model = record.llm_model or "none"
        status = record.status.value

        row = [
            record.id[:30],
            status,
            prov,
            model[:20],
            pv,
        ]
        if provider:
            reasons = stale_reasons(record, provider, target_model)
            row.append(", ".join(reasons))
        row.append(title)

        table.add_row(*row)

    console.print(table)
    console.print(f"\n{len(stale)} stale | {len(current)} current | {len(all_records)} total")
    console.print(f"\n[dim]Run: python -m wiki process-new --only-stale --skip-ingest --provider {provider or '<provider>'}[/dim]")


@app.command()
def enrich_metadata(
    resource_id: Optional[str] = typer.Option(
        None,
        "--resource-id",
        "--resource",
        "-r",
        help="Specific resource ID to enrich",
    ),
    limit: Optional[int] = typer.Option(None, "--limit", "-n", help="Limit number of resources to enrich"),
    force: bool = typer.Option(False, "--force", help="Re-fetch metadata even if already enriched"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be enriched without making changes"),
):
    """Enrich resource metadata (titles, authors, descriptions) from external sources.
    
    For YouTube: uses yt-dlp to fetch video metadata.
    For webpages: extracts OpenGraph and meta tags from cached HTML.
    """
    console.print("[bold blue]Enriching metadata...[/bold blue]\n")
    
    if dry_run:
        console.print("[yellow]DRY RUN - No changes will be made[/yellow]\n")
    
    # Get resources to enrich
    if resource_id:
        record = registry.get_by_id(resource_id)
        if not record:
            console.print(f"[red]Resource not found: {resource_id}[/red]")
            raise typer.Exit(1)
        records = [record]
    else:
        # Get all resources that might need enrichment
        all_records = list(registry.get_all())
        # Filter to those missing title or with empty title
        records = [r for r in all_records if not r.title or r.title == "Untitled"]
    
    if not records:
        console.print("[dim]No resources need metadata enrichment.[/dim]")
        return
    
    # Apply limit
    total = len(records)
    if limit and limit < total:
        records = records[:limit]
    
    console.print(f"Found {total} resource(s) needing enrichment")
    if limit:
        console.print(f"Processing: {len(records)} (limited by --limit)")
    console.print()
    
    enriched = 0
    failed = 0
    skipped = 0
    
    for record in records:
        console.print(f"Enriching: [cyan]{record.id}[/cyan]")
        
        if dry_run:
            console.print(f"  [dim]Would fetch metadata for {record.source_type.value}[/dim]")
            continue
        
        try:
            if record.source_type.value == "youtube":
                record = youtube_metadata_enricher.enrich(record, force=force)
            elif record.source_type.value == "webpage":
                record = webpage_metadata_enricher.enrich(record, force=force)
            else:
                console.print(f"  [dim]No metadata enricher for {record.source_type.value}[/dim]")
                skipped += 1
                continue
            
            if record.title:
                console.print(f"  [green]✓[/green] Title: {record.title[:60]}")
                enriched += 1
            else:
                console.print("  [yellow]⚠[/yellow] No title found")
                failed += 1
            
            registry.update(record)
        except Exception as e:
            console.print(f"  [red]✗ Failed: {e}[/red]")
            failed += 1
    
    console.print("\n[bold]Summary:[/bold]")
    console.print(f"  Enriched: {enriched}")
    console.print(f"  Failed: {failed}")
    if skipped:
        console.print(f"  Skipped: {skipped}")
    if dry_run:
        console.print("\n[dim]No changes made (dry-run mode)[/dim]")


@app.command()
def process_new(
    force: bool = typer.Option(False, "--force", help="Force reprocessing of all eligible resources"),
    force_all: bool = typer.Option(False, "--force-all", help="Force reprocessing regardless of prompt version (same as --force)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done without modifying"),
    limit: Optional[int] = typer.Option(None, "--limit", "-n", help="Limit number of resources to process"),
    resource_id: Optional[str] = typer.Option(None, "--resource-id", "--resource", help="Process a specific resource ID"),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation for LLM calls"),
    allow_untitled: bool = typer.Option(False, "--allow-untitled", help="Allow more than 2 untitled resources in quality gate"),
    skip_quality_gate: bool = typer.Option(False, "--skip-quality-gate", help="Skip real-provider quality gate"),
    skip_ingest: bool = typer.Option(False, "--skip-ingest", help="Skip ingest/normalize for resources that already have chunks"),
    only_stale: bool = typer.Option(False, "--only-stale", help="Only process resources whose prompt version differs from current"),
    provider: Optional[str] = typer.Option(None, "--provider", help="Override LLM provider (mock, ollama_cloud, ollama_local, openai_compatible)"),
):
    """Process new resources through the pipeline.

    Use --only-stale to re-generate only notes that are behind the current
    prompt version. Use --force-all to regenerate everything regardless.

    --only-stale selects resources where prompt_version != current PROMPT_VERSION.
    --force selects all non-duplicate-failed resources (use for full re-ingestion).
    --force-all is an alias for --force.

    --skip-ingest skips the ingest and normalize steps for resources that
    already have chunks.jsonl in their normalized directory.

    --provider overrides the LLM_PROVIDER env var for this run only.
    """
    console.print("[bold blue]Processing new resources...[/bold blue]\n")

    # Resolve --force / --force-all
    if force_all:
        force = True

    # Resolve --provider override
    if provider:
        config.LLM_PROVIDER = provider
        console.print(f"[dim]Provider overridden to: {provider}[/dim]")

    if dry_run:
        console.print("[yellow]DRY RUN - No changes will be made[/yellow]\n")

    # Select resources based on flags
    if resource_id:
        record = registry.get_by_id(resource_id)
        if not record:
            console.print(f"[red]Resource not found: {resource_id}[/red]")
            raise typer.Exit(1)
        records = [record]
    elif only_stale:
        # Select resources whose notes are stale for the target provider
        target_provider_name = config.LLM_PROVIDER
        target_model = ""
        if target_provider_name == "mock":
            target_model = "mock-model"
        elif target_provider_name == "ollama_cloud":
            target_model = config.OLLAMA_CLOUD_MODEL or ""
        elif target_provider_name == "ollama_local":
            target_model = config.OLLAMA_LOCAL_MODEL
        elif target_provider_name == "openai_compatible":
            target_model = config.OPENAI_COMPATIBLE_MODEL or ""
        all_records_for_stale = list(registry.get_all())
        stale_records = [r for r in all_records_for_stale if is_note_stale(r, target_provider_name, target_model)]
        if not stale_records:
            console.print("[green]All notes are at current version for this provider.[/green]")
            console.print(f"[dim]Provider: {target_provider_name}, Model: {target_model or 'any'}[/dim]")
            return
        records = stale_records
        console.print(f"[dim]--only-stale: found {len(records)} resource(s) stale for provider={target_provider_name}[/dim]")
        if target_model:
            console.print(f"[dim]--only-stale: target model={target_model}[/dim]")
    elif force:
        records = [
            r for r in registry.get_all()
            if r.status not in {
                ResourceStatus.DUPLICATE_SKIPPED,
                ResourceStatus.FAILED_PERMANENT,
            }
        ]
    else:
        records = list(registry.get_pending())

    if not records:
        console.print("[dim]No new resources to process.[/dim]")
        return

    # Apply limit if specified
    total_count = len(records)
    if limit and limit < total_count:
        records = records[:limit]

    console.print(f"Found {total_count} resource(s) to process")
    if limit:
        console.print(f"Processing: {len(records)} (limited by --limit)")
    console.print()

    if (
        (force or only_stale or force_all)
        and not dry_run
        and config.LLM_PROVIDER != "mock"
        and not skip_quality_gate
    ):
        issues = quality_gate_issues(records)
        if allow_untitled:
            issues = [issue for issue in issues if "replaceable titles" not in issue]
        if issues:
            console.print("[red]Quality gate failed before real LLM processing:[/red]")
            for issue in issues:
                console.print(f"  - {issue}")
            console.print("Use --allow-untitled or --skip-quality-gate only if you accept the risk.")
            raise typer.Exit(1)
    
    # Safety check for real LLM calls
    if not dry_run and config.LLM_PROVIDER != "mock":
        needs_llm = sum(1 for r in records if would_regenerate_note(r, force=force or force_all or only_stale))
        if needs_llm > 2 and not yes:
            console.print(f"[yellow]Warning:[/yellow] About to process {needs_llm} resources using {config.LLM_PROVIDER}")
            console.print("This may consume cloud tokens.")
            console.print("Use --yes to continue or use --provider mock for testing.")
            raise typer.Exit(1)
    
    # Get LLM provider (only if we'll generate notes)
    provider_inst = None
    
    # Track dry-run stats
    would_ingest = 0
    would_normalize = 0
    would_call_llm = 0
    would_cache_hit = 0
    would_need_manual = 0
    
    for record in records:
        console.print(f"Processing: [cyan]{record.id}[/cyan]")
        
        # Check if we can skip ingest/normalize
        can_skip_ingest = False
        if skip_ingest and record.local_normalized_path:
            chunks_path = Path(record.local_normalized_path) / "chunks.jsonl"
            if chunks_path.exists():
                can_skip_ingest = True
        
        if dry_run:
            # In dry-run mode, analyze what would be done
            console.print("  [dim]Analysis:[/dim]")
            
            if record.status == ResourceStatus.NEEDS_MANUAL_MARKDOWN:
                console.print("  [yellow]⚠ Would mark as 'needs_manual_markdown'[/yellow]")
                would_need_manual += 1
                continue
            
            if can_skip_ingest:
                console.print("  [dim]  - Skip ingest/normalize (chunks exist)[/dim]")
            else:
                console.print("  [dim]  - Would ingest raw content[/dim]")
                would_ingest += 1
                
                console.print("  [dim]  - Would normalize and chunk[/dim]")
                would_normalize += 1
            
            # Check if note exists and cache inputs still match
            if not would_regenerate_note(record, force=force or force_all or only_stale):
                console.print("  [dim]  - Expected LLM cache hit[/dim]")
                would_cache_hit += 1
            else:
                console.print("  [dim]  - Would call LLM ({})[/dim]".format(config.LLM_PROVIDER))
                would_call_llm += 1
            
            continue
        
        # Step 1: Ingest (skip if --skip-ingest and chunks exist)
        if can_skip_ingest:
            console.print("  [dim]Skipping ingest/normalize (chunks exist)[/dim]")
        else:
            try:
                if record.source_type.value == "youtube":
                    youtube_ingestor.ingest(record)
                elif record.source_type.value == "webpage":
                    webpage_ingestor.ingest(record)
                elif record.source_type.value in {"markdown", "medium_markdown"}:
                    pass
                elif record.source_type.value in {"local_video", "local_audio", "local_transcript"}:
                    pass
                
                registry.update_status(record.id, ResourceStatus.RAW_SAVED)
                console.print("  [green]✓[/green] Ingested")
            except Exception as e:
                console.print(f"  [red]✗ Ingest failed: {e}[/red]")
                registry.update_status(record.id, ResourceStatus.FAILED_RETRYABLE, str(e))
                continue
            
            # Step 1.5: Enrich metadata
            try:
                if record.source_type.value == "youtube":
                    record = youtube_metadata_enricher.enrich(record)
                    if record.title:
                        console.print(f"  [dim]ℹ[/dim] Title: {record.title[:60]}")
                elif record.source_type.value == "webpage":
                    record = webpage_metadata_enricher.enrich(record)
                    if record.title:
                        console.print(f"  [dim]ℹ[/dim] Title: {record.title[:60]}")
                
                registry.update(record)
            except Exception as e:
                console.print(f"  [yellow]⚠ Metadata enrichment failed: {e}[/yellow]")
                # Continue even if metadata enrichment fails
            
            # Step 2: Normalize
            try:
                if record.source_type.value == "youtube":
                    youtube_normalizer.normalize(record)
                elif record.source_type.value == "webpage":
                    webpage_normalizer.normalize(record)
                elif record.source_type.value in {"markdown", "medium_markdown"}:
                    markdown_normalizer.normalize(record)
                elif record.source_type.value in {"local_video", "local_audio", "local_transcript"}:
                    transcript_media_normalizer.normalize(record)
                
                registry.update(record)
                console.print("  [green]✓[/green] Normalized")
            except Exception as e:
                console.print(f"  [red]✗ Normalize failed: {e}[/red]")
                registry.update_status(record.id, ResourceStatus.FAILED_RETRYABLE, str(e))
                continue
        
        # Step 3: Generate notes (if not already cached)
        try:
            if not provider_inst:
                provider_inst = get_provider()
            
            generator = get_note_generator(provider_inst)
            if force or force_all or only_stale:
                record.prompt_hash = None
                record.source_chunks_hash = None
            generator.generate(record)
            
            if record.status == ResourceStatus.LLM_CACHE_HIT:
                console.print("  [dim]✓ Cache hit (no LLM call)[/dim]")
            else:
                console.print("  [green]✓[/green] Generated notes")
            
            registry.update(record)
        except Exception as e:
            console.print(f"  [red]✗ Note generation failed: {e}[/red]")
            if record.status == ResourceStatus.FAILED_RETRYABLE:
                registry.update(record)
            else:
                registry.update_status(record.id, ResourceStatus.FAILED_RETRYABLE, str(e))
            continue
        
        # Mark as processed
        from datetime import datetime
        record.processed_at = datetime.utcnow()
        record.status = ResourceStatus.PROCESSED
        registry.update(record)
        
        console.print("  [green]✓[/green] Complete\n")
    
    if dry_run:
        console.print("\n[bold]Dry-Run Summary:[/bold]")
        console.print(f"  Resources to ingest: {would_ingest}")
        console.print(f"  Resources to normalize: {would_normalize}")
        console.print(f"  LLM calls needed: {would_call_llm}")
        console.print(f"  Cache hits expected: {would_cache_hit}")
        if would_need_manual:
            console.print(f"  Need manual Markdown: {would_need_manual}")
        console.print("\n[dim]No changes made (dry-run mode)[/dim]")
    else:
        console.print("[bold green]Processing complete![/bold green]")


@app.command()
def generate_notes(
    resource_id: Optional[str] = typer.Option(None, "--resource", "-r", help="Specific resource ID"),
    limit: Optional[int] = typer.Option(None, "--limit", "-n", help="Limit number of resources"),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation for LLM calls"),
    provider: Optional[str] = typer.Option(None, "--provider", help="Override LLM provider (mock, ollama_cloud, ollama_local, openai_compatible)"),
):
    """Generate LLM notes for processed resources.

    Use --provider to override the LLM_PROVIDER env var for this run only.
    """
    console.print("[bold blue]Generating notes...[/bold blue]\n")

    # Resolve --provider override
    if provider:
        config.LLM_PROVIDER = provider
        console.print(f"[dim]Provider overridden to: {provider}[/dim]")

    provider_inst = get_provider()
    generator = get_note_generator(provider_inst)
    
    if resource_id:
        # Generate for specific resource
        record = registry.get_by_id(resource_id)
        if not record:
            console.print(f"[red]Resource not found: {resource_id}[/red]")
            raise typer.Exit(1)
        
        try:
            generator.generate(record)
            registry.update(record)
            console.print(f"[green]✓[/green] Generated notes for {resource_id}")
        except Exception as e:
            console.print(f"[red]✗ Failed: {e}[/red]")
    else:
        # Get eligible records
        records = list(registry.get_all())
        eligible = [r for r in records if r.local_normalized_path]
        
        # Apply limit
        total_eligible = len(eligible)
        if limit and limit < total_eligible:
            eligible = eligible[:limit]
        
        console.print(f"Found {total_eligible} resource(s) with normalized content")
        if limit:
            console.print(f"Processing: {len(eligible)} (limited by --limit)")
        console.print()
        
        # Safety check for real LLM calls
        if config.LLM_PROVIDER != "mock":
            needs_llm = sum(1 for r in eligible if would_regenerate_note(r))
            if needs_llm > 2 and not yes:
                console.print(f"[yellow]Warning:[/yellow] About to generate notes for {needs_llm} resources using {config.LLM_PROVIDER}")
                console.print("This may consume cloud tokens.")
                console.print("Use --yes to continue or use LLM_PROVIDER=mock for testing.")
                raise typer.Exit(1)
        
        for record in eligible:
            try:
                generator.generate(record)
                registry.update(record)
                console.print(f"[green]✓[/green] {record.id}")
            except Exception as e:
                console.print(f"[red]✗[/red] {record.id}: {e}")


@app.command()
def regenerate_views():
    """Regenerate derived views and site docs without LLM calls."""
    console.print("[bold blue]Regenerating derived views...[/bold blue]\n")
    records = list(registry.get_all())
    manifest = generate_derived_views(records)
    site_path = site_builder.build(records)
    console.print(f"\n[green]✓[/green] Derived views regenerated: {site_path}")


@app.command("regenerate-derived")
def regenerate_derived():
    """Alias for regenerate-views."""
    regenerate_views()


@app.command("regenerate-revision")
def regenerate_revision():
    """Alias for generate-revision."""
    generate_revision()


@app.command("regenerate-notes")
def regenerate_notes_alias():
    """Alias for generate-notes."""
    generate_notes()


@app.command("generate-review-pages")
def generate_review_pages():
    """Generate static review dashboard pages without LLM calls."""
    records = list(registry.get_all())
    data = review_generator.generate(records)
    path = review_generator.save(data)
    console.print(f"[green]✓[/green] Review pages generated: {path}")


@app.command("generate-search-index")
def generate_search_index():
    """Generate static search indexes, Explorer, and Sources pages."""
    records = list(registry.get_all())
    indexes = search_index_generator.generate(records)
    path = search_index_generator.save(indexes)
    console.print(f"[green]✓[/green] Search index generated: {path}")


@app.command("build-chunk-index")
def build_chunk_index_cmd(
    refresh: bool = typer.Option(False, "--refresh", help="Rebuild from scratch (no-op here; the build is always full)"),
    include_source_type: Optional[List[str]] = typer.Option(
        None, "--include-source-type", help="Repeatable filter; only listed source types are indexed"
    ),
    resource_id: Optional[str] = typer.Option(
        None, "--resource-id", help="Index a single resource by id"
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit", help="Cap the number of resources processed"
    ),
    output_dir: Optional[Path] = typer.Option(
        None, "--output-dir", help="Override the processed/chunk_index/ output directory"
    ),
):
    """Build the deterministic chunk index (Prompt 27).

    Reads the per-resource ``chunks.jsonl`` files written by the
    normalizers (PDF, YouTube, webpage, markdown, local transcript,
    local audio, local video) and emits a uniform index of citeable
    chunks under ``processed/chunk_index/``.

    Outputs (deterministic, byte-stable across repeated runs):

    - ``processed/chunk_index/chunks.jsonl``
    - ``processed/chunk_index/chunks.json``
    - ``processed/chunk_index/manifest.json``
    - ``processed/chunk_index/stats.json`` (the only file that may
      drift between runs; it carries build timestamps)
    """
    started = datetime.now(timezone.utc)
    records = list(registry.get_all())
    result = build_chunk_index_fn(
        records,
        include_source_types=include_source_type,
        resource_id=resource_id,
        limit=limit,
    )
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = write_chunk_index_files(result, output_dir=output_dir)
    else:
        paths = write_chunk_index_files(result)

    # Also refresh the small public copy so the VitePress site can
    # serve the index. The public copy is a deterministic JSON
    # mirror of the data-dir files.
    public_paths = write_public_chunk_copy()

    finished = datetime.now(timezone.utc)
    duration = (finished - started).total_seconds()

    console.print("[green]✓[/green] Chunk index built")
    console.print(f"  Total chunks: {len(result.chunks)}")
    console.print(f"  Total resources indexed: {len(result.chunk_count_by_resource)}")
    console.print(f"  Output chunks.jsonl: {paths['chunks_jsonl']}")
    console.print(f"  Output chunks.json: {paths['chunks_json']}")
    console.print(f"  Output manifest.json: {paths['manifest']}")
    console.print(f"  Output stats.json: {paths['stats']}")
    console.print(f"  Public chunks.json: {public_paths['chunks_json']}")
    console.print(f"  Public manifest.json: {public_paths['manifest']}")
    console.print(f"  Warnings: {len(result.warnings)}")
    console.print(f"  Duration: {duration:.2f}s")


@app.command("generate-revision")
def generate_revision():
    """Generate revision pages and deterministic flashcards."""
    records = list(registry.get_all())
    data = revision_generator.generate(records)
    path = revision_generator.save(data)
    console.print(f"[green]✓[/green] Revision pages generated: {path}")


@app.command("generate-flashcards")
def generate_flashcards(
    provider: str = typer.Option("mock", "--provider", help="Provider for optional future generation"),
    topic: Optional[str] = typer.Option(None, "--topic", help="Optional topic slug"),
):
    """Generate deterministic flashcards; real providers are not called by default."""
    if provider != "mock":
        console.print("[yellow]Real-provider flashcard generation is not automatic; using deterministic extraction.[/yellow]")
    records = list(registry.get_all())
    if topic:
        records = [r for r in records if topic in topic_matches(r, read_note_for_cli(r))]
    data = revision_generator.generate(records)
    path = revision_generator.save(data)
    console.print(f"[green]✓[/green] Flashcards generated: {path / 'flashcards.json'}")


def read_note_for_cli(record) -> str:
    if record.generated_note_path and Path(record.generated_note_path).exists():
        return Path(record.generated_note_path).read_text(encoding="utf-8")
    return ""


@app.command("export-flashcards")
def export_flashcards(
    format: str = typer.Option("json", "--format", help="json or csv"),
):
    """Export flashcards for spaced repetition tools."""
    records = list(registry.get_all())
    data = revision_generator.generate(records)
    revision_generator.save(data)
    path = revision_generator.export(data, format)
    console.print(f"[green]✓[/green] Exported flashcards: {path}")


@app.command()
def test_llm(
    provider: str = typer.Option("mock", "--provider", help="Provider to smoke-test"),
):
    """Run a tiny LLM smoke test without touching resource data."""
    prompt = "Return exactly: ollama cloud works"
    if provider == "mock":
        llm = MockProvider()
    elif provider == "ollama_cloud":
        if not config.OLLAMA_CLOUD_API_KEY:
            console.print("[red]OLLAMA_API_KEY or OLLAMA_CLOUD_API_KEY is not set[/red]")
            raise typer.Exit(1)
        if not config.OLLAMA_CLOUD_MODEL:
            console.print("[red]OLLAMA_CLOUD_MODEL is not set[/red]")
            raise typer.Exit(1)
        llm = OllamaCloudProvider()
    else:
        console.print(f"[red]Unsupported test provider: {provider}[/red]")
        raise typer.Exit(1)

    response = llm.generate(prompt, temperature=0)
    console.print(f"LLM provider: {provider}")
    console.print(f"Model: {llm.model}")
    console.print(f"Response: {response[:100]}")


@app.command()
def build_site(
    refresh: bool = typer.Option(False, "--refresh", help="Regenerate derived views before building"),
):
    """Build the static VitePress site."""
    console.print("[bold blue]Building site...[/bold blue]\n")
    
    # Step 1: Generate supporting files
    records = list(registry.get_all())
    if refresh:
        generate_derived_views(records)
    
    # Step 2: Build site
    console.print("\nBuilding VitePress site...")
    site_path = site_builder.build(records)
    console.print(f"  [green]✓[/green] Site built: {site_path}")
    
    console.print("\n[bold green]Site build complete![/bold green]")
    console.print("\nTo view locally:")
    console.print("  cd site && npm install && npm run docs:dev")


@app.command("smoke-site")
def smoke_site():
    """Smoke-test the built static site for missing or blank pages.

    Checks that all expected generated pages exist, are non-empty,
    contain level-1 headings, and are not placeholder-only.
    Also validates that search JSON files exist and are valid JSON.
    """
    console.print("[bold blue]Smoking site...[/bold blue]\n")
    errors: list[tuple[str, str]] = []
    warnings: list[tuple[str, str]] = []
    site_dir = config.get_data_path("site_generated", "docs")
    repo_dir = Path(__file__).parent.parent / "site" / "docs"

    expected_pages = [
        ("Explorer page", site_dir / "explorer" / "index.md"),
        ("Sources page", site_dir / "sources" / "index.md"),
        ("Review page", site_dir / "review" / "index.md"),
        ("Revision page", site_dir / "revision" / "index.md"),
        ("Learn page", site_dir / "learn" / "index.md"),
        ("Tags page", site_dir / "tags" / "index.md"),
        ("Timeline page", site_dir / "timeline.md"),
        ("Gaps page", site_dir / "gaps.md"),
        ("Home page", site_dir / "index.md"),
        ("Graph viewer", site_dir / "graph" / "viewer.md"),
    ]

    for label, path in expected_pages:
        if not path.exists():
            errors.append((label, f"Missing: {path}"))
            continue
        content = path.read_text(encoding="utf-8")
        size = len(content)
        if size < 50:
            errors.append((label, f"Too small ({size} bytes): {path}"))
            continue
        has_h1 = any(line.startswith("# ") for line in content.splitlines())
        has_frontmatter_title = content.strip().startswith("---") and "title:" in content[:500]
        if not has_h1 and not has_frontmatter_title:
            errors.append((label, f"No level-1 heading or frontmatter title in: {path}"))
        placeholder_markers = [
            "_No ",
            "No ",
        ]
        first_200 = content[:200].lower()
        if first_200.startswith("# ") and any(m.lower() in content[:500].lower() for m in placeholder_markers):
            if size < 300:
                warnings.append((label, f"Looks like placeholder-only content ({size} bytes)"))

    expected_json = [
        ("Search all.json", site_dir / "public" / "search" / "all.json"),
        ("Search resources.json", site_dir / "public" / "search" / "resources.json"),
    ]

    for label, path in expected_json:
        if not path.exists():
            errors.append((label, f"Missing: {path}"))
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            items = data.get("items", [])
            if not items:
                warnings.append((label, f"Empty items array in {path}"))
            if label == "Search all.json":
                for item in items[:50]:
                    local_page = item.get("local_page", "")
                    if local_page.endswith(".md"):
                        errors.append(("Search index", f"local_page ends with .md: {local_page[:100]}"))
                    if local_page.startswith("/resources/") and not _resource_route_target_exists(local_page, site_dir):
                        errors.append(("Search index", f"local_page target missing: {local_page}"))
        except json.JSONDecodeError as exc:
            errors.append((label, f"Invalid JSON in {path}: {exc}"))

    explorer_path = site_dir / "explorer" / "index.md"
    if explorer_path.exists():
        explorer_content = explorer_path.read_text(encoding="utf-8")
        if "wiki-explorer" not in explorer_content:
            errors.append(("Explorer page", "Missing #wiki-explorer div"))
        if "## Resource summary" not in explorer_content:
            errors.append(("Explorer page", "Missing Resource summary section"))
        if "## Recent resources" not in explorer_content:
            errors.append(("Explorer page", "Missing Recent resources section"))
        if "const items = [" in explorer_content:
            errors.append(("Explorer page", "Contains inline 'const items = [...]' — should use fetch() instead"))
        if "search/all.json" not in explorer_content:
            errors.append(("Explorer page", "Does not reference search/all.json for data loading"))
        static_rows = explorer_content.count("| [")
        if static_rows < 1 and "| No items" not in explorer_content:
            warnings.append(("Explorer page", "Static fallback table has no resource rows"))
        if "Could not load search index. Check /search/all.json." not in explorer_content:
            warnings.append(("Explorer page", "Missing fetch error fallback message"))

    # Check resources/index.md for broken links
    resources_index = site_dir / "resources" / "index.md"
    if resources_index.exists():
        ri_content = resources_index.read_text(encoding="utf-8")
        if ".md)" in ri_content:
            errors.append(("Resources index", "Contains .md) resource links — should use route paths"))
        for line in ri_content.splitlines():
            if line.startswith("|"):
                unescaped_pipes = len(re.findall(r'(?<!\\)\|', line))
                if unescaped_pipes > 6:
                    errors.append(("Resources index", f"Broken table row (too many pipes?): {line[:120]}"))

    for label, rel in [
        ("Repo Explorer", Path("explorer") / "index.md"),
        ("Repo Home", Path("index.md")),
    ]:
        path = repo_dir / rel
        if not path.exists():
            warnings.append((label, f"Not synced to repo site: {path}"))

    # Check for duplicate topic display names
    topics_index = site_dir / "topics" / "index.md"
    if topics_index.exists():
        try:
            topics_content = topics_index.read_text(encoding="utf-8")
            import re as _re
            topic_names = _re.findall(r"- \[(.+?)\]", topics_content)
            seen_names: dict[str, str] = {}
            for name in topic_names:
                if name in seen_names:
                    errors.append(("Topic Map", f"Duplicate topic display name: '{name}' appears more than once"))
                else:
                    seen_names[name] = name
        except Exception as exc:
            warnings.append(("Topic Map", f"Could not check for duplicate topics: {exc}"))

    # Check for alias topic slugs in search index
    all_json_path = site_dir / "public" / "search" / "all.json"
    if all_json_path.exists():
        try:
            all_data = json.loads(all_json_path.read_text(encoding="utf-8"))
            from wiki.resource_utils import TOPIC_ALIASES
            alias_slugs = set(TOPIC_ALIASES.keys())
            for item in all_data.get("items", [])[:100]:
                item_id = item.get("id", "")
                if item_id.startswith("topic:"):
                    slug = item_id.replace("topic:", "")
                    if slug in alias_slugs:
                        errors.append(("Search index", f"Alias topic slug '{slug}' found in all.json — should be canonical only"))
        except Exception:
            pass

    # Check generation manifest
    manifest_path = config.get_data_path("processed", "generated_manifest.json")
    if not manifest_path.exists():
        warnings.append(("Generation manifest", "Missing generated_manifest.json. Run build-site --refresh."))
    else:
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not manifest_data.get("generated_at"):
                warnings.append(("Generation manifest", "Manifest missing generated_at timestamp."))
            if not manifest_data.get("resource_count"):
                warnings.append(("Generation manifest", "Manifest reports 0 resources."))
        except json.JSONDecodeError:
            errors.append(("Generation manifest", f"Invalid JSON: {manifest_path}"))

    # Check the knowledge graph (Prompt 23).
    graph_dir = site_dir / "public" / "graph"
    expected_graph = [
        ("Knowledge graph nodes.json", graph_dir / "nodes.json"),
        ("Knowledge graph edges.json", graph_dir / "edges.json"),
        ("Knowledge graph knowledge_graph.json", graph_dir / "knowledge_graph.json"),
    ]
    for label, path in expected_graph:
        if not path.exists():
            warnings.append((label, f"Missing: {path}"))
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append((label, f"Invalid JSON in {path}: {exc}"))
            continue
        if label == "Knowledge graph knowledge_graph.json":
            for required in ("schema_version", "nodes", "edges", "stats"):
                if required not in data:
                    errors.append((label, f"Missing key '{required}' in {path}"))
    # Run the graph validator on the on-disk files
    if (graph_dir / "nodes.json").exists() and (graph_dir / "edges.json").exists():
        try:
            from wiki.graph import iter_issues_from_files
            graph_issues = iter_issues_from_files(
                graph_dir / "nodes.json",
                graph_dir / "edges.json",
                knowledge_graph_path=graph_dir / "knowledge_graph.json",
            )
        except Exception as exc:
            warnings.append(("Knowledge graph", f"Validator load failed: {exc}"))
        else:
            for severity, code, message in graph_issues:
                if severity == "error":
                    errors.append(("Knowledge graph", f"{code}: {message}"))
                else:
                    warnings.append(("Knowledge graph", f"{code}: {message}"))

    # Prompt 25: check the graph viewer page contents.
    viewer_path = site_dir / "graph" / "viewer.md"
    if viewer_path.exists():
        try:
            viewer_content = viewer_path.read_text(encoding="utf-8")
        except Exception as exc:
            warnings.append(("Graph viewer", f"Read error: {exc}"))
        else:
            required_viewer_strings = (
                "public/graph/knowledge_graph.json",
                '<div id="graph-viewer">',
                'id="graph-search"',
                'id="graph-node-list"',
            )
            for needle in required_viewer_strings:
                if needle not in viewer_content:
                    warnings.append(
                        ("Graph viewer", f"Missing required marker: {needle!r}")
                    )

    # Prompt 27: check the chunk index JSON files.
    expected_chunk_json = [
        ("Chunk index chunks.json", site_dir / "public" / "chunks" / "chunks.json"),
        ("Chunk index manifest.json", site_dir / "public" / "chunks" / "manifest.json"),
    ]
    for label, path in expected_chunk_json:
        if not path.exists():
            errors.append((label, f"Missing: {path}"))
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append((label, f"Invalid JSON in {path}: {exc}"))

    # Prompt 27: check the chunks index page.
    chunks_index_page = site_dir / "chunks" / "index.md"
    if chunks_index_page.exists():
        try:
            chunks_index_content = chunks_index_page.read_text(encoding="utf-8")
            size = len(chunks_index_content)
            if size < 50:
                warnings.append(("Chunks index page", f"Too small ({size} bytes)"))
        except Exception as exc:
            warnings.append(("Chunks index page", f"Read error: {exc}"))

    if errors:
        console.print(f"[red]Smoke test found {len(errors)} error(s) and {len(warnings)} warning(s):[/red]\n")
        for label, msg in errors:
            console.print(f"  [red]✗[/red] {label}: {msg}")
        for label, msg in warnings:
            console.print(f"  [yellow]⚠[/yellow] {label}: {msg}")
        raise typer.Exit(1)
    elif warnings:
        console.print(f"[yellow]Smoke test passed with {len(warnings)} warning(s):[/yellow]\n")
        for label, msg in warnings:
            console.print(f"  [yellow]⚠[/yellow] {label}: {msg}")
    else:
        console.print("[green]✓[/green] Smoke test passed!")

    page_count = sum(1 for _, p in expected_pages if p.exists())
    json_count = sum(1 for _, p in expected_json if p.exists())
    chunk_json_count = sum(1 for _, p in expected_chunk_json if p.exists())
    console.print(f"  Pages checked: {page_count}/{len(expected_pages)}")
    console.print(f"  JSON files checked: {json_count}/{len(expected_json)}")
    console.print(f"  Chunk JSON files checked: {chunk_json_count}/{len(expected_chunk_json)}")


@app.command()
def validate(
    provider: Optional[str] = typer.Option(None, "--provider", help="Check staleness and provider-specific issues for this provider"),
):
    """Validate the wiki configuration and content.

    Use --provider to check for failed_retryable, provider mismatches,
    missing notes, and contract failures for a specific target provider.
    """
    console.print("[bold blue]Validating wiki...[/bold blue]\n")
    
    issues = []
    
    # Check .env not committed
    git_dir = Path(__file__).parent.parent / ".git"
    if git_dir.exists():
        pass
    
    # Check provider configuration
    if config.LLM_PROVIDER == "ollama_cloud":
        if not config.OLLAMA_CLOUD_API_KEY:
            issues.append(("error", "OLLAMA_API_KEY or OLLAMA_CLOUD_API_KEY not set"))
        if not config.OLLAMA_CLOUD_MODEL:
            issues.append(("error", "OLLAMA_CLOUD_MODEL not set"))
    
    # Check resources
    records = list(registry.get_all())

    expected_site_files = [
        ("review pages", site_builder.repo_site_dir / "review" / "index.md"),
        ("search resources.json", site_builder.repo_site_dir / "public" / "search" / "resources.json"),
        ("search all.json", site_builder.repo_site_dir / "public" / "search" / "all.json"),
        ("Explorer page", site_builder.repo_site_dir / "explorer" / "index.md"),
        ("Sources page", site_builder.repo_site_dir / "sources" / "index.md"),
        ("Revision page", site_builder.repo_site_dir / "revision" / "index.md"),
        ("Learn page", site_builder.repo_site_dir / "learn" / "index.md"),
        ("Tags page", site_builder.repo_site_dir / "tags" / "index.md"),
        ("Timeline page", site_builder.repo_site_dir / "timeline.md"),
        ("Gaps page", site_builder.repo_site_dir / "gaps.md"),
        ("graph viewer", site_builder.repo_site_dir / "graph" / "viewer.md"),
        ("chunks index page", site_builder.repo_site_dir / "chunks" / "index.md"),
        ("chunks public chunks.json", site_builder.repo_site_dir / "public" / "chunks" / "chunks.json"),
        ("chunks public manifest.json", site_builder.repo_site_dir / "public" / "chunks" / "manifest.json"),
    ]
    for label, path in expected_site_files:
        if not path.exists():
            issues.append(("warning", f"Missing generated {label}: {path}"))
            continue
        if path.suffix == ".json":
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                issues.append(("warning", f"{label} has invalid JSON: {exc}"))
                continue
            # Some JSON files are list payloads (chunk index, etc.);
            # others are dicts with an ``items`` key (search index).
            # Chunk index public files are dict manifests where
            # emptiness is reported as ``chunk_count == 0``.
            if isinstance(data, dict):
                if "items" in data and not data["items"]:
                    issues.append(
                        ("warning", f"{label} has empty items array")
                    )
                elif "chunk_count" in data and data.get("chunk_count", 0) == 0:
                    # chunk index manifest with no chunks: only
                    # warn if this is unexpected; keep silent to
                    # avoid noise on empty wikis.
                    pass
            elif isinstance(data, list):
                if not data:
                    issues.append(("warning", f"{label} has empty list"))
            else:
                issues.append(
                    (
                        "warning",
                        f"{label} root is not a list or dict: {type(data).__name__}",
                    )
                )
            continue
        try:
            content = path.read_text(encoding="utf-8")
            size = len(content)
            if size < 50:
                issues.append(("warning", f"{label} is too small ({size} bytes): {path}"))
            else:
                has_h1 = any(line.startswith("# ") for line in content.splitlines())
                has_frontmatter_title = content.strip().startswith("---") and "title:" in content[:500]
                if not has_h1 and not has_frontmatter_title:
                    issues.append(("warning", f"{label} has no level-1 heading: {path}"))
        except Exception as exc:
            issues.append(("warning", f"{label} read error: {exc}"))

    # Check for duplicate topic display names
    topics_index = site_builder.repo_site_dir / "topics" / "index.md"
    if topics_index.exists():
        try:
            topics_content = topics_index.read_text(encoding="utf-8")
            import re as _re
            topic_names = _re.findall(r"- \[(.+?)\]", topics_content)
            seen_names: dict[str, str] = {}
            for name in topic_names:
                if name in seen_names:
                    issues.append(("error", f"Duplicate topic display name: '{name}' appears more than once in Topic Map"))
                else:
                    seen_names[name] = name
        except Exception as exc:
            issues.append(("warning", f"Could not check for duplicate topics: {exc}"))

    # Check for alias topic slugs in search index
    all_json_alias_path = site_builder.repo_site_dir / "public" / "search" / "all.json"
    if all_json_alias_path.exists():
        try:
            all_data = json.loads(all_json_alias_path.read_text(encoding="utf-8"))
            from wiki.resource_utils import TOPIC_ALIASES
            alias_slugs = set(TOPIC_ALIASES.keys())
            for item in all_data.get("items", [])[:100]:
                item_id = item.get("id", "")
                if item_id.startswith("topic:"):
                    slug = item_id.replace("topic:", "")
                    if slug in alias_slugs:
                        issues.append(("error", f"Alias topic slug '{slug}' found in all.json — should be canonical only"))
        except json.JSONDecodeError as exc:
            issues.append(("warning", f"all.json has invalid JSON: {exc}"))

    # Check generation manifest staleness
    manifest_path = config.get_data_path("processed", "generated_manifest.json")
    if not manifest_path.exists():
        issues.append(("warning", "Missing generated_manifest.json. Run build-site --refresh."))
    else:
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_at = manifest_data.get("generated_at", "")
            if manifest_at:
                from datetime import timezone as _tz
                manifest_dt = datetime.fromisoformat(manifest_at.replace("Z", "+00:00")) if "T" in manifest_at else datetime.utcnow()
                for record in records:
                    if record.updated_at and record.updated_at > manifest_dt.replace(tzinfo=None):
                        issues.append(("warning", "Derived views may be stale. Run build-site --refresh."))
                        break
        except Exception:
            issues.append(("warning", "Invalid generated_manifest.json"))

    # Validate generated site pages for broken tables and .md links
    resources_index = site_builder.repo_site_dir / "resources" / "index.md"
    if resources_index.exists():
        try:
            ri_content = resources_index.read_text(encoding="utf-8")
            if ".md)" in ri_content:
                issues.append(("error", "Resources index contains .md) resource links — should use route paths"))
            for line_num, line in enumerate(ri_content.splitlines(), start=1):
                if line.startswith("|"):
                    unescaped_pipes = len(re.findall(r'(?<!\\)\|', line))
                    if unescaped_pipes > 6:
                        issues.append(("warning", f"Resources index line {line_num}: table row has too many unescaped pipes ({unescaped_pipes} cells)"))
        except Exception as exc:
            issues.append(("warning", f"Resources index read error: {exc}"))

    explorer_page = site_builder.repo_site_dir / "explorer" / "index.md"
    if explorer_page.exists():
        try:
            ex_content = explorer_page.read_text(encoding="utf-8")
            if "const items = [" in ex_content:
                issues.append(("error", "Explorer contains inline 'const items = [...]' — should use fetch() instead"))
            if "search/all.json" not in ex_content:
                issues.append(("warning", "Explorer does not reference search/all.json for data loading"))
            if "## Resource summary" not in ex_content:
                issues.append(("warning", "Explorer missing Resource summary section"))
            if "## Recent resources" not in ex_content:
                issues.append(("warning", "Explorer missing Recent resources section"))
            if "Could not load search index. Check /search/all.json." not in ex_content:
                issues.append(("warning", "Explorer missing exact search-index error fallback"))
        except Exception as exc:
            issues.append(("warning", f"Explorer page read error: {exc}"))

    all_json_path = site_builder.repo_site_dir / "public" / "search" / "all.json"
    if all_json_path.exists():
        try:
            all_data = json.loads(all_json_path.read_text(encoding="utf-8"))
            all_items = all_data.get("items", [])
            if not all_items:
                issues.append(("warning", "all.json has empty items array"))
            for item in all_items[:20]:
                local_page = item.get("local_page", "")
                if local_page.endswith(".md"):
                    issues.append(("error", f"all.json local_page ends with .md: {local_page[:80]}"))
                if local_page.startswith("/resources/") and not _resource_route_target_exists(local_page, site_builder.repo_site_dir):
                    issues.append(("error", f"all.json local_page target missing: {local_page}"))
        except json.JSONDecodeError as exc:
            issues.append(("warning", f"all.json has invalid JSON: {exc}"))
    else:
        issues.append(("warning", "Missing all.json — run build-site --refresh"))

    for record in records:
        if provider:
            target_model = ""
            if provider == "mock":
                target_model = "mock-model"
            elif provider == "ollama_cloud":
                target_model = config.OLLAMA_CLOUD_MODEL or ""
            elif provider == "ollama_local":
                target_model = config.OLLAMA_LOCAL_MODEL
            elif provider == "openai_compatible":
                target_model = config.OPENAI_COMPATIBLE_MODEL or ""

            reasons = stale_reasons(record, provider, target_model)
            if reasons:
                rid = record.id
                for reason in reasons:
                    issues.append(("warning", f"{rid}: {reason}"))
            if record.status.value == "failed_retryable":
                issues.append(("error", f"{record.id}: failed_retryable status"))
                if record.failure_reason:
                    issues.append(("warning", f"{record.id}: failure_reason: {record.failure_reason[:80]}"))
        else:
            if record.status == ResourceStatus.PROCESSED:
                if not record.llm_model:
                    issues.append(("warning", f"{record.id}: Missing LLM model in provenance"))
                if not record.prompt_version:
                    issues.append(("warning", f"{record.id}: Missing prompt version"))
        
        # Check for missing files
        if record.status.value in ["raw_saved", "normalized", "processed"]:
            if record.local_raw_path and not record.local_raw_path.exists():
                issues.append(("error", f"{record.id}: Missing raw files"))

        # Prompt 26: PDF records should always have raw and
        # normalized paths after `import-pdf` (the normalizer
        # runs as part of the command). This is a soft warning;
        # it never escalates to an error.
        if record.source_type == SourceType.PDF and record.status != ResourceStatus.FAILED_PERMANENT:
            if record.local_raw_path and not record.local_raw_path.exists():
                issues.append(("warning", f"{record.id}: PDF raw directory missing: {record.local_raw_path}"))
            if record.local_normalized_path and not record.local_normalized_path.exists():
                issues.append(("warning", f"{record.id}: PDF normalized directory missing: {record.local_normalized_path}"))

        # Check for debug failed notes
        if record.status.value == "failed_retryable":
            debug_dir = config.get_data_path("debug", "failed_notes", record.id)
            if debug_dir.exists() and any(debug_dir.iterdir()):
                issues.append(("warning", f"{record.id}: debug failed_notes directory exists"))

    # Check the knowledge graph (Prompt 23)
    graph_dir = site_builder.repo_site_dir / "public" / "graph"
    nodes_path = graph_dir / "nodes.json"
    edges_path = graph_dir / "edges.json"
    knowledge_graph_path = graph_dir / "knowledge_graph.json"
    if not nodes_path.exists():
        issues.append(("warning", f"Missing knowledge graph: {nodes_path}. Run build-site --refresh."))
    if not edges_path.exists():
        issues.append(("warning", f"Missing knowledge graph: {edges_path}. Run build-site --refresh."))
    if nodes_path.exists() or edges_path.exists():
        try:
            from wiki.graph import iter_issues_from_files
            graph_issues = iter_issues_from_files(
                nodes_path, edges_path, knowledge_graph_path=knowledge_graph_path
            )
        except Exception as exc:
            issues.append(("warning", f"Could not load graph validator: {exc}"))
        else:
            for severity, code, message in graph_issues:
                issues.append((severity, f"graph: {code}: {message}"))

    # Prompt 25: check the graph viewer page contents.
    viewer_repo_path = site_builder.repo_site_dir / "graph" / "viewer.md"
    if viewer_repo_path.exists():
        try:
            viewer_content = viewer_repo_path.read_text(encoding="utf-8")
            if "public/graph/knowledge_graph.json" not in viewer_content:
                issues.append(
                    (
                        "warning",
                        "Graph viewer does not reference /public/graph/knowledge_graph.json",
                    )
                )
        except Exception as exc:
            issues.append(("warning", f"Graph viewer read error: {exc}"))

    # Prompt 27: check the chunk index files.
    try:
        from wiki.chunks import iter_chunk_index_issues
        from wiki.chunks.export import chunk_index_output_paths
        chunk_paths = chunk_index_output_paths()
        if chunk_paths["chunks_json"].exists() or chunk_paths["chunks_jsonl"].exists():
            try:
                chunk_issues = list(
                    iter_chunk_index_issues(
                        chunks_jsonl_path=chunk_paths["chunks_jsonl"],
                        chunks_json_path=chunk_paths["chunks_json"],
                        manifest_path=chunk_paths["manifest"],
                    )
                )
            except Exception as exc:
                issues.append(("warning", f"chunk_index: validator crashed: {exc}"))
            else:
                for severity, code, message in chunk_issues:
                    issues.append((severity, f"chunk_index: {code}: {message}"))
    except Exception as exc:  # pragma: no cover - defensive
        issues.append(("warning", f"chunk_index: could not import validator: {exc}"))

    # Prompt 27: check the chunks index Markdown page.
    chunks_index_page = site_builder.repo_site_dir / "chunks" / "index.md"
    if chunks_index_page.exists():
        try:
            chunks_content = chunks_index_page.read_text(encoding="utf-8")
            if "public/chunks/chunks.json" not in chunks_content:
                issues.append(
                    (
                        "warning",
                        "Chunks index page does not reference /public/chunks/chunks.json",
                    )
                )
        except Exception as exc:
            issues.append(("warning", f"Chunks index read error: {exc}"))

    # Print results
    if issues:
        error_count = sum(1 for s, _ in issues if s == "error")
        warning_count = sum(1 for s, _ in issues if s == "warning")
        console.print(f"[yellow]Found {len(issues)} issue(s):[/yellow]  [red]{error_count} errors[/red], [yellow]{warning_count} warnings[/yellow]\n")
        for severity, message in issues:
            icon = "[red]✗[/red]" if severity == "error" else "[yellow]⚠[/yellow]"
            console.print(f"  {icon} {message}")
    else:
        console.print("[green]✓[/green] All checks passed!")


@app.command()
def full_run():
    """Run the complete pipeline."""
    console.print("[bold blue]Running full pipeline...[/bold blue]\n")
    
    # Step 1: Process new
    console.print("[bold]Step 1:[/bold] Processing new resources")
    process_new()
    
    # Step 2: Build site
    console.print("\n[bold]Step 2:[/bold] Building site")
    build_site(refresh=True)
    
    # Step 3: Validate
    console.print("\n[bold]Step 3:[/bold] Validating")
    validate()
    
    console.print("\n[bold green]Full pipeline complete![/bold green]")


@app.command()
def import_markdown(
    file: Path = typer.Option(..., "--file", "-f", help="Path to Markdown file"),
    original_url: Optional[str] = typer.Option(None, "--url", "-u", help="Original URL if available"),
):
    """Import a manually saved Markdown file."""
    console.print(f"[bold blue]Importing Markdown:[/bold blue] {file}")
    
    if not file.exists():
        console.print(f"[red]✗[/red] File not found: {file}")
        raise typer.Exit(1)
    
    # Read content and canonicalize
    content = file.read_text(encoding="utf-8")
    identity = deduplicator.canonicalize_markdown(content, original_url)
    
    # Check for duplicate
    existing = registry.get_by_canonical_id(identity.canonical_id)
    if existing:
        console.print(f"[yellow]⚠[/yellow] Duplicate content: {existing.id}")
        return
    
    # Insert and ingest
    record = registry.insert(identity, status=ResourceStatus.NEW)
    record = markdown_ingestor.ingest(file, record, original_url)
    registry.update(record)
    
    console.print(f"[green]✓[/green] Imported: {record.id}")


def _title_from_markdown(content: str, fallback: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped.lstrip("#").strip()
    return fallback


def _insert_identity_or_get(identity: ResourceIdentity) -> tuple[ResourceRecord, bool]:
    existing = registry.get_by_canonical_id(identity.canonical_id)
    if existing:
        return existing, False
    return registry.insert(identity, status=ResourceStatus.NEW), True


@app.command("import-medium-markdown")
def import_medium_markdown(
    file: Path = typer.Option(..., "--file", "-f", help="Path to copied Medium Markdown"),
    original_url: str = typer.Option(..., "--original-url", help="Original Medium URL"),
    title: Optional[str] = typer.Option(None, "--title", help="Optional title override"),
):
    """Import manually copied/exported Medium Markdown."""
    path = file.expanduser().resolve()
    if not path.exists():
        console.print(f"[red]✗[/red] File not found: {path}")
        raise typer.Exit(1)

    content = path.read_text(encoding="utf-8")
    frontmatter, _body = markdown_ingestor.parse_frontmatter(content)
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    canonical_id = f"medium_markdown:{content_hash}"
    existing = registry.get_by_canonical_id(canonical_id)
    if existing:
        console.print(f"[yellow]⚠[/yellow] Duplicate Medium Markdown: {existing.id}")
        return

    identity = ResourceIdentity(
        source_type=SourceType.MEDIUM_MARKDOWN,
        canonical_id=canonical_id,
        original_url=original_url,
        normalized_url=frontmatter.get("original_url") or original_url,
        content_hash=content_hash,
    )
    record = registry.insert(identity, status=ResourceStatus.NEW)
    record.title = title or frontmatter.get("title") or _title_from_markdown(content, path.stem)
    record.author = frontmatter.get("author")
    record.tags = list(frontmatter.get("tags") or [])
    if frontmatter.get("user_read_at"):
        try:
            record.user_consumed_at = datetime.fromisoformat(str(frontmatter["user_read_at"]))
        except ValueError:
            pass
    raw_dir = config.get_data_path("raw", "markdown", "medium", content_hash[:8])
    raw_dir.mkdir(parents=True, exist_ok=True)
    Storage.write_text(content, raw_dir / "source.md")
    Storage.write_json(
        {
            "content_hash": content_hash,
            "canonical_id": canonical_id,
            "original_file": str(path),
            "original_url": original_url,
            "platform": "medium",
            "has_frontmatter": bool(frontmatter),
            "frontmatter_keys": list(frontmatter.keys()),
        },
        raw_dir / "metadata.json",
    )
    record.local_raw_path = raw_dir
    record.extra.update({"platform": "medium", "manual_markdown": True})
    record = markdown_normalizer.normalize(record)
    registry.update(record)
    console.print(f"[green]✓[/green] Imported Medium Markdown: {record.id}")


@app.command("add-media")
def add_media(
    file: Path = typer.Option(..., "--file", "-f", help="Path to local audio/video file"),
):
    """Add a local audio/video file to the registry without copying it into Git."""
    path = file.expanduser().resolve()
    try:
        built = media_ingestor.build_record(path)
    except Exception as exc:
        console.print(f"[red]✗[/red] {exc}")
        raise typer.Exit(1) from exc

    identity = ResourceIdentity(
        source_type=built.source_type,
        canonical_id=built.canonical_id,
        original_url=built.original_url,
        normalized_url=built.normalized_url,
        content_hash=built.content_hash,
    )
    existing = registry.get_by_canonical_id(identity.canonical_id)
    if existing:
        console.print(f"[yellow]⚠[/yellow] Duplicate media skipped: {existing.id}")
        return

    record = registry.insert(identity, status=ResourceStatus.NEW)
    built.first_seen_at = record.first_seen_at
    built.last_seen_at = record.last_seen_at
    registry.update(built)
    console.print(f"[green]✓[/green] Added media: {built.id}")
    console.print(f"[dim]Transcription status: {built.extra.get('transcription_status')}[/dim]")


@app.command("import-pdf")
def import_pdf(
    file: Path = typer.Option(..., "--file", "-f", help="Path to a local PDF file"),
    title: Optional[str] = typer.Option(None, "--title", help="Optional title override"),
    source_url: Optional[str] = typer.Option(None, "--source-url", help="Optional source URL"),
    tags: Optional[str] = typer.Option(None, "--tags", help="Comma-separated tags"),
    copy_file: bool = typer.Option(
        False,
        "--copy-file/--no-copy-file",
        help="Copy the PDF into the data directory under media/pdfs/",
    ),
    force: bool = typer.Option(False, "--force", help="Re-ingest even if the resource already exists"),
):
    """Import a local PDF file as a new resource.

    The PDF is read locally with pypdf; pages are extracted
    into text and stored under the external data directory.
    Encrypted or scanned PDFs are not supported in this prompt.
    """
    path = file.expanduser().resolve()
    if not path.exists() or not path.is_file():
        console.print(f"[red]✗[/red] PDF not found: {path}")
        raise typer.Exit(1)
    if path.suffix.lower() != ".pdf":
        console.print(f"[red]✗[/red] Not a .pdf file: {path}")
        raise typer.Exit(1)

    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]

    try:
        record = pdf_ingestor.build_record(
            path,
            title=title,
            source_url=source_url,
            tags=tag_list,
            copy_file=copy_file,
        )
    except PdfEncryptedError as exc:
        console.print(f"[red]✗[/red] PDF is encrypted and cannot be read: {path} ({exc})")
        raise typer.Exit(1)
    except FileNotFoundError as exc:
        console.print(f"[red]✗[/red] {exc}")
        raise typer.Exit(1)
    except ValueError as exc:
        console.print(f"[red]✗[/red] {exc}")
        raise typer.Exit(1)
    except Exception as exc:  # pypdf PdfReadError and friends
        console.print(f"[red]✗[/red] Could not read PDF: {path} ({exc})")
        raise typer.Exit(1)

    existing = registry.get_by_canonical_id(record.canonical_id)
    if existing and not force:
        console.print(f"[yellow]⚠[/yellow] Duplicate PDF skipped: {existing.id}")
        return

    if existing and force:
        record.id = existing.id
        record.first_seen_at = existing.first_seen_at
        registry.update(record)
    else:
        identity = ResourceIdentity(
            source_type=SourceType.PDF,
            canonical_id=record.canonical_id,
            original_url=record.original_url,
            normalized_url=record.normalized_url,
            content_hash=record.content_hash,
        )
        inserted = registry.insert(identity, status=ResourceStatus.NEW)
        record.id = inserted.id
        record.first_seen_at = inserted.first_seen_at
        record.last_seen_at = inserted.last_seen_at

    record = pdf_normalizer.normalize(record)
    registry.update(record)
    console.print(f"[green]✓[/green] Imported PDF: {record.id}")


@app.command("transcribe-media")
def transcribe_media(
    resource_id: str = typer.Option(..., "--resource-id", "--resource", help="Media resource ID"),
    provider: str = typer.Option("whisper", "--provider", help="ASR provider: whisper, faster_whisper, mock"),
):
    """Extract audio and transcribe a local media resource."""
    record = registry.get_by_id(resource_id)
    if not record:
        console.print(f"[red]Resource not found: {resource_id}[/red]")
        raise typer.Exit(1)
    if record.source_type not in {SourceType.LOCAL_AUDIO, SourceType.LOCAL_VIDEO}:
        console.print(f"[red]Resource is not local audio/video: {record.source_type.value}[/red]")
        raise typer.Exit(1)

    raw_dir = Path(record.local_raw_path or config.get_data_path("raw", "media", record.content_hash or resource_id.split(":", 1)[-1]))
    raw_dir.mkdir(parents=True, exist_ok=True)
    original_path = Path(record.extra.get("original_path") or record.original_url.removeprefix("local://"))
    audio_path = raw_dir / "audio.wav"
    try:
        extract_audio_to_wav(original_path, audio_path)
        asr = get_asr_provider(provider)
        result = asr.transcribe(audio_path)
    except Exception as exc:
        record.extra["transcription_status"] = "failed_retryable"
        record.extra["transcription_failure_reason"] = str(exc)
        registry.update(record)
        console.print(f"[red]✗ Transcription failed:[/red] {exc}")
        raise typer.Exit(1) from exc

    segments = [segment.to_dict() for segment in result.segments]
    Storage.write_json({"text": result.text, "language": result.language, "segments": segments}, raw_dir / "transcript.json")
    with (raw_dir / "segments.jsonl").open("w", encoding="utf-8") as handle:
        for segment in segments:
            handle.write(json.dumps(segment, ensure_ascii=False) + "\n")
    Storage.write_text(
        "\n".join(f"[{segment['start']:.2f}] {segment['text']}" for segment in segments) + "\n",
        raw_dir / "transcript.md",
    )
    record.local_raw_path = raw_dir
    record.extra.update({
        "audio_path": str(audio_path),
        "transcript_path": str(raw_dir / "transcript.json"),
        "transcription_status": "complete",
        "transcription_provider": asr.provider_name,
        "asr_model": asr.model,
        "asr_task": asr.task,
    })
    record = transcript_media_normalizer.normalize(record)
    registry.update(record)
    console.print(f"[green]✓[/green] Transcribed media: {record.id}")


@app.command("import-transcript")
def import_transcript(
    file: Path = typer.Option(..., "--file", "-f", help="Path to transcript text file"),
    source_title: Optional[str] = typer.Option(None, "--source-title", help="Optional source title"),
    source_url: Optional[str] = typer.Option(None, "--source-url", help="Optional source URL"),
):
    """Import an existing local transcript and normalize it into timestamp chunks."""
    path = file.expanduser().resolve()
    if not path.exists():
        console.print(f"[red]✗[/red] File not found: {path}")
        raise typer.Exit(1)

    content = path.read_text(encoding="utf-8")
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    canonical_id = f"transcript:{content_hash}"
    existing = registry.get_by_canonical_id(canonical_id)
    if existing:
        console.print(f"[yellow]⚠[/yellow] Duplicate transcript skipped: {existing.id}")
        return

    identity = ResourceIdentity(
        source_type=SourceType.LOCAL_TRANSCRIPT,
        canonical_id=canonical_id,
        original_url=source_url or f"local://{path}",
        normalized_url=source_url or f"local://{path}",
        content_hash=content_hash,
    )
    record = registry.insert(identity, status=ResourceStatus.NEW)
    raw_dir = config.get_data_path("raw", "transcript", content_hash[:8])
    raw_dir.mkdir(parents=True, exist_ok=True)
    segments = parse_transcript_text(content)
    Storage.write_text(content, raw_dir / "transcript.txt")
    Storage.write_json({"segments": segments}, raw_dir / "transcript.json")
    Storage.write_json(
        {
            "source_title": source_title or path.stem,
            "source_url": source_url,
            "content_hash": content_hash,
            "original_file": str(path),
            "segment_count": len(segments),
        },
        raw_dir / "metadata.json",
    )
    record.title = source_title or path.stem
    record.local_raw_path = raw_dir
    record.extra.update({
        "media_type": "local_transcript",
        "original_path": str(path),
        "transcript_path": str(raw_dir / "transcript.json"),
        "transcription_status": "imported",
        "transcription_provider": "manual",
        "asr_model": "manual",
        "asr_task": "transcribe",
    })
    record = transcript_media_normalizer.normalize(record)
    registry.update(record)
    console.print(f"[green]✓[/green] Imported transcript: {record.id}")


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(file.stat().st_size for file in path.rglob("*") if file.is_file())


@app.command()
def doctor(
    check_llm: bool = typer.Option(False, "--check-llm", help="Run LLM smoke test"),
    check_asr: bool = typer.Option(False, "--check-asr", help="Check optional ASR imports"),
):
    """Check local environment readiness."""
    checks: list[tuple[str, bool, str]] = []
    checks.append(("Python >= 3.11", sys.version_info >= (3, 11), sys.version.split()[0]))
    for module in ["typer", "pydantic", "httpx", "bs4", "yaml", "rich"]:
        try:
            __import__(module)
            checks.append((f"dependency {module}", True, "ok"))
        except ImportError as exc:
            checks.append((f"dependency {module}", False, str(exc)))
    checks.append(("ffmpeg", shutil.which("ffmpeg") is not None, shutil.which("ffmpeg") or "missing"))
    checks.append(("data directory exists", config.LLM_WIKI_DATA_DIR.exists(), str(config.LLM_WIKI_DATA_DIR)))
    repo_root = Path(__file__).resolve().parents[1]
    outside_repo = not str(config.LLM_WIKI_DATA_DIR).startswith(str(repo_root))
    checks.append(("data directory outside repo", outside_repo, str(config.LLM_WIKI_DATA_DIR)))
    checks.append(("registry exists", registry.db_path.exists(), str(registry.db_path)))
    checks.append(("VitePress package.json", (Path("site") / "package.json").exists(), "site/package.json"))
    checks.append(("node_modules", (Path("site") / "node_modules").exists(), "site/node_modules"))
    for error in config.validate():
        checks.append((f"config: {error}", False, ""))
    if check_asr:
        for module in ["whisper", "faster_whisper"]:
            try:
                __import__(module)
                checks.append((f"optional ASR {module}", True, "installed"))
            except ImportError:
                checks.append((f"optional ASR {module}", False, "not installed"))
    if check_llm:
        try:
            MockProvider().generate("Return ok")
            checks.append(("mock LLM smoke test", True, "ok"))
        except Exception as exc:
            checks.append(("mock LLM smoke test", False, str(exc)))
    for label, ok, detail in checks:
        console.print(f"{'[green]✓[/green]' if ok else '[yellow]⚠[/yellow]'} {label}: {detail}")


@app.command("status-report")
def status_report():
    """Generate Markdown and JSON operational status reports."""
    records = list(registry.get_all())
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    reports_dir = config.get_data_path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    type_counts = Counter(record.source_type.value for record in records)
    status_counts = Counter(record.status.value for record in records)
    provider_counts = Counter(record.llm_provider or "none" for record in records)
    review_required = sum(bool(record.extra.get("requires_human_review")) for record in records)
    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "resource_count": len(records),
        "type_counts": dict(type_counts),
        "status_counts": dict(status_counts),
        "provider_counts": dict(provider_counts),
        "review_required_count": review_required,
        "learn_pages": len(list(config.get_data_path("processed", "learn").glob("*.md"))) if config.get_data_path("processed", "learn").exists() else 0,
        "flashcards": len((Storage.read_json(config.get_data_path("processed", "revision", "flashcards.json")).get("items", []) if config.get_data_path("processed", "revision", "flashcards.json").exists() else [])),
        "source_urls": len([record for record in records if record.original_url]),
        "storage_bytes": {
            "raw": _directory_size(config.get_data_path("raw")),
            "normalized": _directory_size(config.get_data_path("normalized")),
            "processed": _directory_size(config.get_data_path("processed")),
        },
        "latest_added": [record.id for record in sorted(records, key=lambda r: r.first_seen_at, reverse=True)[:10]],
        "latest_processed": [record.id for record in sorted([r for r in records if r.processed_at], key=lambda r: r.processed_at, reverse=True)[:10]],
    }
    json_path = reports_dir / f"status_report_{timestamp}.json"
    md_path = reports_dir / f"status_report_{timestamp}.md"
    Storage.write_json(report, json_path)
    lines = ["# Status Report", "", f"Generated: {report['generated_at']}", "", f"Total resources: {len(records)}", "", "## Resource count by type", ""]
    lines.extend(f"- {key}: {value}" for key, value in report["type_counts"].items())
    lines.extend(["", "## Resource count by status", ""])
    lines.extend(f"- {key}: {value}" for key, value in report["status_counts"].items())
    lines.extend(["", "## Provider counts", ""])
    lines.extend(f"- {key}: {value}" for key, value in report["provider_counts"].items())
    lines.extend(["", f"Review required: {review_required}", f"Learn pages: {report['learn_pages']}", f"Flashcards: {report['flashcards']}", f"Source URLs: {report['source_urls']}"])
    Storage.write_text("\n".join(lines) + "\n", md_path)
    console.print(f"[green]✓[/green] Status report: {md_path}")


@app.command()
def backup(
    include_media: bool = typer.Option(False, "--include-media", help="Include derived media files"),
    include_debug: bool = typer.Option(False, "--include-debug", help="Include debug failed outputs"),
    output: Optional[Path] = typer.Option(None, "--output", help="Output tar.gz path"),
):
    """Backup external wiki data, not the Git repository."""
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backups_dir = config.get_data_path("backups")
    backups_dir.mkdir(parents=True, exist_ok=True)
    out = (output.expanduser().resolve() if output else backups_dir / f"llm_wiki_backup_{timestamp}.tar.gz")
    include_roots = ["registry", "raw", "normalized", "processed", "reports"]

    def allowed(path: Path) -> bool:
        rel = path.relative_to(config.LLM_WIKI_DATA_DIR)
        parts = set(rel.parts)
        if "tmp" in parts or "cache" in parts:
            return False
        if "debug" in parts and not include_debug:
            return False
        if not include_media and path.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".mp3", ".wav", ".m4a", ".aac", ".flac"}:
            return False
        return True

    with tarfile.open(out, "w:gz") as tar:
        for root_name in include_roots:
            root = config.get_data_path(root_name)
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if path.is_file() and allowed(path):
                    tar.add(path, arcname=str(path.relative_to(config.LLM_WIKI_DATA_DIR)))
    console.print(f"[green]✓[/green] Backup created: {out}")


@app.command()
def restore(
    file: Path = typer.Option(..., "--file", help="Backup tar.gz file"),
    target_dir: Optional[Path] = typer.Option(None, "--target-dir", help="Target data directory"),
    yes: bool = typer.Option(False, "--yes", help="Overwrite non-empty target"),
):
    """Restore a backup into a target data directory."""
    backup_path = file.expanduser().resolve()
    if not backup_path.exists():
        console.print(f"[red]Backup not found:[/red] {backup_path}")
        raise typer.Exit(1)
    target = (target_dir or config.LLM_WIKI_DATA_DIR).expanduser().resolve()
    with tarfile.open(backup_path, "r:gz") as tar:
        members = tar.getmembers()
        console.print(f"Backup contains {len(members)} entries")
        console.print(f"Target: {target}")
        if target.exists() and any(target.iterdir()) and not yes:
            console.print("[yellow]Target is non-empty. Re-run with --yes to restore.[/yellow]")
            raise typer.Exit(1)
        target.mkdir(parents=True, exist_ok=True)
        tar.extractall(target)
    if not (target / "registry" / "resources.sqlite").exists():
        console.print("[red]Restore completed but registry/resources.sqlite is missing[/red]")
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] Restored backup to {target}")


@app.command()
def daily(
    provider: str = typer.Option("mock", "--provider", help="mock or ollama_cloud"),
    yes: bool = typer.Option(False, "--yes", help="Allow real-provider processing"),
    skip_llm: bool = typer.Option(False, "--skip-llm", help="Skip LLM processing"),
    limit: Optional[int] = typer.Option(None, "--limit", help="Limit resources processed"),
):
    """Safe daily workflow."""
    if provider == "ollama_cloud" and not yes:
        console.print("[yellow]Refusing real Ollama Cloud daily run without --yes. Use --provider mock or --skip-llm.[/yellow]")
        raise typer.Exit(1)
    pending = list(registry.get_pending())
    console.print(f"Pending/new resources: {len(pending)}")
    for record in list(registry.get_all()):
        if record.source_type.value == "webpage":
            try:
                updated = webpage_metadata_enricher.enrich(record)
                registry.update(updated)
            except Exception:
                pass
    if not skip_llm:
        process_new(
            force=False,
            force_all=False,
            dry_run=False,
            limit=limit,
            resource_id=None,
            yes=yes,
            allow_untitled=True,
            skip_quality_gate=True,
            skip_ingest=False,
            only_stale=False,
            provider=provider,
        )
    records = list(registry.get_all())
    generate_derived_views(records)
    site_builder.build(records)
    validate(provider=None)
    console.print("[green]✓[/green] Daily workflow complete")


@app.command("normalize-registry-providers")
def normalize_registry_providers():
    """Normalize stored llm_provider values to canonical form.

    Rewrites legacy values like 'ollamacloud' to 'ollama_cloud',
    'ollamalocal' to 'ollama_local', and 'openaicompatible' to
    'openai_compatible'.  Safe and idempotent.
    """
    console.print("[bold blue]Normalizing registry provider names...[/bold blue]\n")

    all_records = list(registry.get_all())
    updated = 0

    for record in all_records:
        raw = record.llm_provider
        normalized = normalize_provider_name(raw)
        if raw and raw != normalized:
            record.llm_provider = normalized
            registry.update(record)
            updated += 1
            console.print(f"  {raw} → {normalized}  ({record.id})")

    if updated:
        console.print(f"\n[green]✓[/green] Normalized {updated} record(s)")
    else:
        console.print("[green]✓[/green] All provider names already canonical")


if __name__ == "__main__":
    app()
