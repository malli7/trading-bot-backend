"""
Technical Analysis Indicators Module (The Quant Lib)
====================================================

Why This Module Exists
----------------------
This module contains the pure mathematical logic for the system (Quant Lib).
It processes raw market data into actionable signals.

Responsibilities:
1. **Precision**: Standard EMA, RSI, MACD, ATR formulas via TA-Lib.
2. **Alignment**: Ensures indicator array outputs matched to the input timeline.
3. **Performance**: Optimized C-based calculations using TA-Lib.
"""
from typing import List, Dict, Union, Optional
import numpy as np
import talib

def _to_np(data: List[float]) -> np.ndarray:
    return np.array(data, dtype=np.float64)

def _clean_nans(data: np.ndarray) -> List[float]:
    """Remove NaNs from the beginning of the array and return as list."""
    return data[~np.isnan(data)].tolist()

def calculate_ema(prices: List[float], period: int) -> List[float]:
    """
    Calculate Exponential Moving Average (EMA).
    """
    if not prices or len(prices) < period:
        return []
        
    np_prices = _to_np(prices)
    ema = talib.EMA(np_prices, timeperiod=period)
    return _clean_nans(ema)

def calculate_rsi(prices: List[float], period: int = 14) -> List[float]:
    """
    Calculate Relative Strength Index (RSI).
    """
    if len(prices) <= period:
        return []
        
    np_prices = _to_np(prices)
    rsi = talib.RSI(np_prices, timeperiod=period)
    return _clean_nans(rsi)

def calculate_macd(prices: List[float]) -> List[float]:
    """
    Calculate MACD (12, 26, 9) - returning only the MACD line (Fast - Slow).
    Signal line not currently returned but can be added if needed.
    """
    if not prices or len(prices) < 26:
        return []

    np_prices = _to_np(prices)
    macd, signal, hist = talib.MACD(np_prices, fastperiod=12, slowperiod=26, signalperiod=9)
    return _clean_nans(macd)

def calculate_atr(candlesticks: List[Dict], period: int = 14) -> List[float]:
    """
    Calculate Average True Range (ATR).
    """
    if not candlesticks or len(candlesticks) <= period:
        return []
        
    high = np.array([c['high'] for c in candlesticks], dtype=np.float64)
    low = np.array([c['low'] for c in candlesticks], dtype=np.float64)
    close = np.array([c['close'] for c in candlesticks], dtype=np.float64)
    
    atr = talib.ATR(high, low, close, timeperiod=period)
    return _clean_nans(atr)

def calculate_adx(candlesticks: List[Dict], period: int = 14) -> List[float]:
    """
    Calculate Average Directional Index (ADX).
    """
    if not candlesticks or len(candlesticks) <= period:
        return []

    high = np.array([c['high'] for c in candlesticks], dtype=np.float64)
    low = np.array([c['low'] for c in candlesticks], dtype=np.float64)
    close = np.array([c['close'] for c in candlesticks], dtype=np.float64)
    
    adx = talib.ADX(high, low, close, timeperiod=period)
    return _clean_nans(adx)

def calculate_bollinger_bands(prices: List[float], period: int = 20, std_dev: int = 2) -> Dict[str, List[float]]:
    """
    Calculate Bollinger Bands.
    """
    if not prices or len(prices) < period:
        return {"upper": [], "lower": [], "middle": []}
        
    np_prices = _to_np(prices)
    upper, middle, lower = talib.BBANDS(np_prices, timeperiod=period, nbdevup=std_dev, nbdevdn=std_dev, matype=0)
    
    # BBANDS returns same length as input, with NaNs at start (period-1 usually)
    # We want to maintain alignment. 
    # Current implementation returns lists aligned to the end of the window (i.e. valid values).
    
    return {
        "upper": _clean_nans(upper),
        "lower": _clean_nans(lower), 
        "middle": _clean_nans(middle)
    }

def calculate_squeeze_metrics(
    prices: List[float], 
    bollinger_bands: Dict[str, List[float]], 
    kelter_channels: Optional[Dict] = None
) -> List[Dict[str, float]]:
    """
    Metrics to detect Volatility Squeeze.
    """
    metrics: List[Dict[str, float]] = []
    
    u = bollinger_bands["upper"]
    l = bollinger_bands["lower"]
    m = bollinger_bands["middle"]
    
    # Align lengths? TA-Lib outputs are stripped of NaNs, so they are shorter than prices.
    # Logic: prices is length N. BB is length N - period + 1.
    # We only care about the BB length portion.
    
    count = min(len(u), len(l), len(m))
    
    for i in range(count):
        mid = m[i]
        if mid == 0: 
            metrics.append({"bandwidth": 0, "is_squeeze": 0})
            continue
            
        bw = (u[i] - l[i]) / mid
        metrics.append({"bandwidth": bw})
        
    return metrics

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
    adx14 = calculate_adx(candlesticks, 14)
    
    # New: Bollinger Bands
    bb = calculate_bollinger_bands(close_prices, 20, 2)
    
    # New: Squeeze Metrics
    sqz_metrics = calculate_squeeze_metrics(close_prices, bb)
    squeeze_bandwidth = [m['bandwidth'] for m in sqz_metrics]
    
    # Helper to slice last N items safely and round them
    def get_last_n(arr: List[float], n: int) -> List[float]:
        if not arr: return []
        sliced = arr[-n:] if len(arr) >= n else arr
        return [round(x, 2) for x in sliced]
        
    return {
        "midPrices": get_last_n(mid_prices, output_count),
        "ema20": get_last_n(ema20, output_count),
        "ema50": get_last_n(ema50, output_count),
        "rsi7": get_last_n(rsi7, output_count),
        "rsi14": get_last_n(rsi14, output_count),
        "atr14": get_last_n(atr14, output_count),
        "adx14": get_last_n(adx14, output_count),
        "macd": get_last_n(macd, output_count),
        "bb_upper": get_last_n(bb['upper'], output_count),
        "bb_lower": get_last_n(bb['lower'], output_count),
        "bb_middle": get_last_n(bb['middle'], output_count),
        "squeeze_bandwidth": get_last_n(squeeze_bandwidth, output_count)
    }
