"""Ollama Local provider implementation."""

import json
from typing import Optional

import httpx

from wiki.config import config
from wiki.llm.base import LLMProvider


class OllamaLocalProvider(LLMProvider):
    """Local Ollama server provider.
    
    Uses local Ollama instance. Requires ollama to be running.
    """
    
    @property
    def provider_name(self) -> str:
        return "ollama_local"

    def __init__(self, base_url: Optional[str] = None,
                 model: Optional[str] = None,
                 temperature: float = 0.2) -> None:
        """Initialize local Ollama provider.
        
        Args:
            base_url: Ollama server base URL (defaults to env)
            model: Model name (defaults to env)
            temperature: Sampling temperature
        """
        self.base_url = (base_url or config.OLLAMA_LOCAL_BASE_URL or 
                        "http://localhost:11434").rstrip('/')
        self._model = model or config.OLLAMA_LOCAL_MODEL or "qwen2.5:7b"
        
        super().__init__(self._model, temperature)
        
        self.client = httpx.Client(
            timeout=120.0,
            headers={"Content-Type": "application/json"}
        )
    
    def generate(self, prompt: str, *, system: Optional[str] = None,
                 temperature: Optional[float] = None) -> str:
        """Generate text using local Ollama.
        
        Args:
            prompt: The user prompt
            system: Optional system message
            temperature: Optional temperature override
            
        Returns:
            Generated text
        """
        temp = temperature if temperature is not None else self.temperature
        
        try:
            response = self.client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "system": system or "",
                    "stream": False,
                    "options": {
                        "temperature": temp,
                    }
                }
            )
            response.raise_for_status()
            data = response.json()
            
            return data.get("response", "")
            
        except httpx.ConnectError:
            raise RuntimeError(
                f"Cannot connect to Ollama at {self.base_url}. "
                "Make sure Ollama is running: ollama serve"
            )
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"Ollama error {e.response.status_code}: {e.response.text}"
            )
        except httpx.RequestError as e:
            raise RuntimeError(f"Ollama request failed: {e}")
    
    def check_model(self) -> bool:
        """Check if the model is available locally."""
        try:
            response = self.client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            data = response.json()
            
            models = [m.get("name") for m in data.get("models", [])]
            return self.model in models
        except:
            return False
    
    def __del__(self) -> None:
        """Cleanup HTTP client."""
        if hasattr(self, 'client'):
            self.client.close()
