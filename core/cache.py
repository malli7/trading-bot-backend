"""
Smart Cache Module (The Memory)
===============================

Why This Module Exists
----------------------
To reduce redundant LLM calls across the entire system (Simple Mode, Swarm Mode, Backtesting).

Key Features:
1.  **Centralized Logic**: Thresholds for Price, RSI, ADX are defined in `config.py` but enforced here.
2.  **Time Awareness**: Accepts `current_time` to support both Live Trading (system time) and Backtesting (simulation time).
3.  **Type Safety**: Typed storage for cache entries.
"""

import time
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

from core.config import settings

logger = logging.getLogger(__name__)

@dataclass
class CacheEntry:
    timestamp: float
    price: float
    rsi: float
    adx: float
    response: Dict[str, Any]

class SmartCache:
    """
    Manages caching of LLM decisions based on market stability.
    """
    
    def __init__(self, name: str = "GlobalCache"):
        self.name = name
        self.cache: Dict[str, CacheEntry] = {}
        
    def get(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached response if exists (does NOT check validity)."""
        if symbol in self.cache:
            return self.cache[symbol].response
        return None

    def update(self, symbol: str, price: float, rsi: float, adx: float, response: Dict[str, Any], current_time: Optional[float] = None) -> None:
        """Update the cache with a fresh decision."""
        if current_time is None:
            current_time = time.time()
            
        self.cache[symbol] = CacheEntry(
            timestamp=current_time,
            price=price,
            rsi=rsi,
            adx=adx,
            response=response
        )

    def should_refresh(self, symbol: str, current_price: float, current_rsi: float, current_adx: float, current_time: Optional[float] = None) -> bool:
        """
        Determines if the LLM needs to be called.
        Returns True if REFRESH needed (cache invalid/missing).
        Returns False if CACHE VALID (stable market).
        
        Args:
            current_time: Optional timestamp. If None, uses time.time(). 
                          Pass simulation time for Backtesting.
        """
        if symbol not in self.cache:
            return True
            
        entry = self.cache[symbol]
        
        if current_time is None:
            current_time = time.time()
            
        # 1. Time Expiry Check
        elapsed = current_time - entry.timestamp
        if elapsed > settings.CACHE_EXPIRY_SECONDS:
            logger.info(f"[{self.name}] Cache expired for {symbol} (Age: {elapsed:.0f}s). Refreshing.")
            return True
            
        # 2. Price Change Check
        if entry.price == 0: 
             return True
             
        price_delta_pct = abs(current_price - entry.price) / entry.price
        if price_delta_pct > settings.CHANGE_THRESHOLD_PRICE:
            logger.info(f"[{self.name}] Price moved > {settings.CHANGE_THRESHOLD_PRICE:.1%} for {symbol} ({price_delta_pct:.2%}). Refreshing.")
            return True
            
        # 3. RSI Change Check
        rsi_delta = abs(current_rsi - entry.rsi)
        if rsi_delta > settings.CHANGE_THRESHOLD_RSI:
            logger.info(f"[{self.name}] RSI moved > {settings.CHANGE_THRESHOLD_RSI} for {symbol} ({rsi_delta:.1f}). Refreshing.")
            return True
            
        # 4. ADX Change Check
        adx_delta = abs(current_adx - entry.adx)
        if adx_delta > settings.CHANGE_THRESHOLD_ADX:
            logger.info(f"[{self.name}] ADX moved > {settings.CHANGE_THRESHOLD_ADX} for {symbol} ({adx_delta:.1f}). Refreshing.")
            return True
            
        return False
