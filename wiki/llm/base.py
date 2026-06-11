"""Base class for LLM providers."""

from abc import ABC, abstractmethod
from typing import Optional
import hashlib


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    def __init__(self, model: str, temperature: float = 0.2) -> None:
        """Initialize the provider.
        
        Args:
            model: Model name/identifier
            temperature: Sampling temperature
        """
        self.model = model
        self.temperature = temperature
        self.last_usage: dict | None = None
    
    @abstractmethod
    def generate(self, prompt: str, *, system: Optional[str] = None, 
                 temperature: Optional[float] = None) -> str:
        """Generate text from a prompt.
        
        Args:
            prompt: The user prompt
            system: Optional system message
            temperature: Optional temperature override
            
        Returns:
            Generated text
        """
        pass
    
    def compute_prompt_hash(self, prompt: str, system: Optional[str] = None) -> str:
        """Compute hash of prompt for caching."""
        content = f"{system or ''}:{prompt}"
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    @property
    def provider_name(self) -> str:
        """Return provider name for provenance."""
        return self.__class__.__name__.replace('Provider', '').lower()
