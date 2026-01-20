"""
LLM Client Singleton
====================

Centralized access to the AsyncOpenAI client to prevent resource exhaustion
from multiple connection pools.
"""
import logging
from typing import Optional
from openai import AsyncOpenAI
from core.config import settings

logger = logging.getLogger(__name__)

class LLMFactory:
    _instance: Optional[AsyncOpenAI] = None

    @classmethod
    def get_client(cls) -> AsyncOpenAI:
        """
        Returns the singleton AsyncOpenAI client.
        Initializes it if it doesn't exist.
        """
        if cls._instance is None:
            logger.info("Initializing Shared LLM Client...")
            api_key = settings.OPENROUTER_API_KEY
            if not api_key:
                logger.warning("OPENROUTER_API_KEY not found. LLM calls may fail.")
            
            cls._instance = AsyncOpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=api_key,
            )
        return cls._instance

# Convenience accessor
def get_llm_client() -> AsyncOpenAI:
    return LLMFactory.get_client()
