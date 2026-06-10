#!/usr/bin/env python
"""Lightweight static route verification for the VitePress site (Prompt 28).

Verifies that the expected generated site files / routes exist. The
script is intentionally simple: file-existence checks plus a JSON
parse for ``.json`` files. It does **not** require a browser, network
access, or Playwright. It runs against the in-repo site dir
(``site/docs``) by default and accepts ``--site-dir`` for tests.

Routes checked
--------------

- ``/graph/`` -> ``graph/index.md``
- ``/graph/viewer`` -> ``graph/viewer.md``
- ``/graph/explore`` -> ``graph/explore.md``
- ``/graph/graphify`` -> ``graph/graphify.md``
- ``/graph/resource-relationships`` -> ``graph/resource-relationships.md``
- ``/chunks/`` -> ``chunks/index.md``
- ``/public/chunks/chunks.json`` -> ``public/chunks/chunks.json``
- ``/public/chunks/manifest.json`` -> ``public/chunks/manifest.json``
- ``/search/bm25`` -> ``search/bm25.md`` (Prompt 28 BM25 report page)
- ``/public/search/bm25_index.json`` -> ``public/search/bm25_index.json``
- ``/public/search/bm25_manifest.json`` -> ``public/search/bm25_manifest.json``
- ``/search/vector`` -> ``search/vector.md`` (Prompt 29 vector report page)
- ``/public/search/vector_index.json`` -> ``public/search/vector_index.json``
- ``/public/search/vector_manifest.json`` -> ``public/search/vector_manifest.json``

Usage
-----

    .venv/bin/python scripts/verify_site_static_routes.py
    .venv/bin/python scripts/verify_site_static_routes.py --site-dir /path/to/site/docs
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Tuple


#: Default in-repo site docs directory. Computed from this script's
#: location so the test suite and the developer machine agree.
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SITE_DIR = REPO_ROOT / "site" / "docs"


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--site-dir",
        type=Path,
        default=DEFAULT_SITE_DIR,
        help="Path to the site/docs directory to verify (default: %(default)s)",
    )
    return parser


def _expected_routes(site_dir: Path) -> List[Tuple[str, Path]]:
    """Return the list of ``(label, path)`` pairs to check."""
    return [
        ("/graph/", site_dir / "graph" / "index.md"),
        ("/graph/explore", site_dir / "graph" / "explore.md"),
        ("/graph/graphify", site_dir / "graph" / "graphify.md"),
        ("/graph/viewer", site_dir / "graph" / "viewer.md"),
        ("/graph/resource-relationships", site_dir / "graph" / "resource-relationships.md"),
        ("/chunks/", site_dir / "chunks" / "index.md"),
        ("/public/chunks/chunks.json", site_dir / "public" / "chunks" / "chunks.json"),
        ("/public/chunks/manifest.json", site_dir / "public" / "chunks" / "manifest.json"),
        ("/search/bm25", site_dir / "search" / "bm25.md"),
        ("/public/search/bm25_index.json", site_dir / "public" / "search" / "bm25_index.json"),
        ("/public/search/bm25_manifest.json", site_dir / "public" / "search" / "bm25_manifest.json"),
        # Prompt 29 additions
        ("/search/vector", site_dir / "search" / "vector.md"),
        ("/public/search/vector_index.json", site_dir / "public" / "search" / "vector_index.json"),
        ("/public/search/vector_manifest.json", site_dir / "public" / "search" / "vector_manifest.json"),
        # Prompt 30 additions
        ("/search/retrieval", site_dir / "search" / "retrieval.md"),
    ]


def main() -> int:
    parser = _build_argparser()
    args = parser.parse_args()
    site_dir = Path(args.site_dir).expanduser().resolve()

    if not site_dir.exists():
        print(f"FAIL: site directory does not exist: {site_dir}", file=sys.stderr)
        return 1

    routes = _expected_routes(site_dir)
    ok_count = 0
    failures: list[tuple[str, Path, str]] = []

    for label, path in routes:
        if not path.exists():
            failures.append((label, path, "missing"))
            print(f"  [red]✗[/red] {label}: Missing: {path}")
            continue
        # For .json files, also assert the JSON parses.
        if path.suffix == ".json":
            try:
                with path.open("r", encoding="utf-8") as handle:
                    json.load(handle)
            except json.JSONDecodeError as exc:
                failures.append((label, path, f"invalid JSON: {exc}"))
                print(f"  [red]✗[/red] {label}: Invalid JSON: {exc}")
                continue
        ok_count += 1
        print(f"  [green]✓[/green] {label}")

    print()
    print(f"Routes checked: {ok_count}/{len(routes)}")
    if failures:
        print(f"Missing: {len(failures)}", file=sys.stderr)
        for label, _path, reason in failures:
            print(f"  - {label}: {reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
