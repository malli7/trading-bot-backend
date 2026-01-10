"""
Backtest Engine (The Simulator)
===============================

Why This Module Exists
----------------------
To validate the agent's logic against historical data without risking real capital.
It wraps the `Orchestrator` and `MockAccount` in a time-travel loop.

Key Features:
1.  **Time Travel**: Steps through historical candles as if they were live.
2.  **Fast Mode**: Heuristics to skip LLM calls during low-volatility "chop" (saves tokens).
3.  **Brutal Review**: Auto-generates a critical performance report at the end.
"""
import logging
import asyncio
import json
import os
import shutil
from datetime import datetime
from typing import Dict, Any, List, Optional

# Core / Services
from core.config import settings
from services.orchestrator import TradingOrchestrator
import services.account

# Local Imports
from backtest.mock_account import MockAccount
from backtest.data_loader import DataLoader

logger = logging.getLogger("backtest_engine")

class BacktestEngine:
    """
    Manages the simulation lifecycle.
    """
    
    def __init__(self, days: int = 1, fetch_limit: int = 1000):
        self.days = days
        self.fetch_limit = fetch_limit
        
        # Heuristics Configuration
        self.SKIP_RSI_LOWER = 45
        self.SKIP_RSI_UPPER = 55
        self.SKIP_CHANGE_PCT_MAJORS = 0.2 # BTC, ETH
        self.SKIP_CHANGE_PCT_VOLATILE = 0.3 # SOL

        
        # State
        self.previous_prices: Dict[str, float] = {}
        self.mock_account = MockAccount(initial_balance=settings.ACCOUNT_INITIAL_BALANCE)
        
        # Inject Mock Account
        services.account.demo_account = self.mock_account
        logger.info("[Setup] Patched services.account.demo_account with MockAccount")
        
        self.orchestrator = TradingOrchestrator()
        self.data_loader = DataLoader()

    async def run(self):
        """Execute the backtest simulation."""
        logger.info(f"Initializing Backtest for {self.days} days...")
        
        # 1. Fetch Data
        self.data_loader.fetch_historical_data(limit=self.fetch_limit)
        timeline = self.data_loader.get_simulation_timeline()
        
        if not timeline:
            logger.error("No timeline data. Aborting.")
            return

        # Slice timeline to requested duration
        steps_per_day = 96 # 15m candles
        total_steps = self.days * steps_per_day
        if len(timeline) > total_steps:
            timeline = timeline[-total_steps:]
            
        logger.info(f"Starting Simulation Loop: {len(timeline)} steps...")
        
        try:
            for i, current_ts in enumerate(timeline):
                await self._process_step(i, current_ts, len(timeline))
                
        except KeyboardInterrupt:
            logger.warning("Backtest interrupted by user.")
        except Exception as e:
            logger.error(f"Backtest Crash: {e}", exc_info=True)
        finally:
            await self._generate_report()
            self._cleanup()

    async def _process_step(self, step_idx: int, current_ts: float, total_steps: int):
        """Handle a single simulation step."""
        current_time_str = datetime.fromtimestamp(current_ts).isoformat()
        if step_idx % 4 == 0: # Log every hour
            logger.info(f"--- Step {step_idx+1}/{total_steps} : {current_time_str} ---")

        # A. Market Snapshot (The "See" phase)
        market_data = self.data_loader.get_market_snapshot(current_ts)
        
        # Extract metadata for heuristics
        current_prices = {}
        rsi_values = {}
        
        for symbol, data in market_data.items():
            mid_prices = data.get('indicator_data', {}).get('15m', {}).get('midPrices', [])
            if mid_prices:
                current_prices[symbol] = mid_prices[-1]
                
            rsi_series = data.get('indicator_data', {}).get('15m', {}).get('rsi14', [])
            if rsi_series:
                rsi_values[symbol] = rsi_series[-1]

        # B. Update Account (Mark-to-Market)
        await self.mock_account.update_positions(current_prices)
        
        # C. Reflection (Every 4 steps / 1 hour)
        if step_idx % 4 == 0:
             await self.orchestrator.reflection.review_performance(current_prices)
             
        # D. Swarm Analysis (Parallel)
        tasks = []
        for symbol, feed in market_data.items():
            tasks.append(self._analyze_asset(symbol, feed, current_prices, rsi_values, current_time_str))
            
        if tasks:
            await asyncio.gather(*tasks)
            
        # Update Cache
        self.previous_prices.update(current_prices)

    async def _analyze_asset(
        self, 
        symbol: str, 
        feed: Dict, 
        current_prices: Dict[str, float], 
        rsi_values: Dict[str, float],
        timestamp_str: str
    ):
        """
        Run Orchestrator pipeline for one asset, with 'Fast Mode' skipping.
        """
        if symbol not in current_prices: return
        
        # check skip
        if self._should_skip(symbol, current_prices[symbol], rsi_values.get(symbol)):
             # Log HOLD and exit
             decision = {
                 "coin": symbol,
                 "signal": "HOLD",
                 "reason": "Fast Mode: Skipped (Low Volatility/Neutral)",
                 "invalidation": "N/A",
                 "timestamp": timestamp_str
             }
             await self.mock_account.log_decision(decision)
             return

        # Run Real Analysis
        decision = await self.orchestrator._run_analysis_pipeline(symbol, feed, current_prices)
        decision["timestamp"] = timestamp_str
        
        await self.mock_account.log_decision(decision)
        
        # Execution
        if decision["signal"] not in ["skip_trade", "HOLD", "WAIT"]:
             await self.mock_account.execute_trade(decision, current_prices[symbol])

    def _should_skip(self, symbol: str, current_price: float, rsi: Optional[float]) -> bool:
        """
        Heuristic to determine if we should waste tokens on this candle.
        """
        # 1. Always analyze if we have a position (Defensive)
        if symbol in self.mock_account.positions:
            return False
            
        # 2. Check Price Movement
        prev = self.previous_prices.get(symbol)
        if not prev: return False # First run
        
        pct_change = abs((current_price - prev) / prev) * 100
        
        # Dynamic Threshold
        if symbol in ["BTC", "ETH"]:
            threshold = self.SKIP_CHANGE_PCT_MAJORS
        else:
            threshold = self.SKIP_CHANGE_PCT_VOLATILE
        
        # 3. Check RSI Neutrality
        is_rsi_neutral = False
        if rsi:
            is_rsi_neutral = (self.SKIP_RSI_LOWER <= rsi <= self.SKIP_RSI_UPPER)
            
        # Decision: SKIP if (Small Move) AND (RSI is Neutral or Missing)
        if pct_change < threshold and is_rsi_neutral:
            return True
            
        return False

    async def _generate_report(self):
        """Generate summary and brutal review."""
        print("\n" + "="*60)
        print(" FINAL REPORT ")
        print("="*60)
        
        # Print Table
        self._print_trade_table()
        
        # AI Review
        await self._generate_ai_review()

    def _print_trade_table(self):
        history = self.mock_account.history
        print(f"{'COIN':<6} | {'ACTION':<10} | {'PNL':<10} | {'REASON'}")
        print("-" * 60)
        for t in history:
            if t['result'] == 'CLOSED':
                 print(f"{t['coin']:<6} | {t['action']:<10} | {t.get('pnl',0):<10.2f} | {t.get('reason','-')[:30]}")
        print("-" * 60)
        print(f"Final Balance: ${self.mock_account.total_value:.2f}")

    async def _generate_ai_review(self):
        """Uses the orchestrator's client to review performance."""
        # Simple extraction of metrics
        closed = [t for t in self.mock_account.history if t['result'] == "CLOSED"]
        wins = len([t for t in closed if t['pnl'] > 0])
        total = len(closed)
        win_rate = (wins/total*100) if total else 0
        
        summary = f"Trades: {total}, WinRate: {win_rate:.1f}%, Final Value: ${self.mock_account.total_value}"
        
        prompt = f"Review this backtest result brutally: {summary}. Brief critique."
        
        try:
            resp = await self.orchestrator.client.chat.completions.create(
                model="google/gemini-2.0-flash-001",
                messages=[{"role": "user", "content": prompt}]
            )
            print("\nAI Critique:")
            print(resp.choices[0].message.content)
        except Exception as e:
            logger.error(f"Review failed: {e}")

    def _cleanup(self):
        if os.path.exists(self.data_loader.data_dir):
            shutil.rmtree(self.data_loader.data_dir)
            logger.info("Cleaned up data cache.")
