"""ASR provider contracts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class TranscriptSegment:
    id: int
    start: float
    end: float
    text: str

    def to_dict(self) -> dict[str, float | int | str]:
        return {
            "id": self.id,
            "start": self.start,
            "end": self.end,
            "text": self.text,
        }


@dataclass
class TranscriptResult:
    text: str
    segments: list[TranscriptSegment]
    language: str | None = None


class ASRProvider:
    provider_name = "asr"

    def __init__(
        self,
        model: str = "base",
        *,
        task: str = "transcribe",
        language: str | None = None,
    ) -> None:
        self.model = model
        self.task = task
        self.language = language

    def transcribe(self, audio_path: Path) -> TranscriptResult:
        raise NotImplementedError
