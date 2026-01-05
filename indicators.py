"""
Technical Indicators Module.

This module contains pure mathematical functions to calculate common
technical analysis indicators (EMA, RSI, MACD, ATR).
"""
from typing import List, Dict, Union, Optional

def calculate_ema(prices: List[float], period: int) -> List[float]:
    """
    Calculate Exponential Moving Average (EMA).
    
    Args:
        prices: List of historical prices.
        period: The window size for the EMA.
        
    Returns:
        List of EMA values. The first (period-1) values will be missing/skipped,
        but to maintain alignment logic, we return the calculated array which
        starts from the first valid EMA point.
        However, for caller convenience, this returns a list shorter than input by (period-1).
    """
    ema: List[float] = []
    if not prices or len(prices) < period:
        return ema
    
    multiplier = 2 / (period + 1)
    
    # First EMA is SMA
    initial_slice = prices[:period]
    sma = sum(initial_slice) / len(initial_slice)
    
    ema.append(sma) # distinct from prices[period-1]? No, aligned to it conceptually.
    
    # Calculate subsequent EMAs
    for i in range(period, len(prices)):
        price = prices[i]
        last_ema = ema[-1]
        ema_value = (price - last_ema) * multiplier + last_ema
        ema.append(ema_value)
        
    return ema

def calculate_rsi(prices: List[float], period: int = 14) -> List[float]:
    """
    Calculate Relative Strength Index (RSI).
    """
    rsi: List[float] = []
    gains: List[float] = []
    losses: List[float] = []
    
    if len(prices) <= period:
        return rsi

    # Calculate changes
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        gains.append(max(change, 0.0))
        losses.append(abs(min(change, 0.0)))
        
    # First Avg Gain/Loss
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    # Helper to calc RSI from avg_gain/loss
    def calc(ag, al):
        if al == 0: return 100.0
        rs = ag / al
        return 100.0 - (100.0 / (1.0 + rs))

    rsi.append(calc(avg_gain, avg_loss))
    
    # Smoothed subsequent values (Wilder's Smoothing)
    for i in range(period, len(gains)):
        gain = gains[i]
        loss = losses[i]
        
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        
        rsi.append(calc(avg_gain, avg_loss))
            
    return rsi

def calculate_macd(prices: List[float]) -> List[float]:
    """
    Calculate MACD (12, 26, 9) - returning only the MACD line (Fast - Slow).
    Signal line not currently returned but can be added if needed.
    """
    ema12 = calculate_ema(prices, 12)
    ema26 = calculate_ema(prices, 26)
    
    # Alignment:
    # prices indices: 0..N-1
    # ema12 starts at index 11 (corresponds to prices[11])
    # ema26 starts at index 25 (corresponds to prices[25])
    
    # We want to subtract ema26 from ema12 overlapping at the same time indices.
    # The first valid ema26 is at prices[25].
    # The ema12 value at prices[25] is at index: 25 - 11 = 14.
    
    offset = 26 - 12 # 14
    
    macd: List[float] = []
    
    # Loop through the length of the shorter array (ema26)
    for i in range(len(ema26)):
        idx12 = i + offset
        if idx12 < len(ema12):
             val = ema12[idx12] - ema26[i]
             macd.append(val)
            
    return macd

def calculate_atr(candlesticks: List[Dict], period: int = 14) -> List[float]:
    """
    Calculate Average True Range (ATR).
    """
    atr: List[float] = []
    true_ranges: List[float] = []
    
    if not candlesticks or len(candlesticks) <= period:
        return atr
        
    for i in range(len(candlesticks)):
        current = candlesticks[i]
        
        if i == 0:
            tr = current['high'] - current['low']
        else:
            previous = candlesticks[i-1]
            tr = max(
                current['high'] - current['low'],
                abs(current['high'] - previous['close']),
                abs(current['low'] - previous['close'])
            )
        true_ranges.append(tr)
            
    # First ATR is SMA of TRs
    initial_atr = sum(true_ranges[:period]) / period
    atr.append(initial_atr)
    
    # Subsequent ATRs (Smoothed)
    for i in range(period, len(true_ranges)):
        tr = true_ranges[i]
        last_atr = atr[-1]
        new_atr = (last_atr * (period - 1) + tr) / period
        atr.append(new_atr)
        
    return atr

def calculate_all_indicators(candlesticks: List[Dict], output_count: int = 20) -> Dict[str, List[float]]:
    """
    Calculate comprehensive set of indicators and align them to the most recent data.
    
    Returns:
        Dict: Keyed by indicator name, containing List of float values.
    """
    if not candlesticks:
        return {}

    mid_prices = [round((c['open'] + c['close']) / 2, 3) for c in candlesticks]
    close_prices = [float(c['close']) for c in candlesticks]
    
    # Calculate all raw indicators
    ema20 = calculate_ema(close_prices, 20)
    ema50 = calculate_ema(close_prices, 50)
    macd = calculate_macd(close_prices)
    rsi7 = calculate_rsi(close_prices, 7)
    rsi14 = calculate_rsi(close_prices, 14)
    atr14 = calculate_atr(candlesticks, 14)
    
    # Helper to slice last N items safely and round them
    def get_last_n(arr: List[float], n: int) -> List[float]:
        if not arr: return []
        sliced = arr[-n:] if len(arr) >= n else arr
        return [round(x, 2) for x in sliced]
        
    # Since all calculations traverse forward and append results corresponding to 
    # the "current" candle, taking the last N values from each result list 
    # inherently aligns them to the last N candles of the input.
    
    return {
        "midPrices": get_last_n(mid_prices, output_count),
        "ema20": get_last_n(ema20, output_count),
        "ema50": get_last_n(ema50, output_count),
        "rsi7": get_last_n(rsi7, output_count),
        "rsi14": get_last_n(rsi14, output_count),
        "atr14": get_last_n(atr14, output_count),
        "macd": get_last_n(macd, output_count),
    }
