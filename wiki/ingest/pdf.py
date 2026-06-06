"""Local PDF ingestion.

Extracts page-wise text from a local PDF file using pypdf,
writes deterministic per-page JSON, the concatenated
extracted text, and a metadata block under the external data
directory, and builds a fully populated
:class:`wiki.schemas.ResourceRecord` with
``source_type == SourceType.PDF``.

This module is the foundation for future chunk-index (Prompt 27),
BM25 (Prompt 28), vector search (Prompt 29), and grounded answer
(Prompt 33) work. It performs **no** LLM, embedding, or OCR work.

See ``wiki/ingest/markdown.py`` and ``wiki/ingest/media.py`` for the
sibling modules whose shape this one mirrors.
"""

from __future__ import annotations

import hashlib
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from wiki.config import config
from wiki.schemas import ResourceRecord, ResourceStatus, SourceType
from wiki.storage import Storage


PDF_CHUNK_TARGET_CHARS = 2000
PDF_CHUNK_MAX_CHARS = 4000
PDF_EXTRACT_METHOD = "pypdf"

PDF_EXTENSIONS = {".pdf"}


class PdfEncryptedError(RuntimeError):
    """Raised when a PDF cannot be read because it is encrypted.

    The CLI catches this and prints a friendly error before
    exiting with code 1.
    """


def make_pdf_resource_id(content_hash: str) -> str:
    """Return the canonical PDF resource id ``pdf:<sha256>``.

    The same content_hash always returns the same id, so
    importing the same file twice yields the same record id and
    the dedup check in the CLI returns the existing record.
    """
    if not content_hash or not isinstance(content_hash, str):
        raise ValueError("content_hash must be a non-empty string")
    return f"pdf:{content_hash}"


def make_pdf_chunk_id(resource_id: str, chunk_index: int) -> str:
    """Return a deterministic chunk id like ``pdf:<hash>-p0007``.

    The chunk_index is zero-padded to four digits, matching the
    convention used by the other chunker modules.
    """
    if chunk_index < 0:
        raise ValueError("chunk_index must be non-negative")
    return f"{resource_id}-p{chunk_index:04d}"


def sha256_file(path: Path) -> str:
    """Stream the file and return a SHA-256 hex digest.

    Matches ``wiki.ingest.media.sha256_file`` byte-for-byte so
    existing tooling works unchanged.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _open_reader(path: Path):
    """Open a PDF with pypdf; returns the reader (may be encrypted)."""
    from pypdf import PdfReader

    return PdfReader(str(path))


def _load_reader(path: Path):
    """Open a PDF with pypdf and translate encryption errors.

    In pypdf 6.x, encrypted files can be opened by the
    constructor (``PdfReader(...)``) without raising; the
    :class:`pypdf.errors.FileNotDecryptedError` is raised later
    when the reader tries to dereference any object. We surface
    the encryption failure at the first iteration step instead
    of leaking it from ``extract_pages``.
    """
    from pypdf.errors import FileNotDecryptedError, PdfReadError

    reader = _open_reader(path)
    if reader.is_encrypted:
        # We deliberately do not try to decrypt with an empty
        # password; this prompt never ingests encrypted PDFs.
        raise PdfEncryptedError(
            f"PDF is encrypted and cannot be read: {path}"
        )
    try:
        # Touching any property forces lazy parsing in pypdf 6.x
        # and surfaces the decryption error here, where we can
        # translate it.
        _ = reader.pages
    except FileNotDecryptedError as exc:
        # Caught before PdfReadError because FileNotDecryptedError
        # is a subclass of PdfReadError in pypdf 4.x/5.x/6.x.
        raise PdfEncryptedError(
            f"PDF is encrypted and cannot be read: {path}"
        ) from exc
    except PdfReadError as exc:
        message = str(exc).lower()
        if "encrypt" in message or "password" in message:
            raise PdfEncryptedError(
                f"PDF is encrypted and cannot be read: {path}"
            ) from exc
        raise
    return reader


def extract_pages(pdf_path: Path) -> list[dict[str, Any]]:
    """Return ``[{"page": 1, "text": "..."}, ...]`` using pypdf.

    Each entry has integer ``page`` (1-indexed) and a non-None
    ``text`` string. Pages whose text comes back empty (e.g.
    image scans) are still included, with ``text=""`` and a note
    returned separately in :func:`extract_pages_warnings`.

    Raises :class:`PdfEncryptedError` if the file is encrypted.
    Other :class:`pypdf.errors.PdfReadError` exceptions are
    re-raised unchanged.
    """
    reader = _load_reader(pdf_path)
    pages: list[dict[str, Any]] = []
    for index, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception:
            # A single page with an extraction error shouldn't
            # abort the whole import. Record empty text and
            # continue; the warning will be captured by
            # extract_pages_warnings.
            text = ""
        pages.append({"page": index + 1, "text": text})
    return pages


def extract_pages_warnings(pages: list[dict[str, Any]]) -> list[str]:
    """Return human-readable warnings, sorted by page number.

    The list is deterministic and includes a string for every
    page whose extracted text is empty.
    """
    warnings: list[str] = []
    for entry in pages:
        if not str(entry.get("text") or "").strip():
            warnings.append(f"page {entry['page']} has no extractable text")
    return warnings


def _is_oversized(text: str, max_chars: int) -> bool:
    return len(text) > max_chars


def chunk_pages(
    pages: list[dict[str, Any]],
    *,
    resource_id: str,
    title: str | None = None,
    file_path: str | None = None,
    target_chars: int = PDF_CHUNK_TARGET_CHARS,
    max_chars: int = PDF_CHUNK_MAX_CHARS,
) -> list[dict[str, Any]]:
    """Return deterministic ``PdfChunk``-shaped dicts.

    Each chunk covers a contiguous range of whole pages. A
    single page is the atomic unit; we do not split a page
    across chunks. The chunk's ``text`` is
    ``"\\n\\n".join(page_texts)`` for the page range it covers.

    Chunking rules:

    - Start a new chunk when adding the next page would push the
      accumulated character count above ``max_chars`` **or** when
      the current chunk already has ``>= target_chars``
      characters.
    - A single oversized page (e.g. a long table-less chapter)
      is emitted on its own with ``page_start == page_end``.

    The function is deterministic: same input, same output, same
    chunk ids, in the same order.
    """
    if target_chars <= 0 or max_chars <= 0:
        raise ValueError("target_chars and max_chars must be positive")
    chunks: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0

    def _flush() -> None:
        nonlocal current, current_chars
        if not current:
            return
        page_start = current[0]["page"]
        page_end = current[-1]["page"]
        text = "\n\n".join(str(entry.get("text") or "") for entry in current).strip()
        chunk_index = len(chunks)
        chunk_id = make_pdf_chunk_id(resource_id, chunk_index)
        label = f"page {page_start}" if page_start == page_end else f"pages {page_start}-{page_end}"
        if title:
            label = f"{title}, {label}"
        chunks.append(
            {
                "chunk_id": chunk_id,
                "resource_id": resource_id,
                "source_type": SourceType.PDF.value,
                "page_start": page_start,
                "page_end": page_end,
                "text": text,
                "citation_label": label,
                "char_count": len(text),
                "word_count": len(text.split()),
                "title": title,
                "file_path": file_path,
            }
        )
        current = []
        current_chars = 0

    for entry in pages:
        text = str(entry.get("text") or "")
        if not text.strip():
            # Skip empty pages; they remain addressable via
            # extract_pages_warnings instead of being emitted as
            # an empty chunk.
            continue
        if _is_oversized(text, max_chars):
            # Flush whatever we had and emit this single page on
            # its own. The next page will start a new chunk.
            _flush()
            current.append(entry)
            _flush()
            continue
        prospective = current_chars + len(text)
        if current and (prospective > max_chars or current_chars >= target_chars):
            _flush()
        current.append(entry)
        current_chars += len(text)
    _flush()
    return chunks


def _render_extracted_text(pages: list[dict[str, Any]]) -> str:
    """Concatenate all page texts with deterministic page markers."""
    parts: list[str] = []
    for entry in pages:
        parts.append(f"=== Page {entry['page']} ===\n\n{entry.get('text', '') or ''}\n")
    return "".join(parts).rstrip() + "\n"


def _build_metadata_block(
    *,
    content_hash: str,
    file_path: Path,
    title: str,
    author: str,
    pages: list[dict[str, Any]],
    source_url: Optional[str],
    copy_file: bool,
    media_path: Optional[Path],
    extraction_warnings: list[str],
) -> dict[str, Any]:
    return {
        "source_type": SourceType.PDF.value,
        "content_hash": content_hash,
        "resource_id": make_pdf_resource_id(content_hash),
        "original_path": str(file_path),
        "original_filename": file_path.name,
        "title": title,
        "author": author,
        "page_count": len(pages),
        "extraction_method": PDF_EXTRACT_METHOD,
        "source_url": source_url,
        "copied_to_media": copy_file,
        "media_path": str(media_path) if media_path else None,
        "extraction_warnings": extraction_warnings,
        "imported_at": datetime.utcnow().isoformat(),
    }


def _copy_to_media(source: Path, content_hash: str) -> Path:
    """Copy the source PDF to ``data/media/pdfs/<sha256>.pdf``.

    Returns the destination path. Creates parent directories as
    needed.
    """
    media_dir = config.get_data_path("media", "pdfs")
    media_dir.mkdir(parents=True, exist_ok=True)
    destination = media_dir / f"{content_hash}.pdf"
    if destination.exists() and destination.stat().st_size == source.stat().st_size:
        return destination
    shutil.copy2(source, destination)
    return destination


class PdfIngestor:
    """Ingest a local PDF file into the registry + external data directory.

    The class is stateless; everything is configurable via the
    constructor or method arguments so tests can drive it
    against a tmp dir.
    """

    def build_record(
        self,
        file_path: Path,
        *,
        title: str | None = None,
        source_url: str | None = None,
        tags: list[str] | None = None,
        copy_file: bool = False,
    ) -> ResourceRecord:
        """Read the PDF, extract text, write the raw files.

        Returns a fully populated :class:`ResourceRecord`. Does
        **not** insert into the registry; the CLI does that.

        Raises :class:`FileNotFoundError`, :class:`PermissionError`,
        :class:`PdfEncryptedError`, or :class:`pypdf.errors.PdfReadError`
        on hard failures.
        """
        absolute = file_path.expanduser().resolve()
        if not absolute.exists():
            raise FileNotFoundError(f"PDF not found: {absolute}")
        if not absolute.is_file():
            raise FileNotFoundError(f"Not a file: {absolute}")
        if absolute.suffix.lower() not in PDF_EXTENSIONS:
            raise ValueError(f"Not a .pdf file: {absolute}")

        content_hash = sha256_file(absolute)
        resource_id = make_pdf_resource_id(content_hash)

        # Pull PDF metadata so we can pre-populate the title and
        # author before the user's overrides are applied.
        meta_title, meta_author = self.extract_metadata(absolute)
        chosen_title = (title or meta_title or absolute.stem).strip()
        chosen_author = (meta_author or "").strip()

        # Extract page text. _load_reader raises PdfEncryptedError
        # for encrypted files; other PdfReadError variants bubble up.
        pages = extract_pages(absolute)
        warnings = extract_pages_warnings(pages)

        # Write raw outputs under the data directory.
        raw_dir = config.get_data_path("raw", "pdf", content_hash[:8])
        raw_dir.mkdir(parents=True, exist_ok=True)
        pages_path = raw_dir / "pages.json"
        extracted_path = raw_dir / "extracted.txt"
        metadata_path = raw_dir / "metadata.json"
        Storage.write_json(pages, pages_path)
        Storage.write_text(_render_extracted_text(pages), extracted_path)

        # Optionally copy the original PDF to media/pdfs/.
        media_path: Optional[Path] = None
        if copy_file:
            media_path = _copy_to_media(absolute, content_hash)

        # Final metadata block.
        metadata = _build_metadata_block(
            content_hash=content_hash,
            file_path=absolute,
            title=chosen_title,
            author=chosen_author,
            pages=pages,
            source_url=source_url,
            copy_file=copy_file,
            media_path=media_path,
            extraction_warnings=warnings,
        )
        Storage.write_json(metadata, metadata_path)

        # Description: truncated first ~500 chars of the
        # concatenated extracted text, with newlines collapsed.
        flat_text = " ".join(
            str(entry.get("text") or "").strip() for entry in pages
        )
        description = " ".join(flat_text.split())[:500]

        original_url = source_url or f"local://{absolute}"
        record = ResourceRecord(
            id=resource_id,
            source_type=SourceType.PDF,
            canonical_id=resource_id,
            original_url=original_url,
            normalized_url=original_url,
            content_hash=content_hash,
            title=chosen_title,
            author=chosen_author or None,
            description=description or None,
            tags=list(tags or []),
            status=ResourceStatus.NEW,
            local_raw_path=raw_dir,
            extra={
                "media_type": "pdf",
                "original_path": str(absolute),
                "original_filename": absolute.name,
                "content_hash": content_hash,
                "extraction_method": PDF_EXTRACT_METHOD,
                "extracted_text_path": str(extracted_path),
                "pages_path": str(pages_path),
                "metadata_path": str(metadata_path),
                "extraction_warnings": warnings,
                "copied_to_media": copy_file,
                "media_path": str(media_path) if media_path else None,
                "imported_at": metadata["imported_at"],
                "page_count": len(pages),
            },
        )
        return record

    def extract_metadata(self, pdf_path: Path) -> tuple[str, str]:
        """Return ``(/Title, /Author)`` from pypdf's metadata.

        Returns empty strings when missing. Used only to
        pre-populate the record's title/author; the user-supplied
        ``--title`` always wins.
        """
        try:
            reader = _load_reader(pdf_path)
        except Exception:
            return ("", "")
        meta = reader.metadata or {}
        title = str(meta.get("/Title") or "").strip()
        author = str(meta.get("/Author") or "").strip()
        return (title, author)


pdf_ingestor = PdfIngestor()
