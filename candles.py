import lighter.modules.api
# Monkeypatch VERSION to v1 because the server endpoint is v1
lighter.modules.api.VERSION = "/v1"

from lighter.modules.api import Api
from lighter.constants import (
    HOST, 
    BLOCKCHAIN_ARBITRUM_ID,
    CANDLESTICK_RESOLUTION_1MIN,
    CANDLESTICK_RESOLUTION_5MIN,
    CANDLESTICK_RESOLUTION_1H,
    CANDLESTICK_RESOLUTION_4H
)
import time
from typing import List, Dict, Union, Optional

class CustomApi(Api):
    """
    Subclass of Api to fix get_candles method which uses incorrect parameter name in SDK.
    Server expects 'market_id', SDK sends 'order_book_symbol'.
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
        return self._get(request_path="/candlesticks", params=params)

# Initialize the CustomAPI
# Using the URL from user's example
API_URL = "https://mainnet.zklighter.elliot.ai"
api = CustomApi(host=API_URL, blockchain_id=BLOCKCHAIN_ARBITRUM_ID, api_auth="", api_timeout=10)

def get_candles(market_id: int, duration: str, limit: int = 100) -> List[Dict]:
    """
    Fetch candlestick data for a given market and duration using Lighter Python SDK.
    
    Args:
        market_id (int): The ID of the market (e.g. 1 for WETH-USDC).
        duration (str): Resolution string, e.g., "1m", "5m", "1h", "4h".
        limit (int): Number of candles to retrieve.
        
    Returns:
        List[Dict]: List of candlestick data dictionaries.
    """
    
    # Map duration input to SDK constants
    resolution_map = {
        "1m": "1m",
        "5m": "5m",
        "1hr": "1h",
        "1h": "1h",
        "4hr": "4h",
        "4h": "4h",
        # fallback if user passes constants directly or other formats
        "1min": "1m",
        "5min": "5m",
        "15m": "15m", 
        "1d": "1d",
    }
    
    resolution = resolution_map.get(duration, duration)
    
    # Map duration to seconds for start time calculation
    seconds_map = {
        "1m": 60, "1m": 60,
        "5m": 300, "5m": 300,
        "15m": 900, "15m": 900,
        "1h": 3600, "1hr": 3600,
        "4h": 14400, "4hr": 14400,
        "1d": 86400
    }
    
    seconds = seconds_map.get(duration, 3600)
    
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
        
        # Parse response
        items = response.get('candlesticks', []) if isinstance(response, dict) else response
        
        formatted_candles = []
        for c in items:
            if isinstance(c, dict):
                formatted_candles.append({
                    "timestamp": c.get("timestamp"),
                    "open": float(c.get("open", 0)),
                    "high": float(c.get("high", 0)),
                    "low": float(c.get("low", 0)),
                    "close": float(c.get("close", 0)),
                })
            else:
                formatted_candles.append({
                    "timestamp": getattr(c, "timestamp", 0),
                    "open": float(getattr(c, "open", 0)),
                    "high": float(getattr(c, "high", 0)),
                    "low": float(getattr(c, "low", 0)),
                    "close": float(getattr(c, "close", 0)),
                })
                
        formatted_candles.sort(key=lambda x: x['timestamp'])
        return formatted_candles[-limit:]
        
    except Exception as e:
        print(f"Error fetching candles: {e}")
        return []

if __name__ == "__main__":
    # Test script with mapping ID 1 (common for WETH-USDC in examples)
    # The user should provide the correct ID, but 1 is a good guess for mainnet WETH-USDC
    try:
        m_id = 1
        print(f"Fetching candles for Market ID {m_id}...")
        candles = get_candles(m_id, "5m", 5)
        print(f"Got {len(candles)} candles.")
        if candles:
            print(candles)
    except Exception as e:
        print(f"Test failed: {e}")
