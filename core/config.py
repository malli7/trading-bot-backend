"""
Centralized Application Configuration
=====================================

Purpose
-------
This module defines the single source of truth for all system configurations, 
utilizing Pydantic for robust environment variable validation and type safety.
It consolidates application settings, trading parameters, and LLM model definitions.

Key Components
--------------
1. **Environment Variables**: Automatically loads from .env files.
2. **Risk Engine Settings**: Defines the mathematical safety rails (Vol Target, Correlation Limits).
3. **Model Registry**: Centralizes ALL LLM model IDs.
4. **Trading Constants**: Defines tracked assets and market metadata.

Usage
-----
Import the `settings` instance globally:
    from core.config import settings

"""
import os
from typing import List, Tuple, Dict
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # API Keys
    OPENROUTER_API_KEY: str = ""
    MONGO_URI: str = "mongodb://localhost:27017"
    
    # --- System Config ---
    TRADING_MODE: str = "SWARM" # Options: "SWARM", "SIMPLE"
    SIMPLE_MODEL_ID: str = "google/gemini-3-flash-preview" # Fast, high-reasoning model for single-shot mode

    
    # --- Account / Trading Config ---
    ACCOUNT_INITIAL_BALANCE: float = 1000.0
    MAX_RISK_PER_TRADE: float = 0.02  # 2% of equity
    MAX_MARGIN_PER_POS: float = 0.20  # 20% of equity
    TRADING_FEE_RATE: float = 0.001   # 0.1% Taker Fee

    # --- Smart Cache Config ---
    CACHE_EXPIRY_SECONDS: int = 300          # 5 minutes
    CHANGE_THRESHOLD_PRICE: float = 0.002    # 0.2% price change
    CHANGE_THRESHOLD_RSI: float = 4.0        # 4 point RSI change
    CHANGE_THRESHOLD_ADX: float = 2.0        # 2 point ADX change

    # --- Portfolio Agent Config ---
    PORTFOLIO_MAX_POS_SIZE: float = 0.30     # 30% max per trade
    PORTFOLIO_MIN_CONFIDENCE: float = 60.0   # Minimum confidence to enter
    
    # --- Model Config ---
    RISK_TARGET_VOL: float = 0.40  # Target Annualized Volatility (40%)
    RISK_MAX_CORRELATED_EXPOSURE: float = 1.5 # Max 1.5x equity in highly correlated assets
    
    # Simple static correlation matrix (approximate for Crypto Beta)
    # In a production HFT system, this should likely be dynamic or loaded from an external source.
    RISK_CORRELATION_MATRIX: dict = {
        "BTC": {"BTC": 1.0, "ETH": 0.85, "SOL": 0.75},
        "ETH": {"BTC": 0.85, "ETH": 1.0, "SOL": 0.80},
        "SOL": {"BTC": 0.75, "ETH": 0.80, "SOL": 1.0}
    }
    
    # --- Application Config ---
    APP_NAME: str = "Trading System"
    ENV: str = "development"
    DEBUG: bool = True
    
    # Trading Constants
    # Logic: (MarketID, Symbol)
    TRACKED_ASSETS: List[Tuple[int, str]] = [
        (0, "ETH"),
        (1, "BTC"),
        (2, "SOL")
    ]
    
    DEFAULT_TIMEFRAME: str = "15m"

    @property
    def MARKET_ID_MAP(self) -> Dict[int, str]:
        """Auto-generates ID to Symbol map from TRACKED_ASSETS."""
        return {mid: symbol for mid, symbol in self.TRACKED_ASSETS}
    


    # Agent Specific Models (Consolidated from llm_config.py)
    SWARM_MODELS: List[dict] = [
        {"id": "google/gemini-3-flash-preview", "role": "Conservative Risk Manager"},
        {"id": "google/gemini-3-flash-preview", "role": "Aggressive Trend Follower"},
        {"id": "google/gemini-3-flash-preview", "role": "Pattern Recognition Specialist"},
    ]
    MASTER_MODEL_ID: str = "google/gemini-3-flash-preview"
    RISK_MODEL_ID: str = "google/gemini-3-flash-preview"
    REFLECTION_MODEL_ID: str = "google/gemini-3-flash-preview"

    class Config:
        # Look for .env in current, parent, or ../../ directories
        env_file = (".env", "../.env")
        extra = "ignore"

settings = Settings()
