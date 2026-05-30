"""Configuration management for Harish LLM Wiki."""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Config:
    """Application configuration loaded from environment variables."""

    # Data directory
    LLM_WIKI_DATA_DIR: Path

    # LLM Provider
    LLM_PROVIDER: str

    # Ollama Cloud
    OLLAMA_CLOUD_API_KEY: Optional[str]
    OLLAMA_CLOUD_BASE_URL: str
    OLLAMA_CLOUD_MODEL: Optional[str]

    # Ollama Local
    OLLAMA_LOCAL_BASE_URL: str
    OLLAMA_LOCAL_MODEL: str

    # OpenAI Compatible
    OPENAI_COMPATIBLE_BASE_URL: Optional[str]
    OPENAI_COMPATIBLE_API_KEY: Optional[str]
    OPENAI_COMPATIBLE_MODEL: Optional[str]

    def __init__(self) -> None:
        """Initialize configuration from environment variables."""
        # Data directory - default to ~/llm-wiki-data
        data_dir = os.getenv("LLM_WIKI_DATA_DIR", str(Path.home() / "llm-wiki-data"))
        self.LLM_WIKI_DATA_DIR = Path(data_dir).expanduser().resolve()

        # LLM Provider
        self.LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama_cloud")

        # Ollama Cloud
        self.OLLAMA_CLOUD_API_KEY = os.getenv("OLLAMA_CLOUD_API_KEY")
        self.OLLAMA_CLOUD_BASE_URL = os.getenv(
            "OLLAMA_CLOUD_BASE_URL", "https://ollama.com/api"
        )
        self.OLLAMA_CLOUD_MODEL = os.getenv("OLLAMA_CLOUD_MODEL")

        # Ollama Local
        self.OLLAMA_LOCAL_BASE_URL = os.getenv(
            "OLLAMA_LOCAL_BASE_URL", "http://localhost:11434"
        )
        self.OLLAMA_LOCAL_MODEL = os.getenv("OLLAMA_LOCAL_MODEL", "qwen2.5:7b")

        # OpenAI Compatible
        self.OPENAI_COMPATIBLE_BASE_URL = os.getenv("OPENAI_COMPATIBLE_BASE_URL")
        self.OPENAI_COMPATIBLE_API_KEY = os.getenv("OPENAI_COMPATIBLE_API_KEY")
        self.OPENAI_COMPATIBLE_MODEL = os.getenv("OPENAI_COMPATIBLE_MODEL")

    def get_data_path(self, *parts: str) -> Path:
        """Get a path within the data directory."""
        return self.LLM_WIKI_DATA_DIR.joinpath(*parts)

    def validate(self) -> list[str]:
        """Validate configuration and return list of errors."""
        errors: list[str] = []

        # Validate data directory
        if not self.LLM_WIKI_DATA_DIR.parent.exists():
            errors.append(
                f"Data directory parent does not exist: {self.LLM_WIKI_DATA_DIR.parent}"
            )

        # Validate LLM provider configuration
        if self.LLM_PROVIDER == "ollama_cloud":
            if not self.OLLAMA_CLOUD_API_KEY:
                errors.append("OLLAMA_CLOUD_API_KEY is required when LLM_PROVIDER=ollama_cloud")
            if not self.OLLAMA_CLOUD_MODEL:
                errors.append("OLLAMA_CLOUD_MODEL is required when LLM_PROVIDER=ollama_cloud")

        elif self.LLM_PROVIDER == "ollama_local":
            # Local Ollama just needs to be running, we'll check connectivity later
            pass

        elif self.LLM_PROVIDER == "mock":
            # Mock provider requires no configuration
            pass

        elif self.LLM_PROVIDER == "openai_compatible":
            if not self.OPENAI_COMPATIBLE_BASE_URL:
                errors.append(
                    "OPENAI_COMPATIBLE_BASE_URL is required when LLM_PROVIDER=openai_compatible"
                )
            if not self.OPENAI_COMPATIBLE_API_KEY:
                errors.append(
                    "OPENAI_COMPATIBLE_API_KEY is required when LLM_PROVIDER=openai_compatible"
                )
            if not self.OPENAI_COMPATIBLE_MODEL:
                errors.append(
                    "OPENAI_COMPATIBLE_MODEL is required when LLM_PROVIDER=openai_compatible"
                )

        else:
            errors.append(f"Unknown LLM_PROVIDER: {self.LLM_PROVIDER}")

        return errors

    def ensure_directories(self) -> None:
        """Create all necessary directories if they don't exist."""
        dirs = [
            self.get_data_path("inbox", "urls"),
            self.get_data_path("inbox", "markdown", "medium"),
            self.get_data_path("inbox", "markdown", "blogs"),
            self.get_data_path("inbox", "markdown", "linkedin_manual"),
            self.get_data_path("registry"),
            self.get_data_path("raw", "youtube"),
            self.get_data_path("raw", "webpage"),
            self.get_data_path("raw", "markdown"),
            self.get_data_path("normalized", "youtube"),
            self.get_data_path("normalized", "webpage"),
            self.get_data_path("normalized", "markdown"),
            self.get_data_path("processed", "resources"),
            self.get_data_path("processed", "concepts"),
            self.get_data_path("processed", "timeline"),
            self.get_data_path("processed", "gaps"),
            self.get_data_path("site_generated"),
            self.get_data_path("dist"),
        ]

        for dir_path in dirs:
            dir_path.mkdir(parents=True, exist_ok=True)


# Global config instance
config = Config()
