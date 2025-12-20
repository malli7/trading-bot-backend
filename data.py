import time
from candles import get_candles
from indicators import calculate_all_indicators

async def get_indicators(duration: str, market_id: int, limit: int = 20):
    """
    Main entry point for getting standardized indicators.
    duration: "5m", "1h", "4h"
    limit: Number of records to return (default 20)
    Returns dictionary with midPrices, ema20, ema50, rsi7, rsi14, atr14, macd.
    """
    
    # We need enough data for the longest indicator (EMA50) + output limit.
    # Buffer of 100 is safe for calculation warm-up.
    fetch_limit = limit + 100
    
    candles = get_candles(market_id, duration, limit=fetch_limit)
    
    return calculate_all_indicators(candles, output_count=limit)

async def get_full_analysis(market_id: int):
    """
    Get 20 candles/indicators for 5m, 1h, and 4h timeframes.
    Returns structured data with symbol and indicators.
    """
    # Fetch indicators for all timeframes
    # 20 records requested by user
    limit = 20
    
    # We could use asyncio.gather for parallelism
    import asyncio
    
    task_15m = get_indicators("15m", market_id, limit)
    task_1h = get_indicators("1h", market_id, limit)
    task_4h = get_indicators("4h", market_id, limit)
    
    data_15m, data_1h, data_4h = await asyncio.gather(task_15m, task_1h, task_4h)
    
    # TODO: Fetch real symbol from SDK or map ID
    # For now, defaulting or using a placeholder until we add lookup
    symbol = "Unknown"
    if market_id == 1:
        symbol = "BTC"
    elif market_id == 2:
        symbol = "SOL"
    elif market_id == 0:
        symbol = "ETH"
    
    return {
        "symbol": symbol,
        "indicator_data": {
            "15m": data_15m,
            "1h": data_1h,
            "4h": data_4h
        }
    }
