"""
Candle Data Fetcher Module.

This module interacts with the lighter.xyz API to fetch historical candlestick data.
It includes a custom API wrapper to handle specific endpoint quirks and headers.
"""
import time
import logging
from typing import List, Dict, Union, Any

import lighter.modules.api
from lighter.modules.api import Api
from lighter.constants import BLOCKCHAIN_ARBITRUM_ID

# Monkeypatch VERSION because the server endpoint uses /v1
lighter.modules.api.VERSION = "/v1"

class CustomApi(Api):
    """
    Subclass of Lighter SDK Api to fix get_candles functionality.
    
    Overrides the default method to use the working '/candles' endpoint
    instead of the SDK's default '/candlesticks'.
    """
    def get_candles(self, market_id: int, resolution: str, timestamp_start: int, timestamp_end: int, count_back: int) -> dict:
        params = {
            "blockchain_id": self.blockchain_id,
            "market_id": market_id,
            "resolution": resolution,
            "start_timestamp": timestamp_start,
            "end_timestamp": timestamp_end,
            "count_back": count_back
        }
        # Use /candles endpoint which works
        return self._get(request_path="/candles", params=params)

# Initialize the CustomAPI
API_URL = "https://mainnet.zklighter.elliot.ai"

# Initialize with custom settings
api = CustomApi(
    host=API_URL, 
    blockchain_id=BLOCKCHAIN_ARBITRUM_ID, 
    api_auth="", 
    api_timeout=10
)

# Mimic browser to avoid WAF 403 blocks
api.session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Referer": "https://lighter.xyz/",
    "Origin": "https://lighter.xyz"
})

# Remove empty Auth header if present
if "Auth" in api.session.headers and not api.session.headers["Auth"]:
    del api.session.headers["Auth"]

def get_candles(market_id: int, duration: str, limit: int = 100) -> List[Dict[str, float]]:
    """
    Fetch candlestick data for a given market and duration.
    
    Args:
        market_id (int): The ID of the market (e.g. 1 for WETH-USDC).
        duration (str): Resolution string ("1m", "5m", "15m", "1h", "4h", "1d").
        limit (int): Number of candles to retrieve.
        
    Returns:
        List[Dict[str, float]]: List of candles, each containing timestamp, open, high, low, close, volume.
    """
    
    # Map duration input to SDK constants
    resolution_map = {
        "1m": "1m", "1min": "1m",
        "5m": "5m", "5min": "5m",
        "15m": "15m",
        "1h": "1h", "1hr": "1h",
        "4h": "4h", "4hr": "4h",
        "1d": "1d",
    }
    
    resolution = resolution_map.get(duration, duration)
    
    # Map duration to seconds for start time calculation
    seconds_map = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "1h": 3600,
        "4h": 14400,
        "1d": 86400
    }
    
    seconds = seconds_map.get(resolution, 3600)
    
    now = int(time.time())
    start_time = now - (limit * seconds)
    
    try:
        response = api.get_candles(
            market_id=market_id,
            timestamp_start=start_time,
            timestamp_end=now,
            resolution=resolution,
            count_back=limit
        )
        
        # Extract candle list based on varying response formats
        items: List[Any] = []
        if isinstance(response, dict):
            if 'c' in response: items = response['c']
            elif 'candlesticks' in response: items = response['candlesticks']
            elif 'candles' in response: items = response['candles']
        elif isinstance(response, list):
             items = response
        
        formatted_candles = []
        for c in items:
            if isinstance(c, dict):
                # Condensed format: t, o, h, l, c, v
                if 't' in c:
                    formatted_candles.append({
                        "timestamp": c.get("t") / 1000.0, # Convert ms to seconds
                        "open": float(c.get("o", 0)),
                        "high": float(c.get("h", 0)),
                        "low": float(c.get("l", 0)),
                        "close": float(c.get("c", 0)),
                        "volume": float(c.get("v", 0))
                    })
                # Verbose format
                elif 'timestamp' in c:
                    formatted_candles.append({
                        "timestamp": c.get("timestamp"),
                        "open": float(c.get("open", 0)),
                        "high": float(c.get("high", 0)),
                        "low": float(c.get("low", 0)),
                        "close": float(c.get("close", 0)),
                        "volume": float(c.get("volume", 0))
                    })
            else:
                # Object-like fallback
                formatted_candles.append({
                    "timestamp": getattr(c, "timestamp", 0),
                    "open": float(getattr(c, "open", 0)),
                    "high": float(getattr(c, "high", 0)),
                    "low": float(getattr(c, "low", 0)),
                    "close": float(getattr(c, "close", 0)),
                    "volume": float(getattr(c, "volume", 0))
                })
                
        # Sort by time just in case
        formatted_candles.sort(key=lambda x: x['timestamp'])
        
        # Return requested limit
        return formatted_candles[-limit:]
        
    except Exception as e:
        logging.error(f"Error fetching candles: {e}")
        return []

if __name__ == "__main__":
    # Internal Test
    try:
        M_ID = 1
        print(f"Fetching candles for Market ID {M_ID}...")
        candles = get_candles(M_ID, "5m", 5)
        print(f"Got {len(candles)} candles.")
        if candles:
            print(f"First candle: {candles[0]}")
            print(f"Last candle: {candles[-1]}")
    except Exception as e:
        print(f"Test failed: {e}")
