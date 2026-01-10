"""
Trading Orchestrator Service (The Conductor)
============================================

Why This Module Exists
----------------------
This is the **Central Nervous System** of the agent.
It coordinates the "See -> Think -> Decide -> Act" lifecycle, ensuring that all
sub-agents (Swarm, Risk, Reflection) work in harmony to execute the trading strategy.

Responsibilities:
1.  **Lifecycle Management**: Orchestrating the flow from data collection to execution.
2.  **State Synchronization**: Ensuring the Account and Portfolio states are fresh.
3.  **Parallel Execution**: Running analysis for multiple assets concurrently.
4.  **Error Isolation**: preventing a failure in one asset from crashing the entire cycle.
"""
import logging
import json
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional

from openai import AsyncOpenAI

# Core Imports
from core.config import settings
from core.schemas import CycleResult, TradeDecision

# Service/Agent Imports
from market_data.aggregate import get_full_analysis
import services.account as account
from agents.reflection import ReflectionAgent
from agents.swarm import SwarmAnalyst
from agents.portfolio import PortfolioManager
from agents.risk_manager import RiskAssessmentAgent

# Configure logging
logger = logging.getLogger(__name__)

class TradingOrchestrator:
    """
    The Conductor of the Agentic System.
    """
    
    def __init__(self):
        self.reflection = ReflectionAgent()
        self.swarm = SwarmAnalyst()
        self.portfolio = PortfolioManager()
        self.risk_agent = RiskAssessmentAgent()
        
        # Clients
        self.client = AsyncOpenAI(
             base_url="https://openrouter.ai/api/v1",
             api_key=settings.OPENROUTER_API_KEY
        )

    async def run_cycle(self) -> Dict[str, Any]:
        """
        Executes a full trading cycle: See -> Learn -> Think -> Act.
        """
        logger.info("=== Starting Trading Cycle ===")
        
        # 1. SEE: Data Collection
        market_data, current_prices = await self._fetch_market_data()
        
        # 2. UPDATE: Synchronize Account State
        if account.demo_account.collection is None:
             await account.demo_account.initialize()
        await account.demo_account.update_positions(current_prices)
        
        # 3. LEARN: Reflection (Parallel)
        try:
            await self.reflection.review_performance(current_prices)
        except Exception as e:
            logger.error(f"Reflection failed: {e}")

        # 4. THINK & DECIDE: Parallel Analysis Pipeline
        decisions: List[Dict[str, Any]] = []
        
        # Construct tasks
        tasks = []
        for symbol, data in market_data.items():
            if symbol not in current_prices:
                continue
            tasks.append(self._run_analysis_pipeline(symbol, data, current_prices))
            
        # Execute Robustly
        logger.info(f"Analyzing {len(tasks)} assets in parallel...")
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for res in results:
            if isinstance(res, Exception):
                logger.error(f"Asset Pipeline Failed: {res}")
                continue
            if res:
                decisions.append(res)
                await account.demo_account.log_decision(res)

        # 5. ACT: Execution
        for dec in decisions:
            await self._execute_decision(dec, current_prices)

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

    async def _fetch_market_data(self) -> Tuple[Dict[str, Any], Dict[str, float]]:
        """
        Fetches market data for all tracked assets defined in settings.
        """
        assets = settings.TRACKED_ASSETS
        tasks = [get_full_analysis(mid) for mid, _ in assets]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        all_data = {}
        prices = {}
        
        for i, res in enumerate(results):
            symbol = assets[i][1] # Get symbol from settings tuple
            if isinstance(res, Exception):
                logger.error(f"Failed to fetch data for {symbol}: {res}")
                continue
                
            try:
                # Use close of last 15m candle as reference price
                current_price = res['indicator_data']['15m']['midPrices'][-1]
                prices[symbol] = current_price
                all_data[symbol] = res['indicator_data']
            except (KeyError, IndexError) as e:
                 logger.error(f"Data Malformed for {symbol}: {e}")
                 prices[symbol] = 0.0
                 
        return all_data, prices

    async def _run_analysis_pipeline(
        self, 
        symbol: str, 
        data: Dict[str, Any], 
        current_prices: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        The Core Intelligence Pipeline: Swarm -> Portfolio -> Risk.
        """
        logger.info(f"Analyzing {symbol}...")
        
        # A. Context
        current_price = current_prices[symbol]
        current_position = account.demo_account.positions.get(symbol)
        
        # B. Swarm (The Mind)
        swarm_result = await self.swarm.get_consensus(data, current_position)
        
        # C. Portfolio (The Allocator)
        decision = self.portfolio.allocate(
            signal=swarm_result["signal"], 
            confidence=swarm_result["confidence"], 
            coin=symbol, 
            price=current_price,
            current_position=current_position,
            swarm_reason=swarm_result.get("rationale"),
            swarm_invalidation=swarm_result.get("invalidation"),
            suggested_leverage=swarm_result.get("suggested_leverage")
        )
        
        # D. Risk (The Safety) - For Entries Only
        if decision["signal"] in ["buy_to_enter", "sell_to_enter"]:
             decision = await self._validate_with_risk_agent(decision, symbol, current_price, swarm_result, data)
             
        return decision

    async def _validate_with_risk_agent(
        self, 
        decision: Dict[str, Any], 
        symbol: str, 
        current_price: float, 
        swarm_result: Dict[str, Any],
        market_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validates a proposed trade with the Risk Assessment Agent.
        """
        logger.info(f"Sending {symbol} setup to Risk Agent...")
        
        risk_decision = await self.risk_agent.assess_risk(
            signal=decision["signal"],
            symbol=symbol,
            current_price=current_price,
            swarm_reasoning=swarm_result.get("rationale"),
            swarm_confidence=swarm_result.get("confidence"),
            market_data=market_data,
            account_equity=account.demo_account.total_value,
            current_positions=account.demo_account.positions
        )
        
        if risk_decision.get("signal") == "REJECTED":
            logger.warning(f"Risk Agent REJECTED {symbol}: {risk_decision.get('reasoning')}")
            return {
                "signal": "SKIP_TRADE",
                "coin": symbol,
                "reason": f"Risk Agent Veto: {risk_decision.get('reasoning')}",
                "invalidation": "N/A - Trade Rejected"
            }
        
        # Approved - Merge Risk Params
        logger.info(f"Risk Agent APPROVED {symbol}. Lev: {risk_decision.get('leverage')}x")
        decision.update({
            "leverage": risk_decision.get("leverage", decision["leverage"]),
            "stop_loss": risk_decision.get("stop_loss", decision["stop_loss"]),
            "take_profit": risk_decision.get("take_profit", decision["profit_target"]),
            "position_size_usd": risk_decision.get("position_size_usd"),
            "reason": f"{decision['reason']} | Risk Officer: {risk_decision.get('reasoning')}"
        })
        return decision

    async def _execute_decision(self, dec: Dict[str, Any], current_prices: Dict[str, float]) -> None:
        """
        Routes the decision to the execution engine.
        """
        coin = dec["coin"]
        
        # Update metadata for existing
        if coin in account.demo_account.positions:
            await account.demo_account.update_position_metadata(
                coin,
                dec.get("reason", "No reason"),
                dec.get("invalidation")
            )
            
        # Execute Signal
        signal = dec["signal"]
        if signal not in ["skip_trade", "HOLD", "WAIT"]:
             price = current_prices.get(coin, 0.0)
             if price > 0:
                 await account.demo_account.execute_trade(dec, price)

# Global Instance
orchestrator = TradingOrchestrator()

async def run_agent_cycle() -> Dict[str, Any]:
    """
    Main entry point hook.
    """
    return await orchestrator.run_cycle()
