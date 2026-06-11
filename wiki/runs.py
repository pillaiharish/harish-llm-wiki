"""Append-only processing run and token ledger storage."""

from __future__ import annotations

import json
import math
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wiki.config import config
from wiki.llm.prompts import PROMPT_VERSION
from wiki.schemas import ResourceRecord

RUNS_VERSION = "prompt52e"


def utc_now() -> str:
    """Return an ISO UTC timestamp."""

    return datetime.now(timezone.utc).isoformat()


def runs_dir() -> Path:
    """Return the local processed/runs directory."""

    path = config.get_data_path("processed", "runs")
    path.mkdir(parents=True, exist_ok=True)
    return path


def processing_runs_path() -> Path:
    return runs_dir() / "processing_runs.jsonl"


def token_ledger_path() -> Path:
    return runs_dir() / "token_ledger.jsonl"


def make_run_id(resource_id: str = "", operation: str = "run") -> str:
    """Create a collision-resistant run identifier."""

    safe_operation = re.sub(r"[^a-zA-Z0-9_-]+", "-", operation).strip("-") or "run"
    safe_resource = re.sub(r"[^a-zA-Z0-9_-]+", "-", resource_id).strip("-")[:40] or "resource"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{stamp}-{safe_operation}-{safe_resource}-{uuid.uuid4().hex[:8]}"


def append_jsonl(path: Path, item: dict[str, Any]) -> None:
    """Append one JSON object to a JSONL file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, sort_keys=True, ensure_ascii=False, default=str) + "\n")


def read_jsonl(path: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    """Read JSONL rows, skipping malformed rows defensively."""

    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    if limit is not None:
        return rows[-limit:]
    return rows


def estimate_tokens(text: str | None) -> int:
    """Estimate token count deterministically without external tokenizers."""

    if not text:
        return 0
    stripped = text.strip()
    if not stripped:
        return 0
    wordish = re.findall(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]", stripped)
    # This intentionally overestimates long unbroken strings a little, which is
    # better for local cost awareness than undercounting.
    length_estimate = math.ceil(len(stripped) / 4)
    return max(len(wordish), length_estimate, 1)


def parse_provider_usage(provider: str, usage: Any) -> dict[str, Any]:
    """Normalize token usage reported by common provider response shapes."""

    if not isinstance(usage, dict):
        return {}

    source = usage.get("usage") if isinstance(usage.get("usage"), dict) else usage
    input_tokens = _first_int(
        source,
        "prompt_tokens",
        "input_tokens",
        "prompt_eval_count",
        "prompt_count",
    )
    output_tokens = _first_int(
        source,
        "completion_tokens",
        "output_tokens",
        "eval_count",
        "completion_count",
    )
    total_tokens = _first_int(source, "total_tokens", "total_count")
    if total_tokens is None and (input_tokens is not None or output_tokens is not None):
        total_tokens = int(input_tokens or 0) + int(output_tokens or 0)

    if input_tokens is None and output_tokens is None and total_tokens is None:
        return {}

    return {
        "provider": provider,
        "provider_input_tokens": input_tokens,
        "provider_output_tokens": output_tokens,
        "provider_total_tokens": total_tokens,
    }


def _first_int(source: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def estimate_cost(provider: str, model: str, total_tokens: int, usage_source: str) -> float:
    """Return local estimated spend.

    The project has no pricing table yet, so Prompt52E records zero spend for
    mock/local providers and an explicit zero-dollar unknown estimate for cloud
    providers. Later prompts can add user-configured price tables.
    """

    return 0.0


def build_token_entry(
    *,
    run_id: str,
    resource_id: str,
    operation: str,
    provider: str,
    model: str,
    prompt_version: str,
    prompt_hash: str | None,
    prompt: str | None,
    system: str | None,
    output: str | None,
    provider_usage: Any = None,
    status: str = "success",
    started_at: str | None = None,
    completed_at: str | None = None,
) -> dict[str, Any]:
    """Build a token ledger entry for one generation call."""

    estimated_input = estimate_tokens(system) + estimate_tokens(prompt)
    estimated_output = estimate_tokens(output)
    estimated_total = estimated_input + estimated_output
    parsed_usage = parse_provider_usage(provider, provider_usage)

    provider_input = parsed_usage.get("provider_input_tokens")
    provider_output = parsed_usage.get("provider_output_tokens")
    provider_total = parsed_usage.get("provider_total_tokens")
    usage_source = "provider_reported" if provider_total is not None else "estimated"
    input_tokens = provider_input if provider_input is not None else estimated_input
    output_tokens = provider_output if provider_output is not None else estimated_output
    total_tokens = provider_total if provider_total is not None else estimated_total

    return {
        "version": RUNS_VERSION,
        "run_id": run_id,
        "resource_id": resource_id,
        "operation": operation,
        "provider": provider,
        "model": model,
        "prompt_version": prompt_version,
        "prompt_hash": prompt_hash or "",
        "status": status,
        "started_at": started_at or utc_now(),
        "completed_at": completed_at or utc_now(),
        "estimated_input_tokens": estimated_input,
        "estimated_output_tokens": estimated_output,
        "estimated_total_tokens": estimated_total,
        "provider_input_tokens": provider_input,
        "provider_output_tokens": provider_output,
        "provider_total_tokens": provider_total,
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "total_tokens": int(total_tokens or 0),
        "usage_source": usage_source,
        "estimated_cost": estimate_cost(provider, model, int(total_tokens or 0), usage_source),
    }


def append_processing_run(run: dict[str, Any]) -> dict[str, Any]:
    """Append a processing run row."""

    append_jsonl(processing_runs_path(), run)
    return run


def append_token_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Append a token ledger row."""

    append_jsonl(token_ledger_path(), entry)
    return entry


def record_generation_run(
    *,
    record: ResourceRecord,
    operation: str,
    provider: str,
    model: str,
    prompt_hash: str | None,
    prompt: str | None,
    system: str | None,
    output: str | None,
    provider_usage: Any = None,
    status: str = "success",
    error: str | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
) -> dict[str, Any]:
    """Record one provider generation attempt and token ledger entry."""

    run_id = make_run_id(record.id, operation)
    started = started_at or utc_now()
    completed = completed_at or utc_now()
    token_entry = build_token_entry(
        run_id=run_id,
        resource_id=record.id,
        operation=operation,
        provider=provider,
        model=model,
        prompt_version=PROMPT_VERSION,
        prompt_hash=prompt_hash,
        prompt=prompt,
        system=system,
        output=output,
        provider_usage=provider_usage,
        status=status,
        started_at=started,
        completed_at=completed,
    )
    run = {
        "version": RUNS_VERSION,
        "run_id": run_id,
        "resource_id": record.id,
        "operation": operation,
        "provider": provider,
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "prompt_hash": prompt_hash or "",
        "status": status,
        "started_at": started,
        "completed_at": completed,
        "error": error or "",
        "input_tokens": token_entry["input_tokens"],
        "output_tokens": token_entry["output_tokens"],
        "total_tokens": token_entry["total_tokens"],
        "usage_source": token_entry["usage_source"],
        "estimated_cost": token_entry["estimated_cost"],
    }
    append_processing_run(run)
    append_token_entry(token_entry)
    return run


def record_cache_hit(
    *,
    record: ResourceRecord,
    provider: str,
    model: str,
    prompt_hash: str | None,
) -> dict[str, Any]:
    """Record a cache hit without adding token ledger cost."""

    now = utc_now()
    run = {
        "version": RUNS_VERSION,
        "run_id": make_run_id(record.id, "note_generation_cache_hit"),
        "resource_id": record.id,
        "operation": "note_generation_cache_hit",
        "provider": provider,
        "model": model,
        "prompt_version": record.prompt_version or PROMPT_VERSION,
        "prompt_hash": prompt_hash or record.prompt_hash or "",
        "status": "cache_hit",
        "started_at": now,
        "completed_at": now,
        "error": "",
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "usage_source": "none",
        "estimated_cost": 0.0,
    }
    return append_processing_run(run)


def record_dry_run_plan(
    *,
    record: ResourceRecord,
    provider: str,
    model: str,
    would_ingest: bool,
    would_normalize: bool,
    would_call_llm: bool,
    would_cache_hit: bool,
    would_need_manual: bool = False,
) -> dict[str, Any]:
    """Record a zero-cost dry-run plan row without token ledger entries."""

    now = utc_now()
    run = {
        "version": RUNS_VERSION,
        "run_id": make_run_id(record.id, "process_new_dry_run"),
        "resource_id": record.id,
        "operation": "process_new_dry_run",
        "provider": provider,
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "prompt_hash": record.prompt_hash or "",
        "status": "planned",
        "started_at": now,
        "completed_at": now,
        "error": "",
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "usage_source": "none",
        "estimated_cost": 0.0,
        "would_ingest": would_ingest,
        "would_normalize": would_normalize,
        "would_call_llm": would_call_llm,
        "would_cache_hit": would_cache_hit,
        "would_need_manual": would_need_manual,
    }
    return append_processing_run(run)


def read_processing_runs(*, limit: int | None = None) -> list[dict[str, Any]]:
    return read_jsonl(processing_runs_path(), limit=limit)


def read_token_ledger(*, limit: int | None = None) -> list[dict[str, Any]]:
    return read_jsonl(token_ledger_path(), limit=limit)


def get_run(run_id: str) -> dict[str, Any] | None:
    for run in read_processing_runs():
        if run.get("run_id") == run_id:
            return run
    return None


def token_ledger_summary() -> dict[str, Any]:
    """Summarize token ledger rows."""

    entries = read_token_ledger()
    by_provider: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"entries": 0, "total_tokens": 0, "estimated_cost": 0.0}
    )
    by_model: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"entries": 0, "total_tokens": 0, "estimated_cost": 0.0}
    )
    usage_sources: Counter[str] = Counter()

    total_tokens = 0
    estimated_cost = 0.0
    for entry in entries:
        tokens = int(entry.get("total_tokens") or 0)
        cost = float(entry.get("estimated_cost") or 0.0)
        provider = str(entry.get("provider") or "unknown")
        model = str(entry.get("model") or "unknown")
        source = str(entry.get("usage_source") or "unknown")
        total_tokens += tokens
        estimated_cost += cost
        usage_sources[source] += 1
        by_provider[provider]["entries"] += 1
        by_provider[provider]["total_tokens"] += tokens
        by_provider[provider]["estimated_cost"] += cost
        by_model[model]["entries"] += 1
        by_model[model]["total_tokens"] += tokens
        by_model[model]["estimated_cost"] += cost

    runs = read_processing_runs()
    statuses = Counter(str(run.get("status") or "unknown") for run in runs)
    operations = Counter(str(run.get("operation") or "unknown") for run in runs)

    return {
        "version": RUNS_VERSION,
        "run_count": len(runs),
        "ledger_entry_count": len(entries),
        "success_count": statuses.get("success", 0),
        "failed_count": statuses.get("failed", 0),
        "cache_hit_count": statuses.get("cache_hit", 0),
        "total_tokens": total_tokens,
        "estimated_cost": round(estimated_cost, 8),
        "status_counts": dict(sorted(statuses.items())),
        "operation_counts": dict(sorted(operations.items())),
        "usage_source_counts": dict(sorted(usage_sources.items())),
        "by_provider": dict(sorted(by_provider.items())),
        "by_model": dict(sorted(by_model.items())),
    }
