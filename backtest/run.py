"""
Backtest Engine Entry Point.

This script runs the Time-Travel Simulation.
It patches the global `demo_account` in the live system to use our `MockAccount`,
fetches historical data, and steps through time, invoking the Agent Orchestrator.
"""
import sys
import os
import asyncio
import logging
import json
from datetime import datetime

# 1. Setup Paths to import backend modules
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(current_dir)
sys.path.append(backend_dir)

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("backtest_engine")

# 2. Dependency Injection / Patching
# We must patch 'account.demo_account' BEFORE importing agents that use it.
from backtest.mock_account import MockAccount
mock_account = MockAccount(initial_balance=1000.0)

import account
account.demo_account = mock_account
logger.info("PATCHED: account.demo_account replaced with MockAccount")

# Now we can safely import agents that reference account.demo_account
from backtest.data_loader import DataLoader
from agents.swarm import SwarmAnalyst
from agents.portfolio import PortfolioManager
from agents.reflection import ReflectionAgent

# 3. The Engine Logic
async def run_backtest():
    logger.info("Initializing Backtest...")
    
    # Initialize Components
    data_loader = DataLoader()
    swarm = SwarmAnalyst()
    portfolio = PortfolioManager()
    reflection = ReflectionAgent()
    
    # Fetch Data (Covering enough for 24h + warmup)
    data_loader.fetch_historical_data(limit=500) 
    
    # Get Timeline
    timeline = data_loader.get_simulation_timeline()
    if not timeline:
        logger.error("No valid timeline found (check data fetching). Exiting.")
        return

    logger.info(f"Full Timeline has {len(timeline)} steps.")
    
    # SIMULATION SETTING: Run last 24 hours (4 * 24 = 96 steps)
    # Changed to 96 for full 24h run
    steps_to_run = 96
    timeline = timeline[-steps_to_run:] if len(timeline) > steps_to_run else timeline
    
    logger.info(f"Running Simulation over last {len(timeline)} steps (~{len(timeline)/4} hours)...")
    
    # Track previous prices for heuristic checks
    previous_prices = {}
    
    try:
        # Simulation Loop
        for i, current_time_ts in enumerate(timeline):
            
            # Format time for logs
            current_time_str = datetime.fromtimestamp(current_time_ts).isoformat()
            logger.info(f"--- Step {i+1}/{len(timeline)} : {current_time_str} ---")
            
            # A. Market Snapshot (The "See" phase)
            market_data_snapshot = data_loader.get_market_snapshot(current_time_ts)
            
            # Extract current prices
            current_prices = {}
            rsi_values = {}
            for symbol, data in market_data_snapshot.items():
                if '15m' in data['indicator_data'] and 'midPrices' in data['indicator_data']['15m']:
                    price = data['indicator_data']['15m']['midPrices'][-1]
                    current_prices[symbol] = price
                    
                    # Store RSI for heuristic check
                    if 'rsi14' in data['indicator_data']['15m']:
                         rsi_values[symbol] = data['indicator_data']['15m']['rsi14'][-1]

            # B. Update Account State (The "Reality" phase)
            await mock_account.update_positions(current_prices)
            
            # C. Reflection (The "Learn" phase)
            # OPTIMIZATION: Run Reflection only once every hour (every 4 steps)
            if i % 4 == 0:
                 await reflection.review_performance(current_prices)
            
            # D. Swarm Analysis (The "Think" phase)
            sentiment_dummy = {"text": "Neutral (Backtest Mode)"}
            
            for symbol, data_feed in market_data_snapshot.items():
                if symbol not in current_prices: continue
                if not data_feed['indicator_data'].get('15m'): continue

                # === FAST MODE OPTIMIZATION ===
                # Check 1: Volatility (Price change < 0.3%)
                prev_price = previous_prices.get(symbol)
                is_boring_price = False
                if prev_price:
                    pct_change = abs((current_prices[symbol] - prev_price) / prev_price) * 100
                    if pct_change < 0.3:
                        is_boring_price = True
                        
                # Check 2: RSI Neutral (40-60)
                curr_rsi = rsi_values.get(symbol, 50)
                is_neutral_rsi = 40 <= curr_rsi <= 60
                
                # Check 3: Current Position? If we are in a trade, we might want to be more attentive.
                # But if price is boring, holding is usually fine.
                # Let's be aggressive with skipping: Skip if Boring Price AND Neutral RSI
                
                should_skip_llm = is_boring_price and is_neutral_rsi
                
                # Force update previous price for next loop
                previous_prices[symbol] = current_prices[symbol]
                
                if should_skip_llm:
                    logger.info(f"Skipping LLM for {symbol} (Fast Mode: Low Volatility & Neutral RSI)")
                    # Default HOLD logic
                    decision = {
                        "signal": "HOLD",
                        "coin": symbol,
                        "leverage": 1,
                        "size": 0.0,
                        "reason": "Fast Mode: Skipped due to low volatility",
                        "invalidation": "None",
                        "timestamp": current_time_str
                    }
                    await mock_account.log_decision(decision)
                    continue
                # ==============================
                
                logger.info(f"Agent thinking on {symbol}...")
                
                # 1. Swarm Consensus
                swarm_result = await swarm.get_consensus(data_feed['indicator_data'], sentiment_dummy)
                
                # 2. Portfolio Decision
                current_pos = mock_account.positions.get(symbol)
                price = current_prices[symbol]
                
                decision = portfolio.allocate(
                    signal=swarm_result["signal"],
                    confidence=swarm_result["confidence"],
                    coin=symbol,
                    price=price,
                    current_position=current_pos,
                    swarm_reason=swarm_result.get("rationale"),
                    swarm_invalidation=swarm_result.get("invalidation")
                )
                
                # 3. Execution
                decision["timestamp"] = current_time_str
                await mock_account.log_decision(decision)
                
                if decision["signal"] not in ["skip_trade", "HOLD"]:
                    await mock_account.execute_trade(decision, price)

    except KeyboardInterrupt:
        logger.warning("Simulation stopped by user.")
    except Exception as e:
        logger.error(f"Simulation failed: {e}")
    finally:
        # End of Simulation
        logger.info("=== Backtest Complete ===")
        logger.info(f"Final Balance: ${mock_account.cash:.2f}")
        logger.info(f"Total Value: ${mock_account.total_value:.2f}")
        
        # Save Report
        report = {
            "final_balance": mock_account.cash,
            "total_value": mock_account.total_value,
            "total_trades": len(mock_account.history),
            "history": mock_account.history
        }
        with open(os.path.join(mock_account.results_dir, "report.json"), "w") as f:
            json.dump(report, f, indent=2, default=str)
            
        print_report(mock_account)

def print_report(account):
    """Print a pretty table of trades."""
    print("\n" + "="*100)
    print(f"{'COIN':<6} | {'ACTION':<10} | {'ENTRY':<10} | {'EXIT':<10} | {'PNL ($)':<10} | {'REASON (OPEN / CLOSE)':<40}")
    print("-" * 100)
    
    history = account.history
    # Group by Coin to find open/close pairs roughly? 
    # Actually the history log is sequential.
    
    # We filter for CLOSED trades to show PnL
    # But user wants "Final Taken Trades" -> which implies Open ones too.
    
    total_pnl = 0.0
    wins = 0
    losses = 0
    
    for trade in history:
        if trade["result"] == "CLOSED":
            pnl = trade.get("pnl", 0.0)
            total_pnl += pnl
            if pnl > 0: wins += 1
            else: losses += 1
            
            # Try to find matching open? (MockAccount history is a flat list of events)
            # For this simple table, we just list the events
            
            action = trade["action"]
            price = trade["price"]
            coin = trade["coin"]
            reason = trade["reason"]
            
            # If it's a CLOSE event, show PnL
            print(f"{coin:<6} | {action:<10} | {'-':<10} | {price:<10.2f} | {pnl:<10.2f} | {reason[:40]}")

        elif trade["result"] == "OPEN":
            action = trade["action"]
            price = trade["price"]
            coin = trade["coin"]
            reason = trade["reason"]
            print(f"{coin:<6} | {action:<10} | {price:<10.2f} | {'-':<10} | {'-':<10} | {reason[:40]}")
            
    print("-" * 100)
    print(f"Total PnL: ${total_pnl:.2f}")
    print(f"Win/Loss: {wins} / {losses}")
    print(f"Final Account Value: ${account.total_value:.2f}")
    print("="*100 + "\n")

if __name__ == "__main__":
    asyncio.run(run_backtest())
