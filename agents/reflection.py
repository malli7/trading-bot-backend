"""
Reflection Agent Module.

This agent is responsible for "Continuous Improvement". It reviews past trading
decisions (specifically skipped or held trades) against subsequent price action
to identify "missed opportunities" and generate lessons for the Swarm.
"""
import logging
import os
import asyncio
import time
from typing import Dict, Optional, Set, List, Any
from datetime import datetime, timedelta

from openai import AsyncOpenAI
from account import demo_account
from llm_config import REFLECTION_MODEL_ID
from prompt import REFLECTION_PROMPT

logger = logging.getLogger(__name__)

class ReflectionAgent:
    """
    The Critic Agent that learns from past mistakes.
    Now upgrades to analyze ALL trade states:
    1. Closed Trades (Post-Mortem): Did we follow process?
    2. Open Trades (Active Audit): Are we churning or holding dead money?
    3. Skipped Trades (Missed Opportunity): Did we miss a pump?
    """
    
    def __init__(self):
        self.model = REFLECTION_MODEL_ID
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        self.client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.api_key,
        )

    async def review_performance(self, current_prices: Dict[str, float]) -> None:
        """
        Master Review Cycle.
        """
        logger.info("Reflection Agent: Starting 360° Review Cycle...")
        
        if not demo_account.history:
            logger.info("Reflection Agent: No history to review.")
            return

        # 1. Fetch Data
        # Get last 100 actions to ensure we cover recent context
        history = demo_account.history[-100:] 
        
        # 2. Parallel Analysis Tasks
        tasks = []
        
        # A. Analyze Closed Trades (Post-Mortem)
        tasks.append(self._analyze_closed_trades(history))
        
        # B. Analyze Open Positions (Active Audit)
        # We use demo_account.positions directly
        tasks.append(self._analyze_open_trades(demo_account.positions, current_prices))
        
        # C. Analyze Skipped/Held Decisions (Missed Opps)
        # We need to fetch from DB for this as 'skip' isn't in account.history usually
        if demo_account.decision_collection is not None:
            cursor = demo_account.decision_collection.find(
                {"signal": {"$in": ["skip_trade", "HOLD", "WAIT"]}}
            ).sort("timestamp", -1).limit(50)
            skipped_decisions = await cursor.to_list(length=50)
            tasks.append(self._analyze_skipped_trades(skipped_decisions, current_prices))

        await asyncio.gather(*tasks)

    # ==========================================
    # A. CLOSED TRADE ANALYSIS (Post-Mortem)
    # ==========================================
    async def _analyze_closed_trades(self, history: List[Dict]):
        """Find recent closes and critique them."""
        # Filter for CLOSES in last 24h
        now = datetime.utcnow()
        recent_closes = []
        
        for action in reversed(history):
            if action.get("result") == "CLOSED" or action.get("action") == "close":
                try:
                    t = datetime.fromisoformat(action["time"])
                    if (now - t).total_seconds() < 24 * 3600:
                        recent_closes.append(action)
                except: continue

        for close_action in recent_closes:
            coin = close_action["coin"]
            close_id = f"CLOSE_{close_action['time']}_{coin}"
            
            # Deduplication
            if await self._is_processed(close_id):
                continue
                
            # Find matching OPEN
            open_action = self._find_matching_open(history, coin, close_action["time"])
            entry_reason = open_action.get("reason", "Unknown") if open_action else "Unknown"
            entry_price = open_action.get("price", 0) if open_action else 0
            
            # Data Prep
            pnl_val = close_action.get("pnl", 0)
            # Approximate PnL% if size is missing
            exit_price = close_action.get("price", 0)
            pnl_pct = 0.0
            if entry_price > 0:
                 pnl_pct = ((exit_price - entry_price) / entry_price) * 100
                 if pnl_val < 0 and pnl_pct > 0: pnl_pct *= -1 # Adjust for shorts if needed (simplification)

            outcome_desc = f"Closed with PnL: {pnl_pct:.2f}%. Exit Reason: {close_action.get('reason')}"
            
            # Generate Lesson
            await self._process_and_save_lesson(
                close_id,
                action="TRADE_COMPLETE", 
                coin=coin, 
                old_price=entry_price, 
                curr_price=exit_price, 
                pnl_pct=pnl_pct, 
                reason=f"Entry: {entry_reason}", 
                outcome_desc=outcome_desc
            )

    def _find_matching_open(self, history, coin, close_time_iso):
        """Find the Open event immediately preceding the Close."""
        close_dt = datetime.fromisoformat(close_time_iso)
        # Search backwards from Close
        for action in reversed(history):
            if action["coin"] == coin and action.get("result") == "OPEN":
                try:
                    open_dt = datetime.fromisoformat(action["time"])
                    if open_dt < close_dt:
                        return action
                except: continue
        return None

    # ==========================================
    # B. OPEN TRADE ANALYSIS (Active Audit)
    # ==========================================
    async def _analyze_open_trades(self, positions: Dict, current_prices: Dict):
        """Critique active positions for Stale/Churn status."""
        for coin, pos in positions.items():
            # Check ID for "Open Audit" - do this once every 4 hours? 
            # For now, let's do it based on entry time to avoid spamming 
            # We'll rely on the LLM to only output if there's a problem.
            
            # We construct a synthetic ID based on entry time + specific check intervals
            # e.g. check at 1h, 4h, 12h
            entry_time = datetime.fromisoformat(pos["timestamp"])
            now = datetime.utcnow()
            age_hours = (now - entry_time).total_seconds() / 3600
            
            audit_id = f"OPEN_AUDIT_{pos['timestamp']}_{int(age_hours)}" # Unique per hour
            
            # Verify duplication
            if await self._is_processed(audit_id):
                continue
                
            # Only audit at key milestones: 1h, 4h, 12h, 24h
            if int(age_hours) not in [1, 4, 12, 24]:
                continue
                
            curr_price = current_prices.get(coin, pos["entry_price"])
            pnl_pct = pos.get("unrealized_pnl", 0) # This is raw value, convert to % roughly
            # (Simplification: using stored pnl raw / margin * lev? or just use price delta)
            if pos["entry_price"] > 0:
                price_delta_pct = ((curr_price - pos["entry_price"]) / pos["entry_price"]) * 100
                if pos["sign"] == "SHORT": price_delta_pct *= -1
            else:
                price_delta_pct = 0.0

            outcome_desc = f"Holding for {age_hours:.1f} hours. Current PnL: {price_delta_pct:.2f}%."
            
            await self._process_and_save_lesson(
                audit_id,
                action="HOLDING_AUDIT",
                coin=coin,
                old_price=pos["entry_price"],
                curr_price=curr_price,
                pnl_pct=price_delta_pct,
                reason=pos.get("reason", "No reason"),
                outcome_desc=outcome_desc
            )

    # ==========================================
    # C. SKIPPED TRADE ANALYSIS (Missed Opps)
    # ==========================================
    async def _analyze_skipped_trades(self, decisions: List[Dict], current_prices: Dict):
        """Check if we missed a pump."""
        for dec in decisions:
            coin = dec.get("coin")
            if not coin or coin not in current_prices:
                continue
                
            # ID
            decision_id = f"SKIP_{dec['timestamp']}_{coin}"
            if await self._is_processed(decision_id):
                continue
                
            curr_price = current_prices[coin]
            old_price = float(dec.get("price", 0))
            if old_price == 0: continue
            
            # Simple threshold: If price moved > 2% against our 'wait', it's a miss
            move_pct = ((curr_price - old_price) / old_price) * 100
            
            # Only send to LLM if there is actually something to discuss
            if abs(move_pct) > 2.0:
                outcome_desc = f"Market moved {move_pct:.2f}% after we voted {dec.get('signal')}."
                
                await self._process_and_save_lesson(
                    decision_id,
                    action="MISSED_OPP_CHECK",
                    coin=coin,
                    old_price=old_price,
                    curr_price=curr_price,
                    pnl_pct=move_pct, # Hypothetical PnL
                    reason=dec.get("reason", "Unknown"),
                    outcome_desc=outcome_desc
                )

    # ==========================================
    # HELPERS
    # ==========================================
    async def _is_processed(self, unique_id: str) -> bool:
        """Check if we already generated a lesson for this ID."""
        if demo_account.lessons_collection is None:
            return False
        existing = await demo_account.lessons_collection.find_one({"source_decision_id": unique_id})
        return bool(existing)

    async def _process_and_save_lesson(self, unique_id, action, coin, old_price, curr_price, pnl_pct, reason, outcome_desc):
        """Generate and save lesson."""
        lesson_text = await self._generate_lesson(action, coin, old_price, reason, curr_price, pnl_pct, outcome_desc)
        
        if lesson_text and "No lesson" not in lesson_text:
            clean_lesson = lesson_text.replace("Lesson:", "").strip()
            logger.info(f"Generated Lesson for {coin} ({action}): {clean_lesson}")
            await demo_account.save_lesson(clean_lesson, source_decision_id=unique_id)

    async def _generate_lesson(self, action, coin, old_price, reason, curr_price, pnl_pct, outcome_desc) -> str:
        """LLM Call."""
        prompt = REFLECTION_PROMPT.format(
            action=action, 
            coin=coin, 
            old_price=old_price, 
            reason=reason, 
            curr_price=curr_price, 
            pnl_pct=f"{pnl_pct:.2f}",
            outcome_desc=outcome_desc
        )
        try:
            start_ts = time.time()
            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )
            logger.info(f"PERF: Reflection Agent LLM Call took {time.time() - start_ts:.2f}s")
            return completion.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Reflection LLM error: {e}")
            return "No lesson"
