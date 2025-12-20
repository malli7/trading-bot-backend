from typing import List, Dict, Union, Optional
import math

def calculate_ema(prices: List[float], period: int) -> List[float]:
    """
    Calculate Exponential Moving Average (EMA).
    """
    ema: List[float] = []
    if not prices:
        return ema
    
    multiplier = 2 / (period + 1)
    
    initial_slice = prices[:period]
    if not initial_slice:
        return ema
        
    sma = sum(initial_slice) / len(initial_slice)
    
    if len(prices) >= period:
        ema.append(sma)
    else:
        return ema

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
    
    if len(prices) < 2:
        return rsi

    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        gains.append(change if change > 0 else 0.0)
        losses.append(abs(change) if change < 0 else 0.0)
        
    if len(gains) < period:
        return rsi
        
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    if avg_loss == 0:
        rsi.append(100.0)
    else:
        rs = avg_gain / avg_loss
        rsi.append(100.0 - (100.0 / (1.0 + rs)))
        
    for i in range(period, len(gains)):
        gain = gains[i]
        loss = losses[i]
        
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        
        if avg_loss == 0:
            rsi.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi.append(100.0 - (100.0 / (1.0 + rs)))
            
    return rsi

def calculate_macd(prices: List[float]) -> List[float]:
    """
    Calculate Moving Average Convergence Divergence (MACD).
    """
    ema12 = calculate_ema(prices, 12)
    ema26 = calculate_ema(prices, 26)
    
    # Align them. EMA26 starts at index 26 (if using SMA start). 
    # Actually calculate_ema returns array starting from the first calculated value.
    # EMA12 length = N - 11
    # EMA26 length = N - 25
    # To align, we match the ends.
    
    # If using standard logic:
    # prices = [p0, p1, ..., pN]
    # ema12[0] corresponds to period ending at p11
    # ema26[0] corresponds to period ending at p25
    
    # We want MACD[0] to be ema12[k] - ema26[0]
    # where p25 is the end price for both.
    # ema12 value for p25 is at index (25 - 11) = 14.
    
    # So we skip first 14 elements of ema12.
    offset = 26 - 12 # 14
    
    macd: List[float] = []
    min_length = min(len(ema12) - offset, len(ema26))
    
    if min_length <= 0:
        return macd
        
    for i in range(min_length):
        ema12_idx = i + offset
        if ema12_idx < len(ema12):
            val = ema12[ema12_idx] - ema26[i]
            macd.append(val)
            
    return macd

def calculate_atr(candlesticks: List[Dict], period: int) -> List[float]:
    """
    Calculate Average True Range (ATR).
    """
    atr: List[float] = []
    true_ranges: List[float] = []
    
    if not candlesticks:
        return atr
        
    for i in range(len(candlesticks)):
        current = candlesticks[i]
        
        if i == 0:
            true_ranges.append(current['high'] - current['low'])
        else:
            previous = candlesticks[i-1]
            tr = max(
                current['high'] - current['low'],
                abs(current['high'] - previous['close']),
                abs(current['low'] - previous['close'])
            )
            true_ranges.append(tr)
            
    if len(true_ranges) < period:
        return atr
        
    initial_atr = sum(true_ranges[:period]) / period
    atr.append(initial_atr)
    
    for i in range(period, len(true_ranges)):
        tr = true_ranges[i]
        last_atr = atr[-1]
        new_atr = (last_atr * (period - 1) + tr) / period
        atr.append(new_atr)
        
    return atr

def calculate_all_indicators(candlesticks: List[Dict], output_count: int = 20) -> Dict:
    """
    Calculate comprehensive set of indicators:
    MidPrices, EMA20, EMA50, RSI7, RSI14, ATR14, MACD.
    Returns dictionaries aligned to the last N elements.
    Ordered oldest to newest.
    """
    if not candlesticks:
        return {}

    mid_prices = [round((c['open'] + c['close']) / 2, 3) for c in candlesticks]
    close_prices = [float(c['close']) for c in candlesticks]
    
    # Calculate all raw indicators
    ema20 = calculate_ema(close_prices, 20)
    ema50 = calculate_ema(close_prices, 50)
    macd = calculate_macd(close_prices) # Starts at index 26
    rsi7 = calculate_rsi(close_prices, 7)
    rsi14 = calculate_rsi(close_prices, 14)
    atr14 = calculate_atr(candlesticks, 14)
    
    # Start Indices (index in the original price array where the valid data starts)
    # EMA20 starts at 19 (0-indexed)
    # EMA50 starts at 49
    # MACD starts at 25
    # RSI7 starts at 7 (actually 7th gain is index 7) -> usually window size. 
    # RSI14 starts at 14
    # ATR14 starts at 13 (TR calculated from idx 1, then window 14 => 14th TR is at idx 14? No.
    # TR array length is same as candles (first is H-L).
    # Then we sum period TRs. 0..13 (14 items) -> idx 13 produces first ATR.
    
    # Let's verify lengths relative to prices.
    # If len(prices) = N.
    # len(ema20) = N - 19. (Last element corresponds to prices[N-1])
    # len(ema50) = N - 49.
    # len(macd) = N - 25.
    # len(rsi7) = N - 7.
    # len(rsi14) = N - 14.
    # len(atr14) = N - 13.
    
    # We want to align everything to the end.
    # We want exactly output_count items if available.
    
    # The constraining factor is usually EMA50 (needs 50 candles).
    # If we don't have enough data for EMA50, we return empty list for it? Or partial?
    # User requested 20 items.
    
    # Helper to slice last N items safely and round them
    def get_last_n(arr: List, n: int) -> List:
        if not arr: return []
        sliced = arr[-n:] if len(arr) >= n else arr
        return [round(x, 2) for x in sliced]
        
    # We must ensure alignment. 
    # e.g. if we have 100 prices.
    # ema50 has 51 values. the last value corresponds to price[99].
    # ema20 has 81 values. the last value corresponds to price[99].
    # So simply taking last N from each list will align them to the same timeframe (the latest N candles).
    
    return {
        "midPrices": get_last_n(mid_prices, output_count),
        "ema20": get_last_n(ema20, output_count),
        "ema50": get_last_n(ema50, output_count),
        "rsi7": get_last_n(rsi7, output_count),
        "rsi14": get_last_n(rsi14, output_count),
        "atr14": get_last_n(atr14, output_count),
        "macd": get_last_n(macd, output_count),
    }
