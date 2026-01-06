
"""
Application Configuration.

This module loads and validates environment variables and defines
system-wide constants (e.g., Asset IDs, API Timeouts).
"""
import os
from typing import List, Tuple
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # API Keys
    OPENROUTER_API_KEY: str = ""
    MONGO_URI: str = "mongodb://localhost:27017"
    
    # Application Config
    APP_NAME: str = "Antigravity Trading System"
    ENV: str = "development"
    DEBUG: bool = True
    
    # Trading Constants
    # Helper to decode list of tuples if needed, but for now simple list is fine.
    # Logic: (MarketID, Symbol)
    TRACKED_ASSETS: List[Tuple[int, str]] = [
        (0, "ETH"),
        (1, "BTC"),
        (2, "SOL")
    ]
    
    # Model Config
    LLM_MODEL_FAST: str = "google/gemini-2.0-flash-001"
    LLM_MODEL_REASONING: str = "deepseek/deepseek-chat"
    LLM_MODEL_CREATIVE: str = "meta-llama/llama-3.1-70b-instruct"

    class Config:
        # Look for .env in current, parent, or ../../ directories
        env_file = (".env", "../.env")
        extra = "ignore"

settings = Settings()
