"""
Data Loader for Backtesting.

Fetches historical data from Lighter.xyz API using the shared `candles.py` API wrapper,
caches it locally, and provides mechanism to slice it for simulation.
"""
import time
import json
import os
import logging
import sys
from typing import Dict, List, Any

# Ensure backend path is in sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(current_dir)
if backend_dir not in sys.path:
    sys.path.append(backend_dir)

# Import the WORKING api instance from candles.py
from candles import api

logger = logging.getLogger("backtest_data")

class DataLoader:
    def __init__(self, data_dir: str = "data_cache"):
        self.data_dir = os.path.join(os.path.dirname(__file__), data_dir)
        os.makedirs(self.data_dir, exist_ok=True)
        # Market IDs: 0=ETH, 1=BTC, 2=SOL
        self.assets = [(0, "ETH"), (1, "BTC"), (2, "SOL")]
        self.timeframes = ["15m", "1h", "4h"]
        
        # Cache structure: {symbol: {timeframe: [candles]}}
        self.data_cache: Dict[str, Dict[str, List[Dict]]] = {}

    def fetch_historical_data(self, limit: int = 1000):
        """
        Download data for all assets and timeframes using candles.api.
        """
        logger.info(f"Fetching {limit} candles for all assets...")
        
        for m_id, symbol in self.assets:
            self.data_cache[symbol] = {}
            for tf in self.timeframes:
                filename = os.path.join(self.data_dir, f"{symbol}_{tf}.json")
                
                # Check Local Cache first
                if os.path.exists(filename):
                    try:
                        with open(filename, 'r') as f:
                            data = json.load(f)
                            if data: # Only use if not empty
                                self.data_cache[symbol][tf] = data
                                logger.info(f"Loaded {len(data)} {tf} candles for {symbol} from cache.")
                                continue
                    except json.JSONDecodeError:
                        logger.warning(f"Corrupted cache for {symbol} {tf}, refetching.")

                # Fetch from API using candles.py wrapper
                candles = self._download_candles(m_id, tf, limit)
                
                if candles:
                    self.data_cache[symbol][tf] = candles
                    # Save to Cache
                    with open(filename, 'w') as f:
                        json.dump(candles, f)
                    logger.info(f"Fetched {len(candles)} {tf} candles for {symbol}.")
                else:
                    logger.warning(f"Failed to fetch {tf} candles for {symbol}.")
                
                # Respect API limits
                time.sleep(0.5)

    def _download_candles(self, market_id: int, resolution: str, limit: int) -> List[Dict]:
        """Wrapper around candles.api.get_candles."""
        resolution_map = {
            "15m": "15m",
            "1h": "1h",
            "4h": "4h"
        }
        res_str = resolution_map.get(resolution, "15m")
        
        seconds_map = {"15m": 900, "1h": 3600, "4h": 14400}
        sec = seconds_map.get(resolution, 900)
        
        now = int(time.time())
        start = now - (limit * sec)
        
        try:
            # Call the CustomApi instance from candles.py
            # It returns the raw dict response from the server
            response = api.get_candles(
                market_id=market_id,
                resolution=res_str,
                timestamp_start=start,
                timestamp_end=now,
                count_back=limit
            )
            
            # Parse it
            items = []
            if isinstance(response, dict):
                if 'c' in response: items = response['c']
                elif 'candlesticks' in response: items = response['candlesticks']
                elif 'candles' in response: items = response['candles']
            elif isinstance(response, list):
                 items = response
            
            formatted = []
            for c in items:
                if isinstance(c, dict) and 't' in c:
                     formatted.append({
                        "timestamp": c['t'] / 1000.0,
                        "open": float(c.get("o", 0)),
                        "high": float(c.get("h", 0)),
                        "low": float(c.get("l", 0)),
                        "close": float(c.get("c", 0)),
                        "volume": float(c.get("v", 0))
                     })
                elif isinstance(c, dict) and 'timestamp' in c:
                    formatted.append({
                        "timestamp": c['timestamp'],
                        "open": float(c.get("open", 0)),
                        "high": float(c.get("high", 0)),
                        "low": float(c.get("low", 0)),
                        "close": float(c.get("close", 0)),
                         "volume": float(c.get("volume", 0))
                    })
            
            formatted.sort(key=lambda x: x['timestamp'])
            return formatted
            
        except Exception as e:
            logger.error(f"Download exception for {market_id} {resolution}: {e}")
            return []

    def get_market_snapshot(self, end_time_cutoff: float) -> Dict[str, Any]:
        """Same logic as before."""
        snapshot = {}
        
        for _, symbol in self.assets:
            if symbol not in self.data_cache: continue
            
            indicator_data = {}
            for tf in self.timeframes:
                if tf not in self.data_cache[symbol]: continue
                
                all_candles = self.data_cache[symbol][tf]
                visible = [c for c in all_candles if c['timestamp'] <= end_time_cutoff]
                
                if len(visible) < 50:
                    indicator_data[tf] = {}
                    continue
                
                from indicators import calculate_all_indicators
                
                # Use slightly larger context for calculation
                slice_for_calc = visible[-150:] 
                calc_result = calculate_all_indicators(slice_for_calc, output_count=20)
                indicator_data[tf] = calc_result
                
            snapshot[symbol] = {
                "symbol": symbol,
                "indicator_data": indicator_data
            }
            
        return snapshot

    def get_simulation_timeline(self) -> List[float]:
        if "BTC" not in self.data_cache or "15m" not in self.data_cache["BTC"]:
            return []
            
        btc_candles = self.data_cache["BTC"]["15m"]
        timestamps = [c['timestamp'] for c in btc_candles]
        
        if len(timestamps) > 100:
            return timestamps[100:]
        return []
