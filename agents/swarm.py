"""
Swarm Analyst Module.

This module implements a "Swarm Intelligence" approach where multiple diverse
LLM personas analyze market data in parallel. A Master LLM then aggregates
their individual reports into a final consensus decision.
"""
import logging
import json
import os
import asyncio
from typing import Dict, Any, List, Optional

from openai import AsyncOpenAI
from account import demo_account

logger = logging.getLogger(__name__)

from prompt import SWARM_PROMPT, MASTER_AGGREGATION_PROMPT

class SwarmAnalyst:
    """
    Manages the Swarm Intelligence network.
    
    Attributes:
        models (List[Dict]): Configuration of diverse analyst personas.
        client (AsyncOpenAI): OpenAI-compatible client.
    """
    
    def __init__(self):
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        self.client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.api_key,
        )
        
        # Diverse models for different perspectives (Using reliable IDs)
        self.models = [
            {"id": "google/gemini-2.0-flash-001", "role": "Conservative Risk Manager"},
            {"id": "deepseek/deepseek-chat", "role": "Aggressive Trend Follower"},
            {"id": "meta-llama/llama-3.1-70b-instruct", "role": "Pattern Recognition Specialist"},
        ]

    async def get_consensus(self, market_data: Dict[str, Any], sentiment: Dict[str, Any], current_position: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Query all models in parallel and aggregate votes via Master LLM.
        
        Args:
            market_data: Technical indicators for the asset.
            sentiment: Macro market sentiment.
            current_position: Existing position info (or None).
            
        Returns:
            Dict containing 'signal', 'confidence', 'rationale', and 'invalidation'.
        """
        # 1. Get Lessons
        lessons = await demo_account.get_recent_lessons()
        lessons_str = "\n- ".join(lessons) if lessons else "None"
        
        # Format Position Context for LLM
        if current_position:
            pos_str = f"{current_position['sign']} ({current_position['quantity']} units) @ ${current_position['entry_price']:.2f}"
            pnl_pct = ((current_position.get('current_price', 0) - current_position['entry_price']) / current_position['entry_price']) * 100
            if current_position['sign'] == "SHORT": pnl_pct *= -1
            pos_str += f" | PnL: {pnl_pct:.2f}%"
        else:
            pos_str = "NONE (Flat)"

        # 2. Prepare Tasks
        tasks = []
        market_str = json.dumps(market_data, default=str)
        sentiment_str = json.dumps(sentiment, default=str)
        
        for model_cfg in self.models:
            tasks.append(self._query_model(model_cfg, market_str, sentiment_str, lessons_str, pos_str))
            
        # 3. Gather Results
        results = await asyncio.gather(*tasks)
        valid_results = [r for r in results if r is not None]
        
        if not valid_results:
             return {
                 "signal": "HOLD", 
                 "confidence": 0.0, 
                 "rationale": "Swarm failed", 
                 "invalidation": "None"
             }

        # 4. Master Aggregation
        return await self._aggregate_with_master(valid_results, sentiment_str)

    async def _aggregate_with_master(self, results: List[Dict], sentiment_str: str) -> Dict[str, Any]:
        """
        Send all individual agent reports to a Master LLM for synthesis.
        """
        reports = ""
        for i, res in enumerate(results):
            reports += f"\n--- Analyst {i+1} ({res['role']}) ---\n"
            reports += f"Vote: {res['vote']}\nConfidence: {res['confidence']}%\n"
            reports += f"Reason: {res['reason']}\nInvalidation: {res['invalidation']}\n"
            
        prompt = MASTER_AGGREGATION_PROMPT.format(sentiment=sentiment_str, reports=reports)
        
        try:
            # Use a smart model for synthesis
            completion = await self.client.chat.completions.create(
                model="google/gemini-2.0-flash-001", # Capable and fast for aggregation
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2
            )
            content = completion.choices[0].message.content
            
            # Parse Master Output
            decision = "HOLD"
            conf = 0.0
            reason = "Master synthesis failed"
            invalidation = "None"
            
            lines = content.split('\n')
            for line in lines:
                if "Decision:" in line:
                    decision = line.split(":", 1)[1].strip().upper()
                if "Confidence:" in line:
                     try:
                        conf = float(line.split(":", 1)[1].strip().replace('%',''))
                     except (ValueError, IndexError): 
                        pass
                if "Reason:" in line:
                    reason = line.split(":", 1)[1].strip()
                if "Invalidation:" in line:
                    invalidation = line.split(":", 1)[1].strip()

            logger.info(f"Master Swarm Decision: {decision} ({conf}%) - {reason}")
            
            return {
                "signal": decision,
                "confidence": conf,
                "rationale": reason,
                "invalidation": invalidation
            }
            
        except Exception as e:
            logger.error(f"Master Swarm Aggregation failed: {e}")
            # Fallback to simple voting if Master fails
            return self._fallback_voting(results)

    def _fallback_voting(self, results: List[Dict]) -> Dict[str, Any]:
        """Legacy Logic as fallback if Master LLM fails."""
        votes = {"BUY": 0, "SELL": 0, "HOLD": 0}
        confidences = []
        reasons = []
        
        for res in results:
            v = res.get("vote", "HOLD").upper()
            if "BUY" in v: votes["BUY"] += 1
            elif "SELL" in v: votes["SELL"] += 1
            else: votes["HOLD"] += 1
            
            confidences.append(res.get("confidence", 0))
            reasons.append(f"{res['role']}: {res['reason']}")
        
        winner = max(votes, key=votes.get)
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0
        
        return {
            "signal": winner,
            "confidence": avg_confidence,
            "rationale": "; ".join(reasons),
            "invalidation": "Aggregation Failed"
        }

    async def _query_model(self, model_cfg: Dict[str, str], market_data: str, sentiment: str, lessons: str, pos_str: str) -> Optional[Dict[str, Any]]:
        """Query a single Swarm Agent."""
        prompt = SWARM_PROMPT.format(
            role_name=model_cfg["role"],
            market_data=market_data,
            sentiment=sentiment,
            lessons=lessons,
            position=pos_str
        )
        
        try:
            completion = await self.client.chat.completions.create(
                model=model_cfg["id"],
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )
            content = completion.choices[0].message.content
            
            # Simple parsing
            vote = "HOLD"
            conf = 0.0
            reason = "No reason"
            invalidation = "None"
            
            lines = content.split('\n')
            for line in lines:
                clean_line = line.strip()
                if clean_line.startswith("Vote:"):
                    vote = clean_line.split(":", 1)[1].strip()
                elif clean_line.startswith("Confidence:"):
                     try:
                        conf = float(clean_line.split(":", 1)[1].strip().replace('%',''))
                     except: pass
                elif clean_line.startswith("Technical Reason:"):
                    reason = clean_line.split(":", 1)[1].strip()
                elif clean_line.startswith("Reason:"): # Fallback
                     reason = clean_line.split(":", 1)[1].strip()
                elif clean_line.startswith("Invalidation:"):
                    invalidation = clean_line.split(":", 1)[1].strip()
                    
            return {
                "role": model_cfg["role"],
                "vote": vote,
                "confidence": conf,
                "reason": reason,
                "invalidation": invalidation
            }
            
        except Exception as e:
            logger.error(f"Model {model_cfg['id']} failed: {e}")
            return None
