"""Placeholder OpenAI transcription provider.

Local Whisper/faster-whisper are the intended defaults. This class exists so
the provider abstraction has a stable extension point without wiring cloud ASR
into the default media workflow.
"""

from __future__ import annotations

from pathlib import Path

from wiki.asr.base import ASRProvider, TranscriptResult


class OpenAITranscribeProvider(ASRProvider):
    provider_name = "openai_transcribe"

    def transcribe(self, audio_path: Path) -> TranscriptResult:
        raise RuntimeError(
            "openai_transcribe is not configured for this project. "
            "Use --provider whisper or --provider faster_whisper."
        )
