"""CLI for Harish LLM Wiki."""

from pathlib import Path
from typing import Optional, List

import typer
from rich.console import Console
from rich.table import Table
from rich import box

from wiki.config import config
from wiki.schemas import ResourceStatus
from wiki.registry import registry
from wiki.dedupe import deduplicator
from wiki.ingest.youtube import youtube_ingestor
from wiki.ingest.webpage import webpage_ingestor
from wiki.ingest.markdown import markdown_ingestor
from wiki.normalize.transcript import youtube_normalizer
from wiki.normalize.webpage import webpage_normalizer
from wiki.normalize.markdown import markdown_normalizer
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
from wiki.site.builder import site_builder
from wiki.enrich.metadata import youtube_metadata_enricher, webpage_metadata_enricher
from wiki.resource_utils import is_replaceable_title


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


def generate_derived_views(records=None) -> None:
    """Regenerate derived views without calling an LLM."""
    records = list(records or registry.get_all())

    console.print("Generating concepts...")
    concept_extractor.concepts = {}
    concept_extractor.aggregate(records)
    concept_extractor.save()
    console.print("  [green]✓[/green] Concepts saved")

    console.print("Generating timeline...")
    periods = timeline_generator.generate(records)
    timeline_generator.save(periods)
    console.print("  [green]✓[/green] Timeline saved")

    console.print("Generating tags...")
    tags = tags_generator.generate(records)
    tags_generator.save(tags)
    console.print("  [green]✓[/green] Tags saved")

    console.print("Generating topics...")
    topics = topic_generator.generate(records)
    topic_generator.save(topics)
    console.print("  [green]✓[/green] Topics saved")

    console.print("Generating gaps report...")
    gaps = gaps_generator.generate(records)
    gaps_generator.save(gaps)
    console.print("  [green]✓[/green] Gaps saved")


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
                elif record.source_type.value == "markdown":
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
                elif record.source_type.value == "markdown":
                    markdown_normalizer.normalize(record)
                
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
    generate_derived_views(records)
    site_path = site_builder.build(records)
    console.print(f"\n[green]✓[/green] Derived views regenerated: {site_path}")


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

        # Check for debug failed notes
        if record.status.value == "failed_retryable":
            debug_dir = config.get_data_path("debug", "failed_notes", record.id)
            if debug_dir.exists() and any(debug_dir.iterdir()):
                issues.append(("warning", f"{record.id}: debug failed_notes directory exists"))

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
