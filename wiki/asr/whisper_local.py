"""Local OpenAI Whisper ASR provider."""

from __future__ import annotations

from pathlib import Path

from wiki.asr.base import ASRProvider, TranscriptResult, TranscriptSegment


class WhisperLocalProvider(ASRProvider):
    provider_name = "whisper_local"

    def transcribe(self, audio_path: Path) -> TranscriptResult:
        try:
            import whisper
        except ImportError as exc:
            raise RuntimeError("Install local Whisper with: pip install -U openai-whisper") from exc

        model = whisper.load_model(self.model)
        result = model.transcribe(
            str(audio_path),
            task=self.task,
            language=self.language or None,
            verbose=False,
        )
        segments = [
            TranscriptSegment(
                id=int(segment.get("id", index)),
                start=float(segment.get("start", 0.0)),
                end=float(segment.get("end", 0.0)),
                text=str(segment.get("text", "")).strip(),
            )
            for index, segment in enumerate(result.get("segments", []))
        ]
        return TranscriptResult(
            text=str(result.get("text", "")).strip(),
            segments=segments,
            language=result.get("language"),
        )
