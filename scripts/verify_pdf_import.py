"""Manual verification script for Prompt 26 PDF ingestion.

This script imports a real research PDF (default: the "Attention
Is All You Need" paper from arXiv 1706.03762) and exercises the
full ``import-pdf`` -> ``build-site`` -> ``smoke-site`` ->
``validate`` flow against an isolated data directory.

Per ``prompt26.md`` §"Real PDF verification requirement", the
script:

- imports a real downloaded PDF (or skips gracefully if it is
  not present on disk);
- checks the extracted text contains expected phrases
  (Attention Is All You Need, Transformer, Scaled
  Dot-Product Attention);
- confirms ``pages.json``, ``chunks.json``, and
  ``metadata.json`` exist with the expected keys;
- runs ``build-site --refresh`` after the import;
- runs ``smoke-site`` and ``validate`` and asserts the exit
  codes are zero;
- checks the graph JSON includes the imported PDF as a
  resource node;
- checks the graph viewer still builds after the import.

Usage (from inside ``harish-llm-wiki/``):

    ./.venv/bin/python scripts/verify_pdf_import.py
    ./.venv/bin/python scripts/verify_pdf_import.py --pdf /path/to/some.pdf

The script does NOT depend on network access. If the default
PDF is not present and no ``--pdf`` argument is supplied, the
script exits 0 with an informational message rather than
failing. This keeps it safe to invoke from CI without
network egress.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


DEFAULT_PDF = Path.home() / "llm-wiki-data" / "test-pdfs" / "attention-is-all-you-need.pdf"
EXPECTED_PHRASES = (
    "Attention Is All You Need",
    "Transformer",
    "Scaled Dot-Product Attention",
)


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pdf",
        type=Path,
        default=DEFAULT_PDF,
        help="Path to a real PDF to import (default: %(default)s)",
    )
    parser.add_argument(
        "--download-url",
        default="https://arxiv.org/pdf/1706.03762.pdf",
        help="URL to download the test PDF from if not on disk",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="If the PDF is missing, attempt to download it from --download-url",
    )
    parser.add_argument(
        "--keep-data-dir",
        action="store_true",
        help="Print the temp data dir at the end instead of removing it",
    )
    return parser


def _download(pdf: Path, url: str) -> bool:
    """Try to download the PDF using ``urllib`` (stdlib only)."""
    try:
        import urllib.request
    except ImportError:
        return False
    pdf.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
            data = response.read()
    except Exception as exc:  # pragma: no cover - network-dependent
        print(f"  download failed: {exc}", file=sys.stderr)
        return False
    if not data.startswith(b"%PDF"):
        print("  downloaded bytes do not look like a PDF", file=sys.stderr)
        return False
    pdf.write_bytes(data)
    return True


def _run(cmd: list[str], *, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run a subprocess, raising on failure with a clear message."""
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def main() -> int:
    parser = _build_argparser()
    args = parser.parse_args()

    pdf = args.pdf
    if not pdf.exists():
        if args.download:
            print(f"PDF not found at {pdf}, attempting to download from {args.download_url}")
            if not _download(pdf, args.download_url):
                print("Could not download the test PDF; skipping.")
                return 0
        else:
            print(
                f"PDF not found at {pdf}. Re-run with --download to attempt to\n"
                "fetch it, or supply a different --pdf path. Skipping."
            )
            return 0

    # Use a fresh temp data dir so the verification does not
    # touch the user's real wiki.
    tmp_dir = Path(tempfile.mkdtemp(prefix="verify_pdf_import_"))
    print(f"Using isolated data dir: {tmp_dir}")
    env = {
        **__import__("os").environ,
        "LLM_WIKI_DATA_DIR": str(tmp_dir),
    }

    try:
        from wiki.config import config
        from wiki.ingest.pdf import extract_pages, pdf_ingestor
        from wiki.normalize.pdf import pdf_normalizer

        # Override the in-process config so direct calls
        # (build_record, normalize) write to the temp dir.
        config.LLM_WIKI_DATA_DIR = tmp_dir
        config.ensure_directories()

        # 1. Ingest + normalize via the public modules.
        print("\n[1/7] Ingesting PDF and writing raw + normalized files")
        record = pdf_ingestor.build_record(
            pdf,
            title="Attention Is All You Need",
            tags=["transformer", "attention"],
        )
        record = pdf_normalizer.normalize(record)
        raw_dir = Path(record.local_raw_path)
        norm_dir = Path(record.local_normalized_path)
        processed_dir = (
            tmp_dir / "processed" / "pdfs" / (record.content_hash or "")[:8]
        )
        for label, target in (
            ("raw pages.json", raw_dir / "pages.json"),
            ("raw extracted.txt", raw_dir / "extracted.txt"),
            ("raw metadata.json", raw_dir / "metadata.json"),
            ("normalized transcript.md", norm_dir / "transcript.md"),
            ("normalized chunks.jsonl", norm_dir / "chunks.jsonl"),
            ("processed pages.json", processed_dir / "pages.json"),
            ("processed chunks.json", processed_dir / "chunks.json"),
        ):
            assert target.exists(), f"missing {label}: {target}"
            print(f"  ok: {label} ({target.stat().st_size} bytes)")

        # 2. Verify the expected phrases.
        print("\n[2/7] Verifying expected phrases in extracted text")
        pages = extract_pages(pdf)
        joined = "\n".join(page["text"] for page in pages)
        missing = [phrase for phrase in EXPECTED_PHRASES if phrase not in joined]
        assert not missing, f"missing expected phrases: {missing}"
        for phrase in EXPECTED_PHRASES:
            print(f"  ok: '{phrase}' found in extracted text")

        # 3. Verify metadata.json shape.
        print("\n[3/7] Verifying metadata.json shape")
        meta = json.loads((raw_dir / "metadata.json").read_text(encoding="utf-8"))
        assert "page_count" in meta, "metadata.json missing page_count"
        assert "extraction_method" in meta, "metadata.json missing extraction_method"
        assert meta["extraction_method"] == "pypdf"
        print(f"  ok: page_count={meta['page_count']}, extraction_method={meta['extraction_method']}")

        # 4. Insert the record into the registry via the CLI.
        print("\n[4/7] Importing PDF via the wiki import-pdf CLI")
        cli_runner = subprocess.run(
            [
                sys.executable,
                "-m",
                "wiki",
                "import-pdf",
                "--file",
                str(pdf),
                "--title",
                "Attention Is All You Need",
                "--tags",
                "transformer,attention",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO_ROOT),
        )
        print(cli_runner.stdout)
        assert "pdf:" in cli_runner.stdout, "import-pdf did not print a pdf:<id>"

        # 5. Run build-site --refresh.
        print("\n[5/7] Running build-site --refresh")
        _run(
            [sys.executable, "-m", "wiki", "build-site", "--refresh"],
            env=env,
        )

        # 6. Run smoke-site and validate.
        print("\n[6/7] Running smoke-site and validate")
        _run([sys.executable, "-m", "wiki", "smoke-site"], env=env)
        _run([sys.executable, "-m", "wiki", "validate"], env=env)

        # 7. Check the graph JSON includes the imported PDF.
        print("\n[7/7] Checking graph JSON includes the imported PDF")
        public_graph = (
            tmp_dir / "site_generated" / "docs" / "public" / "graph"
        )
        nodes = json.loads((public_graph / "nodes.json").read_text(encoding="utf-8"))
        resource_nodes = [
            n for n in nodes
            if n.get("type") == "resource"
            and n.get("metadata", {}).get("source_type") == "pdf"
        ]
        assert resource_nodes, "no PDF resource node in graph nodes.json"
        for node in resource_nodes:
            print(f"  ok: graph node id={node['id']} source_type=pdf")
        bundle = json.loads(
            (public_graph / "knowledge_graph.json").read_text(encoding="utf-8")
        )
        bundle_resource_nodes = [
            n for n in bundle["nodes"]
            if n.get("type") == "resource"
            and n.get("metadata", {}).get("source_type") == "pdf"
        ]
        assert bundle_resource_nodes, (
            "no PDF resource node in knowledge_graph.json bundle"
        )

        # 8. Check the graph viewer page is present.
        viewer = tmp_dir / "site_generated" / "docs" / "graph" / "viewer.md"
        assert viewer.exists(), f"graph viewer page missing: {viewer}"
        size = viewer.stat().st_size
        print(f"  ok: graph viewer present ({size} bytes)")

        print("\n[OK] All real-PDF verification checks passed.")
        return 0
    except subprocess.CalledProcessError as exc:
        print("\n[FAIL] subprocess failed:", exc)
        print("stdout:", exc.stdout)
        print("stderr:", exc.stderr)
        return 1
    except AssertionError as exc:
        print(f"\n[FAIL] {exc}")
        return 1
    finally:
        if not args.keep_data_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        else:
            print(f"\nKept data dir: {tmp_dir}")


if __name__ == "__main__":
    sys.exit(main())
