"""Storage layer for file operations."""

import json
import hashlib
from pathlib import Path
from typing import Any, Iterator

from wiki.config import config


def compute_hash(content: bytes) -> str:
    """Compute SHA256 hash of content."""
    return hashlib.sha256(content).hexdigest()


def compute_string_hash(text: str) -> str:
    """Compute SHA256 hash of a string."""
    return compute_hash(text.encode("utf-8"))


class Storage:
    """File storage operations for the external data directory."""

    @staticmethod
    def write_json(data: Any, path: Path, indent: int = 2) -> None:
        """Write data as JSON to a file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, default=str, ensure_ascii=False)

    @staticmethod
    def read_json(path: Path) -> Any:
        """Read JSON from a file."""
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def write_jsonl(items: Iterator[dict], path: Path) -> None:
        """Write items as JSONL to a file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item, default=str, ensure_ascii=False) + "\n")

    @staticmethod
    def append_jsonl(item: dict, path: Path) -> None:
        """Append a single item to a JSONL file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(item, default=str, ensure_ascii=False) + "\n")

    @staticmethod
    def read_jsonl(path: Path) -> Iterator[dict]:
        """Read items from a JSONL file."""
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)

    @staticmethod
    def write_text(text: str, path: Path) -> None:
        """Write text to a file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    @staticmethod
    def read_text(path: Path) -> str:
        """Read text from a file."""
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def write_bytes(data: bytes, path: Path) -> None:
        """Write bytes to a file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)

    @staticmethod
    def read_bytes(path: Path) -> bytes:
        """Read bytes from a file."""
        with open(path, "rb") as f:
            return f.read()

    @staticmethod
    def exists(path: Path) -> bool:
        """Check if a path exists."""
        return path.exists()


# Convenience functions
def write_json(data: Any, *parts: str, indent: int = 2) -> Path:
    """Write JSON to a path in the data directory."""
    path = config.get_data_path(*parts)
    Storage.write_json(data, path, indent=indent)
    return path


def read_json(*parts: str) -> Any:
    """Read JSON from a path in the data directory."""
    path = config.get_data_path(*parts)
    return Storage.read_json(path)


def write_text(text: str, *parts: str) -> Path:
    """Write text to a path in the data directory."""
    path = config.get_data_path(*parts)
    Storage.write_text(text, path)
    return path


def read_text(*parts: str) -> str:
    """Read text from a path in the data directory."""
    path = config.get_data_path(*parts)
    return Storage.read_text(path)
