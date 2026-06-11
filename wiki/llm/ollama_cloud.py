"""Ollama Cloud provider implementation."""

import time
from typing import Optional

import httpx

from wiki.config import config
from wiki.llm.base import LLMProvider


class OllamaCloudProvider(LLMProvider):
    """Ollama Cloud API provider.
    
    Uses Ollama Cloud's REST API.
    """
    
    @property
    def provider_name(self) -> str:
        return "ollama_cloud"

    def __init__(self, api_key: Optional[str] = None, 
                 base_url: Optional[str] = None,
                 model: Optional[str] = None,
                 temperature: float = 0.2) -> None:
        """Initialize Ollama Cloud provider.
        
        Args:
            api_key: Ollama Cloud API key (defaults to env)
            base_url: Ollama Cloud API base URL (defaults to env)
            model: Model name (defaults to env)
            temperature: Sampling temperature
        """
        self.api_key = api_key or config.OLLAMA_CLOUD_API_KEY
        self.base_url = (base_url or config.OLLAMA_CLOUD_BASE_URL or 
                        "https://ollama.com/api").rstrip('/')
        self._model = model or config.OLLAMA_CLOUD_MODEL
        
        if not self.api_key:
            raise ValueError("OLLAMA_API_KEY or OLLAMA_CLOUD_API_KEY is required")
        if not self._model:
            raise ValueError("OLLAMA_CLOUD_MODEL is required")
        
        super().__init__(self._model, temperature)
        
        self.client = httpx.Client(
            timeout=120.0,  # Longer timeout for generation
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )
        self.max_retries = 3
    
    def generate(self, prompt: str, *, system: Optional[str] = None,
                 temperature: Optional[float] = None) -> str:
        """Generate text using Ollama Cloud API.
        
        Args:
            prompt: The user prompt
            system: Optional system message
            temperature: Optional temperature override
            
        Returns:
            Generated text
        """
        temp = temperature if temperature is not None else self.temperature
        max_tokens = config.LLM_MAX_OUTPUT_TOKENS
        self.last_usage = None
        
        # Build messages
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.client.post(
                    f"{self.base_url}/chat",
                    json={
                        "model": self.model,
                        "messages": messages,
                        "stream": False,
                        "options": {
                            "temperature": temp,
                            "num_predict": max_tokens,
                        }
                    }
                )
                response.raise_for_status()
                data = response.json()
                self.last_usage = data.get("usage") or {
                    "prompt_eval_count": data.get("prompt_eval_count"),
                    "eval_count": data.get("eval_count"),
                    "total_count": data.get("total_count"),
                }
                return data.get("message", {}).get("content", "")
            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code < 500 or attempt == self.max_retries:
                    raise RuntimeError(
                        f"Ollama Cloud API error {e.response.status_code}: {e.response.text}"
                    )
            except httpx.RequestError as e:
                last_error = e
                if attempt == self.max_retries:
                    raise RuntimeError(f"Ollama Cloud request failed: {e}")

            time.sleep(2 ** (attempt - 1))

        raise RuntimeError(f"Ollama Cloud request failed: {last_error}")
    
    def __del__(self) -> None:
        """Cleanup HTTP client."""
        if hasattr(self, 'client'):
            self.client.close()
