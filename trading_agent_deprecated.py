"""
Trading Orchestrator Module.

This module acts as the central coordinator for the automated trading system,
managing the "Learn -> See -> Feel -> Think -> Decide -> Act" lifecycle.
"""
import os
import json
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, Tuple, List, Optional

from openai import AsyncOpenAI
from dotenv import load_dotenv

# Project Imports
from data import get_full_analysis
from account import demo_account
from agents.reflection import ReflectionAgent
from agents.swarm import SwarmAnalyst
from agents.portfolio import PortfolioManager
from agents.risk_manager import RiskAssessmentAgent

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

class TradingOrchestrator:
    """
    Coordinator class that manages the agentic workflow.
    
    Attributes:
        reflection (ReflectionAgent): Analyzes past performance.
        swarm (SwarmAnalyst): Generates trading signals via consensus.
        portfolio (PortfolioManager): Manages risk and allocation.
        risk_agent (RiskAssessmentAgent): Final check for sizing & leverage.
        client (AsyncOpenAI): LLM client for sentiment analysis.
    """
    
    def __init__(self):
        self.reflection = ReflectionAgent()
        self.swarm = SwarmAnalyst()
        self.portfolio = PortfolioManager()
        self.risk_agent = RiskAssessmentAgent()
        
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            logger.warning("OPENROUTER_API_KEY not found in environment.")
            
        self.client = AsyncOpenAI(
             base_url="https://openrouter.ai/api/v1",
             api_key=api_key
        )

    async def run_cycle(self) -> Dict[str, Any]:
        """
        Executes a full trading cycle.

        Steps:
        1. **Reflection**: Review past decisions and learn lessons.
        2. **Data Collection**: Fetch current market data and prices.
        3. **Sentiment**: Analyze macro sentiment (Fear/Greed).
        4. **Swarm Analysis**: Generate signals (Buy/Sell/Hold) for each token.
        5. **Portfolio**: Format initial decision (Direction).
        6. **Risk Assessment**: AI Agent determines Sizing, Leverage, SL/TP.
        7. **Execution**: Execute validated orders.

        Returns:
            Dict[str, Any]: Summary of the cycle execution.
        """
        logger.info("=== Starting Trading Cycle ===")
        
        # 2. Data Collection (See)
        market_data, current_prices = await get_all_market_data()
        
        # UPDATE ACCOUNT STATE (P&L, Stop Loss, Take Profit)
        # We must do this before making any new decisions.
        await demo_account.update_positions(current_prices)

        
        # 1. Reflection (Learn) & 3. Sentiment (Feel) - Parallel Execution
        # We run these together to save time. Swarm needs Sentiment, but not necessarily instant Reflection (though we wait for it to keep logic simple).
        reflection_task = asyncio.create_task(self.reflection.review_performance(current_prices))
        sentiment_task = asyncio.create_task(self.get_sentiment(market_data))
        
        # Wait for both (Reflection updates DB for Swarm to potentially use, though we could optimize this further)
        await reflection_task
        sentiment = await sentiment_task
        
        # 4. Swarm Analysis (Think)
        decisions: List[Dict[str, Any]] = []
        
        # 4. Swarm Analysis (Think) & Decision Making
        decisions: List[Dict[str, Any]] = []

        # Create tasks for all assets to run in parallel
        asset_tasks = []
        for symbol, data in market_data.items():
            if symbol not in current_prices:
                continue
            
            asset_tasks.append(
                self._process_asset(symbol, data, sentiment, current_prices)
            )

        # Execute all asset analysis in parallel
        logger.info(f"Analyzing {len(asset_tasks)} assets in parallel...")
        asset_results = await asyncio.gather(*asset_tasks)
        
        # Collect non-None results
        for res in asset_results:
            if res:
                decisions.append(res)
                await demo_account.log_decision(res)
            
        # 5. Execution (Act)
        for dec in decisions:
            if dec["signal"] not in ["skip_trade", "HOLD"]:
                current_price = current_prices.get(dec["coin"], 0.0)
                if current_price > 0:
                     await demo_account.execute_trade(dec, current_price)
                 
        return {
            "status": "success",
            "decisions": decisions,
            "account": {
                "balance": demo_account.cash,
                "positions": len(demo_account.positions)
            }
        }

    async def _process_asset(
        self, 
        symbol: str, 
        data: Dict[str, Any], 
        sentiment: Dict[str, Any], 
        current_prices: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        Helper to process a single asset: Swarm -> Portfolio -> Risk Agent.
        """
        logger.info(f"Analyzing {symbol}...")
        
        # A. Portfolio Context
        current_price = current_prices[symbol]
        current_position = demo_account.positions.get(symbol)
        
        # B. Swarm Vote (Now Context Aware)
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

        # C. AI Risk Assessment (The Risk Officer) - ONLY for NEW trades
        if decision["signal"] in ["buy_to_enter", "sell_to_enter"]:
            logger.info(f"Sending {symbol} setup to Risk Agent for validation...")
            
            risk_decision = await self.risk_agent.assess_risk(
                signal=decision["signal"],
                symbol=symbol,
                current_price=current_price,
                swarm_reasoning=swarm_result.get("rationale"),
                swarm_confidence=swarm_result.get("confidence"),
                market_data=data, # Pass technicals for context
                account_equity=demo_account.total_value
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
                    "position_size_usd": risk_decision.get("position_size_usd"), # Passed to account.py
                    "reason": f"{decision['reason']} | Risk Officer: {risk_decision.get('reasoning')}"
                })

        return decision

    async def get_sentiment(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyzes market sentiment using a lightweight LLM model.
        
        Args:
            market_data: Dictionary of market indicators.
            
        Returns:
            Dict[str, Any]: Sentiment analysis result (e.g. {"text": "BULLISH"}).
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
                 model="google/gemini-2.0-flash-001",
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
    
    bReturns:
        Tuple containing:
        - market_data (Dict): full technical analysis
        - prices (Dict): current prices map
    """
    # Asset definition: (MarketID, Symbol)
    # IDs correspond to data.py logic: ETH=0, BTC=1, SOL=2
    assets = [(0, "ETH"), (1, "BTC"), (2, "SOL")]
    
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
    Main entry point hook for the API.
    Ensures DB is ready before running the cycle.
    """
    # Ideally initialize should be called at app startup (which we do now in main.py)
    # But double check here for safety.
    if demo_account.collection is None:
        await demo_account.initialize()
        
    return await orchestrator.run_cycle()

