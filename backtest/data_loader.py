"""
Data Loader (The Time Machine)
==============================

Why This Module Exists
----------------------
To provide a reliable, cached stream of historical market data to the simulation engine.
It abstracts away the complexity of API rate limits, pagination, and local caching.

Responsibilities:
1.  **Fetching**: Smart pagination to get N days of 15m/1h/4h candles.
2.  **Caching**: Minimizes API calls by saving JSONs locally.
3.  **Playback**: Slices the timeline for the `BacktestEngine` to step through.
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
from market_data.candles import api

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
            # Pagination Logic
            collected_candles = []
            remaining = limit
            current_end = now
            
            chunk_size = 500 # Safe max for API
            
            while len(collected_candles) < limit:
                count = min(remaining, chunk_size)
                # Ensure we ask for at least a few, or just ask for chunk_size and filter later
                count = chunk_size 
                
                # We need to calculate start for THIS chunk loosely
                # But get_candles uses (start, end, count_back) priorities.
                # Use a wide window for start to ensure count_back works
                chunk_start = current_end - (count * sec * 2) 
                
                # Fetch Chunk
                response = api.get_candles(
                    market_id=market_id,
                    resolution=res_str,
                    timestamp_start=chunk_start,
                    timestamp_end=current_end,
                    count_back=count
                )
                
                # Extract Items
                items = []
                if isinstance(response, dict):
                    if 'c' in response: items = response['c']
                    elif 'candlesticks' in response: items = response['candlesticks']
                    elif 'candles' in response: items = response['candles']
                elif isinstance(response, list):
                     items = response
                     
                if not items:
                    break
                    
                # Parse Chunk
                chunk_formatted = []
                for c in items:
                    if isinstance(c, dict) and 't' in c:
                         chunk_formatted.append({
                            "timestamp": c['t'] / 1000.0,
                            "open": float(c.get("o", 0)),
                            "high": float(c.get("h", 0)),
                            "low": float(c.get("l", 0)),
                            "close": float(c.get("c", 0)),
                            "volume": float(c.get("v", 0))
                         })
                    elif isinstance(c, dict) and 'timestamp' in c:
                        chunk_formatted.append({
                            "timestamp": c['timestamp'],
                            "open": float(c.get("open", 0)),
                            "high": float(c.get("high", 0)),
                            "low": float(c.get("low", 0)),
                            "close": float(c.get("close", 0)),
                             "volume": float(c.get("volume", 0))
                        })
                
                # Sort just within chunk
                chunk_formatted.sort(key=lambda x: x['timestamp'])
                
                # Filter out dupes or future data if any
                new_candles = [c for c in chunk_formatted if c['timestamp'] < current_end]
                
                if not new_candles:
                    new_candles = chunk_formatted # Fallback
                
                if not new_candles:
                    break

                # Add to collection (prepend because we are going backwards? No, results come oldest->newest usually)
                # But here we are fetching back from 'current_end'.
                # The API likely returns [Oldest ... Newest] in that window.
                # So we should prepend or append?
                # If we use count_back from end, we get [End-Count ... End].
                # So the next query needs End' = (Oldest Timestamp of this chunk).
                
                collected_candles.extend(new_candles)
                
                # Update cursor for next page (move backwards)
                # We want the end of the next chunk to be the start of the oldest candle we just got.
                oldest_in_chunk = new_candles[0]['timestamp']
                current_end = int(oldest_in_chunk)
                
                # If we got fewer than requested, we actally might be done or API limits
                if len(new_candles) < 5: # Some buffer for sparse data
                     break
                     
                # Dedupe later
            
            # Deduplicate by timestamp
            unique = {c['timestamp']: c for c in collected_candles}
            final_list = list(unique.values())
            final_list.sort(key=lambda x: x['timestamp'])
            
            # Return exact limit needed (taking the most recent ones)
            return final_list[-limit:]
            
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
                
                from market_data.indicators import calculate_all_indicators
                
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
