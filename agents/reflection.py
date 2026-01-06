"""
Reflection Agent Module.

This agent is responsible for "Continuous Improvement". It reviews past trading
decisions (specifically skipped or held trades) against subsequent price action
to identify "missed opportunities" and generate lessons for the Swarm.
"""
import logging
import os
from typing import Dict, Optional, Set
from datetime import datetime

from openai import AsyncOpenAI
from account import demo_account

logger = logging.getLogger(__name__)

from prompt import REFLECTION_PROMPT

class ReflectionAgent:
    """
    The Critic Agent that learns from past mistakes.
    
    Attributes:
        model (str): The LLM model ID to use.
        client (AsyncOpenAI): OpenAI-compatible client.
    """
    
    def __init__(self):
        self.model = "google/gemini-2.0-flash-001"
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        self.client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.api_key,
        )

    async def review_performance(self, current_prices: Dict[str, float]) -> None:
        """
        Review past SKIP/HOLD decisions against current prices to find missed pumps.
        
        Args:
            current_prices: Dictionary of current market prices.
        """
        logger.info("Reflection Agent: Starting review cycle...")
        
        if demo_account.decision_collection is None:
            logger.warning("No decision collection found.")
            return

        # 0. Get Recent Lessons for Deduplication (Context)
        # We don't strictly need them here if we rely on decision_ID deduplication,
        # but useful if we wanted semantic checking later.
        
        # 1. Fetch recent 'skip_trade' or 'HOLD' decisions (last 50)
        cursor = demo_account.decision_collection.find(
            {"signal": {"$in": ["skip_trade", "HOLD"]}}
        ).sort("timestamp", -1).limit(50)
        
        decisions = await cursor.to_list(length=50)
        
        if not decisions:
            logger.info("Reflection Agent: No past decisions to review.")
            return

        # 2. Analyze
        # Track coins we've already generated a lesson for in this cycle to avoid dupes
        reviewed_coins: Set[str] = set()
        tasks = []
        
        for dec in decisions:
            coin = dec.get("coin")
            if not coin or coin in reviewed_coins:
                continue
                
            curr_price = current_prices.get(coin)
            if not curr_price:
                continue
                
            # Parse decision time
            try:
                dec_time = datetime.fromisoformat(dec["timestamp"])
                age_hours = (datetime.utcnow() - dec_time).total_seconds() / 3600
                
                # Only review decisions 1h to 24h old
                if age_hours < 1 or age_hours > 24: 
                    continue
            except (ValueError, TypeError):
                continue
                
            # Deduplication: Check if we already have a lesson for this specific decision
            # Unique ID = Timestamp + Coin + Signal
            decision_id = f"{dec['timestamp']}_{coin}_{dec['signal']}"
            
            # We must await the DB check here to avoid scheduling unnecessary tasks
            # This is a small performance hit but saves LLM calls. 
            # Alternatively, we could optimistically schedule and check inside the task, 
            # but that might waste LLM tokens if we don't check first.
            existing = await demo_account.lessons_collection.find_one({"source_decision_id": decision_id})
            if existing:
                logger.debug(f"Skipping reviewed decision: {decision_id}")
                continue

            # Calculate Price Move
            old_price = float(dec.get("price", 0))
            if old_price == 0: 
                continue
            
            pnl_pct = ((curr_price - old_price) / old_price) * 100
            
            # Threshold: If we missed a > 1.5% move
            if pnl_pct > 1.5:
                reviewed_coins.add(coin) # Mark as handled for this batch
                
                # Create Task
                tasks.append(
                    self._process_single_lesson(
                         dec, coin, old_price, curr_price, pnl_pct, decision_id
                    )
                )

        if tasks:
            logger.info(f"Reflection Agent: Generating {len(tasks)} lessons in parallel...")
            await asyncio.gather(*tasks)

    async def _process_single_lesson(self, dec, coin, old_price, curr_price, pnl_pct, decision_id):
        """Helper to generate and save a lesson."""
        outcome = "Missed Opportunity (Price Rallied)"
        action = dec.get("signal")
        reason = dec.get("reason", "Unknown")
        
        lesson = await self._generate_lesson(action, coin, old_price, reason, curr_price, pnl_pct, outcome)
        
        if lesson and "No lesson" not in lesson:
                clean_lesson = lesson.replace("Lesson: ", "").strip()
                logger.info(f"Generated Lesson for {coin}: {clean_lesson}")
                await demo_account.save_lesson(clean_lesson, source_decision_id=decision_id)

    async def _generate_lesson(
        self, 
        action: Optional[str], 
        coin: str, 
        old_price: float, 
        reason: str, 
        curr_price: float, 
        pnl_pct: float, 
        outcome_desc: str
    ) -> str:
        """
        Generate a lesson using the LLM.
        
        Returns:
            str: The generated lesson text or 'No lesson'.
        """
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
            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )
            return completion.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Reflection LLM error: {e}")
            return "No lesson"
