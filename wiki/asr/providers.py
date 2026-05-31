"""ASR provider factory."""

from __future__ import annotations

from wiki.asr.base import ASRProvider
from wiki.config import config


def get_asr_provider(name: str | None = None) -> ASRProvider:
    provider_name = (name or config.ASR_PROVIDER).replace("-", "_")
    model = config.ASR_MODEL
    task = config.ASR_TASK
    language = config.ASR_LANGUAGE

    if provider_name in {"whisper", "whisper_local"}:
        from wiki.asr.whisper_local import WhisperLocalProvider

        return WhisperLocalProvider(model=model, task=task, language=language)
    if provider_name == "faster_whisper":
        from wiki.asr.faster_whisper import FasterWhisperProvider

        return FasterWhisperProvider(model=model, task=task, language=language)
    if provider_name == "mock":
        from wiki.asr.mock import MockASRProvider

        return MockASRProvider(model="mock", task=task, language=language)
    if provider_name == "openai_transcribe":
        from wiki.asr.openai_transcribe import OpenAITranscribeProvider

        return OpenAITranscribeProvider(model=model, task=task, language=language)
    raise ValueError(f"Unknown ASR provider: {provider_name}")
