"""
Data Aggregation Module.

This module coordinates fetching raw market data (candles) and transforming it
into technical indicators for use by the trading agents.
"""
import asyncio
from typing import Dict, Any, List

from candles import get_candles
from indicators import calculate_all_indicators

async def get_indicators(duration: str, market_id: int, limit: int = 20) -> Dict[str, List[float]]:
    """
    Fetch standardized indicators for a specific market and timeframe.
    
    Args:
        duration: Timeframe ("15m", "1h", "4h")
        market_id: Market ID (0=ETH, 1=BTC, 2=SOL)
        limit: Number of records to return
        
    Returns:
        Dict containing lists of indicator values (midPrices, ema20, rsi14, etc.)
    """
    # We need enough data for the longest indicator (EMA50) + output limit.
    # Buffer of 100 is safe for calculation warm-up to converge.
    fetch_limit = limit + 100
    
    # This is a synchronous call to Lighter SDK (via candles.py), wrapped in async def
    # Ideally should run in executor if blocking, but HTTP request is fast enough for now
    candles = get_candles(market_id, duration, limit=fetch_limit)
    
    return calculate_all_indicators(candles, output_count=limit)

async def get_full_analysis(market_id: int) -> Dict[str, Any]:
    """
    Fetch comprehensive analysis across multiple timeframes for a single market.
    
    Args:
        market_id: Market ID to analyze.
        
    Returns:
        Dict containing symbol name and a nested dictionary of indicators by timeframe.
    """
    # 20 records requested by user for context window
    limit = 20
    
    # Run fetches in parallel
    task_15m = get_indicators("15m", market_id, limit)
    task_1h = get_indicators("1h", market_id, limit)
    task_4h = get_indicators("4h", market_id, limit)
    
    results = await asyncio.gather(task_15m, task_1h, task_4h)
    data_15m, data_1h, data_4h = results
    
    # Map ID to Symbol
    # TODO: Fetch real symbol from SDK or centralized config
    symbol_map = {
        0: "ETH",
        1: "BTC",
        2: "SOL"
    }
    symbol = symbol_map.get(market_id, "Unknown")
    
    return {
        "symbol": symbol,
        "indicator_data": {
            "15m": data_15m,
            "1h": data_1h,
            "4h": data_4h
        }
    }
