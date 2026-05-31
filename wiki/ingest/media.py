"""Local audio/video ingestion and audio extraction."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

from wiki.config import config
from wiki.schemas import ResourceRecord, SourceType
from wiki.storage import Storage


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac"}
MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS


def media_source_type(path: Path) -> SourceType:
    suffix = path.suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return SourceType.LOCAL_VIDEO
    if suffix in AUDIO_EXTENSIONS:
        return SourceType.LOCAL_AUDIO
    raise ValueError(f"Unsupported media extension: {suffix}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg"):
        return
    raise RuntimeError(
        "ffmpeg is required for media transcription.\n\n"
        "macOS:\n  brew install ffmpeg\n\n"
        "Ubuntu:\n  sudo apt-get install ffmpeg"
    )


def ffmpeg_extract_command(input_path: Path, output_path: Path) -> list[str]:
    return [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-ar",
        "16000",
        "-ac",
        "1",
        str(output_path),
    ]


def extract_audio_to_wav(input_path: Path, output_path: Path) -> Path:
    """Normalize audio/video input to a 16kHz mono WAV file."""
    ensure_ffmpeg()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ffmpeg_extract_command(input_path, output_path),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return output_path


class MediaIngestor:
    """Create registry-ready records and raw metadata for local media files."""

    def build_record(self, file_path: Path) -> ResourceRecord:
        absolute = file_path.expanduser().resolve()
        if not absolute.exists():
            raise FileNotFoundError(f"Media file not found: {absolute}")
        source_type = media_source_type(absolute)
        content_hash = sha256_file(absolute)
        resource_id = f"media:{content_hash}"
        raw_dir = config.get_data_path("raw", "media", content_hash)
        raw_dir.mkdir(parents=True, exist_ok=True)

        record = ResourceRecord(
            id=resource_id,
            source_type=source_type,
            canonical_id=resource_id,
            original_url=f"local://{absolute}",
            normalized_url=f"local://{absolute}",
            content_hash=content_hash,
            title=absolute.stem,
            local_raw_path=raw_dir,
            extra={
                "media_type": source_type.value,
                "original_path": str(absolute),
                "content_hash": content_hash,
                "duration_seconds": None,
                "audio_path": str(raw_dir / "audio.wav"),
                "transcript_path": str(raw_dir / "transcript.json"),
                "transcription_status": "pending",
            },
        )

        Storage.write_json(
            {
                "source_type": source_type.value,
                "original_path": str(absolute),
                "content_hash": content_hash,
                "resource_id": resource_id,
                "audio_path": str(raw_dir / "audio.wav"),
                "transcript_path": str(raw_dir / "transcript.json"),
                "transcription_status": "pending",
            },
            raw_dir / "metadata.json",
        )
        return record


media_ingestor = MediaIngestor()
