"""OpenAI-compatible provider implementation.

Supports GLM Cloud, Kimi, Minimax, OpenRouter, and other OpenAI-compatible APIs.
"""

import json
from typing import Optional

import httpx

from wiki.config import config
from wiki.llm.base import LLMProvider


class OpenAICompatibleProvider(LLMProvider):
    """Generic OpenAI-compatible API provider.
    
    Works with any API that follows OpenAI's chat completions format,
    including GLM Cloud, Kimi, Minimax, OpenRouter, etc.
    """
    
    @property
    def provider_name(self) -> str:
        return "openai_compatible"

    def __init__(self, base_url: Optional[str] = None,
                 api_key: Optional[str] = None,
                 model: Optional[str] = None,
                 temperature: float = 0.2) -> None:
        """Initialize OpenAI-compatible provider.
        
        Args:
            base_url: API base URL (defaults to env)
            api_key: API key (defaults to env)
            model: Model name (defaults to env)
            temperature: Sampling temperature
        """
        self.base_url = (base_url or config.OPENAI_COMPATIBLE_BASE_URL or 
                        "").rstrip('/')
        self.api_key = api_key or config.OPENAI_COMPATIBLE_API_KEY
        self._model = model or config.OPENAI_COMPATIBLE_MODEL
        
        if not self.base_url:
            raise ValueError("OPENAI_COMPATIBLE_BASE_URL is required")
        if not self.api_key:
            raise ValueError("OPENAI_COMPATIBLE_API_KEY is required")
        if not self._model:
            raise ValueError("OPENAI_COMPATIBLE_MODEL is required")
        
        super().__init__(self._model, temperature)
        
        self.client = httpx.Client(
            timeout=120.0,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )
    
    def generate(self, prompt: str, *, system: Optional[str] = None,
                 temperature: Optional[float] = None) -> str:
        """Generate text using OpenAI-compatible API.
        
        Args:
            prompt: The user prompt
            system: Optional system message
            temperature: Optional temperature override
            
        Returns:
            Generated text
        """
        temp = temperature if temperature is not None else self.temperature
        
        # Build messages
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        
        # Make request
        try:
            response = self.client.post(
                f"{self.base_url}/chat/completions",
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temp,
                }
            )
            response.raise_for_status()
            data = response.json()
            
            # Extract response
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return ""
            
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"API error {e.response.status_code}: {e.response.text}"
            )
        except httpx.RequestError as e:
            raise RuntimeError(f"Request failed: {e}")
    
    def __del__(self) -> None:
        """Cleanup HTTP client."""
        if hasattr(self, 'client'):
            self.client.close()
