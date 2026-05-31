"""Local faster-whisper ASR provider."""

from __future__ import annotations

from pathlib import Path

from wiki.asr.base import ASRProvider, TranscriptResult, TranscriptSegment


class FasterWhisperProvider(ASRProvider):
    provider_name = "faster_whisper"

    def transcribe(self, audio_path: Path) -> TranscriptResult:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("Install faster-whisper with: pip install -U faster-whisper") from exc

        model = WhisperModel(self.model)
        segments_iter, info = model.transcribe(
            str(audio_path),
            task=self.task,
            language=self.language or None,
        )
        segments = [
            TranscriptSegment(
                id=index,
                start=float(segment.start),
                end=float(segment.end),
                text=segment.text.strip(),
            )
            for index, segment in enumerate(segments_iter)
        ]
        return TranscriptResult(
            text=" ".join(segment.text for segment in segments).strip(),
            segments=segments,
            language=getattr(info, "language", None),
        )
