"""Generate the small synthetic PDF fixture used by Prompt 26 tests.

This script is **not** part of the runtime test suite. It only
exists so a maintainer can re-create ``tests/fixtures/synthetic.pdf``
without re-running pytest.

The generated PDF is committed as a binary file. Do not re-run
this unless you want to regenerate the fixture; the bytes are
intentionally stable for byte-deterministic hashing.

Usage (from inside ``harish-llm-wiki/``):

    ./.venv/bin/python tests/fixtures/_make_synthetic_pdf.py
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import (
    ContentStream,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)


PAGES_TEXT = [
    (
        "Page 1: Introduction to Transformers",
        [
            "Page 1: Introduction to Transformers",
            "This is the first page of the synthetic test PDF.",
            "It mentions Transformer and attention mechanisms in plain prose.",
            "Transformer models use self-attention to model sequence data.",
        ],
    ),
    (
        "Page 2: Scaled Dot-Product Attention",
        [
            "Page 2: Scaled Dot-Product Attention",
            "Scaled Dot-Product Attention is a key component of the Transformer.",
            "It computes attention weights as softmax(QK^T / sqrt(d_k)) V.",
            "The query, key, and value matrices come from the input embeddings.",
        ],
    ),
    (
        "Page 3: Multi-Head Attention",
        [
            "Page 3: Multi-Head Attention",
            "Multi-Head Attention projects the input into multiple heads.",
            "Each head runs Scaled Dot-Product Attention in parallel.",
            "Concatenating the head outputs and projecting back yields the result.",
        ],
    ),
]


def _build_page(writer: PdfWriter, lines: list[str]) -> None:
    """Add a single PDF page with the given text lines."""
    page = writer.add_blank_page(width=612, height=792)
    # Build the content stream. We use the built-in /Helvetica
    # font which pypdf's writer inserts by default for blank pages.
    pieces: list[bytes] = [b"BT\n/F1 14 Tf\n72 720 Td\n"]
    for index, line in enumerate(lines):
        if index == 0:
            pieces.append(f"({_escape(line)}) Tj\n".encode("latin-1"))
        else:
            pieces.append(f"0 -22 Td\n({_escape(line)}) Tj\n".encode("latin-1"))
    pieces.append(b"ET\n")
    content_bytes = b"".join(pieces)

    content_obj = DecodedStreamObject()
    content_obj.set_data(content_bytes)
    # Wrap the stream so pypdf resolves indirect references.
    cs = ContentStream(content_obj, page)
    page[NameObject("/Contents")] = cs

    # Add the /Resources dict with the Helvetica font.
    resources = DictionaryObject()
    font_dict = DictionaryObject()
    font_dict[NameObject("/F1")] = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    resources[NameObject("/Font")] = font_dict
    page[NameObject("/Resources")] = resources


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf_bytes() -> bytes:
    """Build the synthetic PDF in memory and return its bytes."""
    writer = PdfWriter()
    for _title, lines in PAGES_TEXT:
        _build_page(writer, lines)
    writer.add_metadata(
        {
            "/Title": "Synthetic Test PDF for Prompt 26",
            "/Author": "harish-llm-wiki test suite",
            "/Subject": "Fixture for PDF ingestion tests",
        }
    )
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def main(target: Path | None = None) -> Path:
    output = target or (Path(__file__).parent / "synthetic.pdf")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(build_pdf_bytes())
    print(f"Wrote {output} ({output.stat().st_size} bytes)")
    return output


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
