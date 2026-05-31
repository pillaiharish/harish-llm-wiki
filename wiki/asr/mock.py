"""Deterministic ASR provider for tests."""

from __future__ import annotations

from pathlib import Path

from wiki.asr.base import ASRProvider, TranscriptResult, TranscriptSegment


class MockASRProvider(ASRProvider):
    provider_name = "mock"

    def transcribe(self, audio_path: Path) -> TranscriptResult:
        segments = [
            TranscriptSegment(id=0, start=0.0, end=4.0, text="This is a mock transcript."),
            TranscriptSegment(id=1, start=4.0, end=9.0, text="It is deterministic for tests."),
        ]
        return TranscriptResult(text=" ".join(segment.text for segment in segments), segments=segments)
