
"""
Trading Orchestrator Service.

This module acts as the central coordinator for the automated trading system,
managing the "Learn -> See -> Feel -> Think -> Decide -> Act" lifecycle.
It integrates various agents (Swarm, Risk, Reflection) and services (Market Data, Execution).
"""
import logging
import json
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Tuple

from openai import AsyncOpenAI

# Core Imports
from core.config import settings
from core.schemas import CycleResult, TradeDecision

# Service/Agent Imports
# Assuming 'backend' is the root of the python path
from data import get_full_analysis
import account # Dynamic import for patching
from agents.reflection import ReflectionAgent
from agents.swarm import SwarmAnalyst
from agents.portfolio import PortfolioManager
from agents.risk_manager import RiskAssessmentAgent

# Configure logging
logger = logging.getLogger(__name__)

class TradingOrchestrator:
    """
    Coordinator class that manages the agentic workflow.
    """
    
    def __init__(self):
        self.reflection = ReflectionAgent()
        self.swarm = SwarmAnalyst()
        self.portfolio = PortfolioManager()
        self.risk_agent = RiskAssessmentAgent()
        
        if not settings.OPENROUTER_API_KEY:
            logger.warning("OPENROUTER_API_KEY not found in settings.")
            
        self.client = AsyncOpenAI(
             base_url="https://openrouter.ai/api/v1",
             api_key=settings.OPENROUTER_API_KEY
        )

    async def run_cycle(self) -> Dict[str, Any]:
        """
        Executes a full trading cycle.
        """
        logger.info("=== Starting Trading Cycle ===")
        
        # 2. Data Collection (See)
        market_data, current_prices = await get_all_market_data()
        
        # UPDATE ACCOUNT STATE (P&L, Stop Loss, Take Profit)
        # We must do this before making any new decisions.
        await account.demo_account.update_positions(current_prices)
        
        # 1. Reflection (Learn) & 3. Sentiment (Feel) - Parallel Execution
        reflection_task = asyncio.create_task(self.reflection.review_performance(current_prices))
        sentiment_task = asyncio.create_task(self.get_sentiment(market_data))
        
        # Wait for both
        await reflection_task
        sentiment = await sentiment_task
        
        # 4. Swarm Analysis (Think) & Decision Making
        decisions: List[Dict[str, Any]] = []

        # Create tasks for all assets to run in parallel
        asset_tasks = []
        for symbol, data in market_data.items():
            if symbol not in current_prices:
                continue
            
            asset_tasks.append(
                self.process_asset_logic(symbol, data, sentiment, current_prices)
            )

        # Execute all asset analysis in parallel
        logger.info(f"Analyzing {len(asset_tasks)} assets in parallel...")
        asset_results = await asyncio.gather(*asset_tasks)
        
        # Collect non-None results
        for res in asset_results:
            if res:
                decisions.append(res)
                await account.demo_account.log_decision(res)
            
        # 5. Execution (Act)
        for dec in decisions:
            coin = dec["coin"]
            
            # Update metadata for existing positions (keep reasoning fresh)
            if coin in account.demo_account.positions:
                await account.demo_account.update_position_metadata(
                    coin,
                    dec.get("reason", "No reason provided"),
                    dec.get("invalidation")
                )

            if dec["signal"] not in ["skip_trade", "HOLD", "WAIT"]:
                current_price = current_prices.get(coin, 0.0)
                if current_price > 0:
                     await account.demo_account.execute_trade(dec, current_price)
                 
        return {
            "status": "success",
            "timestamp": datetime.utcnow().isoformat(),
            "decisions": decisions,
            "account": {
                "balance": account.demo_account.cash,
                "positions": len(account.demo_account.positions),
                "total_value": account.demo_account.total_value
            }
        }

    async def process_asset_logic(
        self, 
        symbol: str, 
        data: Dict[str, Any], 
        sentiment: Dict[str, Any], 
        current_prices: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        Public Helper to process a single asset: Swarm -> Portfolio -> Risk Agent.
        Useful for backtesting where data is pre-fetched.
        """
        logger.info(f"Analyzing {symbol}...")
        
        # A. Portfolio Context
        current_price = current_prices[symbol]
        current_position = account.demo_account.positions.get(symbol)
        
        # B. Swarm Vote (Context Aware)
        # Pass position context to Swarm
        swarm_result = await self.swarm.get_consensus(data, sentiment, current_position)
        
        # C. Portfolio Allocation (Decide Direction)
        decision = self.portfolio.allocate(
            signal=swarm_result["signal"], 
            confidence=swarm_result["confidence"], 
            coin=symbol, 
            price=current_price,
            current_position=current_position,
            swarm_reason=swarm_result.get("rationale"),
            swarm_invalidation=swarm_result.get("invalidation")
        )

        # D. AI Risk Assessment (The Risk Officer) - ONLY for NEW trades
        if decision["signal"] in ["buy_to_enter", "sell_to_enter"]:
            logger.info(f"Sending {symbol} setup to Risk Agent for validation...")
            
            risk_decision = await self.risk_agent.assess_risk(
                signal=decision["signal"],
                symbol=symbol,
                current_price=current_price,
                swarm_reasoning=swarm_result.get("rationale"),
                swarm_confidence=swarm_result.get("confidence"),
                market_data=data,
                account_equity=account.demo_account.total_value,
                current_positions=account.demo_account.positions
            )
            
            if risk_decision.get("signal") == "REJECTED":
                # Risk Agent vetoed the trade
                logger.warning(f"Risk Agent REJECTED {symbol}: {risk_decision.get('reasoning')}")
                decision["signal"] = "HOLD"
                decision["reason"] = f"Risk Agent Veto: {risk_decision.get('reasoning')}"
            else:
                # Risk Agent approved - Apply Overrides
                logger.info(f"Risk Agent APPROVED {symbol}. Lev: {risk_decision.get('leverage')}x. Size: ${risk_decision.get('position_size_usd')}")
                decision.update({
                    "leverage": risk_decision.get("leverage", decision["leverage"]),
                    "stop_loss": risk_decision.get("stop_loss", decision["stop_loss"]),
                    "take_profit": risk_decision.get("take_profit", decision["profit_target"]),
                    "position_size_usd": risk_decision.get("position_size_usd"), # Passed to account
                    "reason": f"{decision['reason']} | Risk Officer: {risk_decision.get('reasoning')}"
                })

        return decision

    async def get_sentiment(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyzes market sentiment using a lightweight LLM model.
        """
        try:
             # Truncate data to save context window/costs
             # Only show last 5 hours of prices
             summary = {
                 k: v['1h']['midPrices'][-5:] 
                 for k, v in market_data.items() 
                 if '1h' in v
             }
             
             completion = await self.client.chat.completions.create(
                 model=settings.LLM_MODEL_FAST,
                 messages=[
                     {"role": "system", "content": "Analyze market sentiment (BULLISH/BEARISH/NEUTRAL) based on recent prices."},
                     {"role": "user", "content": json.dumps(summary)}
                 ]
             )
             return {"text": completion.choices[0].message.content}
        except Exception as e:
             logger.warning(f"Sentiment analysis failed: {e}")
             return {"text": "Neutral"}

# Helpers
async def get_all_market_data() -> Tuple[Dict[str, Any], Dict[str, float]]:
    """
    Fetches comprehensive market data for all tracked assets.
    """
    # Use settings for tracked assets
    # settings.TRACKED_ASSETS is List[Tuple[int, str]]
    assets = settings.TRACKED_ASSETS
    
    tasks = [get_full_analysis(mid) for mid, _ in assets]
    results = await asyncio.gather(*tasks)
    
    all_data = {}
    prices = {}
    
    for res in results:
        symbol = res['symbol']
        try:
            # We use the close of the last 15m candle as 'current price' reference
            current_price = res['indicator_data']['15m']['midPrices'][-1]
            prices[symbol] = current_price
        except (KeyError, IndexError):
            prices[symbol] = 0.0
            
        all_data[symbol] = res['indicator_data']
        
    return all_data, prices

# Global Orchestrator Instance
orchestrator = TradingOrchestrator()

async def run_agent_cycle() -> Dict[str, Any]:
    """
    Main entry point hook.
    """
    if account.demo_account.collection is None:
        await account.demo_account.initialize()
        
    return await orchestrator.run_cycle()
