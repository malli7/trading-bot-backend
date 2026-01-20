"""
Simple Agent Module (The All-In-One Analyst)
============================================

Why This Module Exists
----------------------
This module implements "Simple Mode", where a single high-reasoning LLM call replaces
the complex Swarm -> Master -> Risk pipeline.

It is designed for speed, lower cost, and relying on the reasoning capabilities 
of advanced models (like Gemini 2.0 Flash) to handle the full context in one go.
"""

import logging
import json
import time
from typing import Dict, Any, Optional

from openai import AsyncOpenAI
from core.config import settings
from core.llm import get_llm_client
from services.account import demo_account

logger = logging.getLogger(__name__)

from prompts.simple import SIMPLE_TRADING_PROMPT

from core.cache import SmartCache

class SimpleAgent:
    """
    Single-shot agent that analyzes market data and produces a trading decision with risk parameters.
    """
    
    def __init__(self):
        self.api_key = settings.OPENROUTER_API_KEY
        self.model_id = settings.SIMPLE_MODEL_ID
        self.client = get_llm_client()
        self.cache = SmartCache(name="SimpleAgent")

    def _get_latest_indicator(self, market_data: Dict[str, Any], key: str, default: float = 0.0) -> float:
        """Helper to extract latest value from market data arrays."""
        try:
            # Handle nested structure first
            source = market_data.get("15m", market_data)
            arr = source.get(key, [])
            if arr and len(arr) > 0:
                return float(arr[-1])
        except:
            pass
        return default

    async def analyze(self, symbol: str, market_data: Dict[str, Any], current_prices: Dict[str, float], current_time: Optional[float] = None) -> Dict[str, Any]:
        """
        Analyze specific asset using the single-shot prompt with Smart Caching.
        """
        start_ts = time.time()
        
        # 1. Extract Critical Metrics for Caching
        price = current_prices.get(symbol, 0.0)
        current_rsi = self._get_latest_indicator(market_data, "rsi14")
        current_adx = self._get_latest_indicator(market_data, "adx14")
        
        # 2. Check Cache
        if not self.cache.should_refresh(symbol, price, current_rsi, current_adx, current_time=current_time):
            logger.info(f"Using CACHED decision for {symbol} (Stable Market Conditions).")
            cached_response = self.cache.get(symbol)
            if cached_response:
                return cached_response

        # 3. Context Prep
        pos = demo_account.positions.get(symbol)
        
        # Format Position
        if pos:
            pos_str = f"{pos['sign']} ({pos['quantity']:.4f}) @ {pos['entry_price']:.2f}"
        else:
            pos_str = "FLAT"

        # Format Lessons
        lessons = await demo_account.get_recent_lessons()
        lessons_str = "\n- ".join(lessons) if lessons else "None"
        
        # Format Market Data (Dump JSON for the LLM to parse raw values if needed, or simplified)
        # Using the same simplified approach as Swarm might be better, but passing full JSON is fine for Gemini 2.0
        market_str = json.dumps(market_data, indent=2) 
        # Truncate if too long (unlikely for single asset 15m data)
        if len(market_str) > 20000:
            market_str = market_str[:20000] + "...(truncated)"

        # 4. Build Prompt
        prompt = SIMPLE_TRADING_PROMPT.format(
            symbol=symbol,
            price=price,
            position_str=pos_str,
            lessons=lessons_str,
            market_data=market_str
        )

        try:
            # 5. Call LLM
            logger.info(f"SimpleAgent analyzing {symbol} with {self.model_id}...")
            completion = await self.client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2, # Low temp for deterministic logic
                response_format={"type": "json_object"} # Force JSON
            )
            
            result_json = completion.choices[0].message.content
            logger.debug(f"SimpleAgent Raw Output: {result_json}")
            
            data = json.loads(result_json)
            
            # 6. Normalize Output
            signal = data.get("signal", "HOLD").upper()
            confidence = float(data.get("confidence", 0))
            
            final_response = {
                "signal": signal,
                "confidence": confidence,
                "rationale": data.get("reason", "No reason provided"),
                "invalidation": f"Price: {data.get('invalidation_price', 'N/A')}",
                "suggested_leverage": int(data.get("suggested_leverage", 1)),
                "stop_loss": data.get("stop_loss", 0.0),
                "take_profit": data.get("take_profit", 0.0)
            }
            
            # 7. Update Cache
            self.cache.update(symbol, price, current_rsi, current_adx, final_response, current_time=current_time)
            
            return final_response
            
        except Exception as e:
            logger.error(f"SimpleAgent failed for {symbol}: {e}")
            return {
                "signal": "HOLD",
                "confidence": 0.0,
                "rationale": f"Agent Error: {e}",
                "invalidation": "Error"
            }
