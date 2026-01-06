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
# Now we can safely import agents that reference account.demo_account
from backtest.data_loader import DataLoader
from services.orchestrator import TradingOrchestrator

# 3. The Engine Logic
async def run_backtest(days: int = 1, fetch_limit: int = 1000):
    logger.info(f"Initializing Backtest for {days} days (Fetch limit: {fetch_limit})...")
    
    # Initialize Components
    data_loader = DataLoader()
    orchestrator = TradingOrchestrator()
    
    # Fetch Data (Covering enough for N days + warmup)
    data_loader.fetch_historical_data(limit=fetch_limit) 
    
    # Get Timeline
    timeline = data_loader.get_simulation_timeline()
    if not timeline:
        logger.error("No valid timeline found (check data fetching). Exiting.")
        return

    logger.info(f"Full Timeline has {len(timeline)} steps.")
    
    # SIMULATION SETTING: Run last N days (96 steps per day)
    steps_to_run = days * 96
    timeline = timeline[-steps_to_run:] if len(timeline) > steps_to_run else timeline
    
    logger.info(f"Running Simulation over last {len(timeline)} steps (~{days} days)...")
    
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
                 await orchestrator.reflection.review_performance(current_prices)
            
            # D. Swarm Analysis (The "Think" phase) - PARALLELIZED
            sentiment_dummy = {"text": "Neutral (Backtest Mode)"}
            
            async def process_asset(symbol, data_feed):
                if symbol not in current_prices: return
                if not data_feed['indicator_data'].get('15m'): return

                # === FAST MODE / DEFENSIVE SKIP LOGIC ===
                current_price = current_prices[symbol]
                prev_price = previous_prices.get(symbol)
                
                # Check for open position
                current_pos = mock_account.positions.get(symbol)
                has_position = current_pos is not None
                
                should_skip = False
                
                if prev_price:
                    pct_change = ((current_price - prev_price) / prev_price) * 100
                    abs_change = abs(pct_change)
                    
                    # Heuristic Thresholds:
                    # User requested 0.3% for volatile asset SOL, 0.2% for BTC/ETH
                    threshold = 0.3 if symbol == "SOL" else 0.2
                    is_small_move = abs_change < threshold
                    
                    if not has_position:
                        # CASE 1: No Position. 
                        # Skip if move is small (noise/consolidation).
                        should_skip = is_small_move
                    else:
                        # CASE 2: In Position. 
                        # "Defensive Skip": Only skip if move is small AND favorable/neutral.
                        # Do NOT skip if move is adverse (Red for Long, Green for Short).
                        
                        is_long = current_pos['sign'] == "LONG"
                        is_adverse = (is_long and pct_change < 0) or (not is_long and pct_change > 0)
                        
                        if is_adverse:
                            should_skip = False # ALWAYS check if moving against us
                        else:
                            should_skip = is_small_move # Skip if small profit/flat
                
                if should_skip:
                    logger.info(f"Skipping LLM for {symbol} (Fast Mode: Small Move < {threshold}%)")
                    # Default HOLD logic
                    decision = {
                        "signal": "HOLD",
                        "coin": symbol,
                        "leverage": 1,
                        "size": 0.0,
                        "reason": "Fast Mode: Skipped",
                        "invalidation": "None",
                        "timestamp": current_time_str
                    }
                    await mock_account.log_decision(decision)
                    return

                # ==============================
                
                logger.info(f"Agent thinking on {symbol}...")
                
                # ORCHESTRATOR LOGIC (Swarm -> Portfolio -> Risk)
                decision = await orchestrator.process_asset_logic(
                    symbol, 
                    data_feed['indicator_data'], 
                    sentiment_dummy, 
                    current_prices
                )
                
                # 3. Execution
                decision["timestamp"] = current_time_str
                await mock_account.log_decision(decision)
                
                if decision["signal"] not in ["skip_trade", "HOLD", "WAIT"]:
                    await mock_account.execute_trade(decision, current_price)

            # Create tasks
            tasks = []
            for symbol, data_feed in market_data_snapshot.items():
                tasks.append(process_asset(symbol, data_feed))
            
            # Execute in parallel
            await asyncio.gather(*tasks)

            # Update previous prices for next loop
            # We do this update AFTER the step logic so we compare vs previous step
            previous_prices.update(current_prices)

    except KeyboardInterrupt:
        logger.warning("Simulation stopped by user.")
    except Exception as e:
        logger.error(f"Simulation failed: {e}")
    finally:
        # End of Simulation
        logger.info("=== Backtest Complete ===")
        
        # Print trades table FIRST (Restored)
        try:
            print_report(mock_account)
        except Exception as report_err:
            logger.error(f"Report Generation Failed: {report_err}")
            
        # 4. Generate Brutal Review
        await generate_brutal_review(mock_account, orchestrator.client)
        
        # Cleanup Data Cache
        if os.path.exists(data_loader.data_dir):
            import shutil
            shutil.rmtree(data_loader.data_dir)
            logger.info("Cleanup: Deleted raw data cache.")

def print_report(account):
    """Print a pretty table of trades."""
    print("\n" + "="*100)
    print(f"{'COIN':<6} | {'ACTION':<10} | {'ENTRY':<10} | {'EXIT':<10} | {'PNL ($)':<10} | {'REASON (OPEN / CLOSE)':<40}")
    print("-" * 100)
    
    history = account.history
    total_pnl = 0.0
    wins = 0
    losses = 0
    
    for trade in history:
        if trade["result"] == "CLOSED":
            pnl = trade.get("pnl", 0.0)
            total_pnl += pnl
            if pnl > 0: wins += 1
            else: losses += 1
            
            action = trade["action"]
            price = trade["price"]
            coin = trade["coin"]
            reason = trade.get("reason", "No reason")
            
            # If it's a CLOSE event, show PnL
            print(f"{coin:<6} | {action:<10} | {'-':<10} | {price:<10.2f} | {pnl:<10.2f} | {reason[:40]}")

        elif trade["result"] == "OPEN":
            action = trade["action"]
            price = trade["price"]
            coin = trade["coin"]
            reason = trade.get("reason", "No reason")
            print(f"{coin:<6} | {action:<10} | {price:<10.2f} | {'-':<10} | {'-':<10} | {reason[:40]}")
            
    print("-" * 100)
    print(f"Total Realized PnL: ${total_pnl:.2f}")
    print(f"Win/Loss: {wins} / {losses}")
    print(f"Final Account Value: ${account.total_value:.2f}")
    print("="*100 + "\n")

async def generate_brutal_review(account, client):
    """
    Ask the LLM to brutally review the backtest performance.
    """
    logger.info("Generating Brutal Performance Review...")
    
    # Calculate Metrics
    history = account.history
    closed_trades = [t for t in history if t["result"] == "CLOSED"]
    open_trades = [t for t in history if t["result"] == "OPEN" and not any(c for c in history if c["result"] == "CLOSED" and c["coin"] == t["coin"] and c.get("entry_price") == t["price"])] 
    # Logic for open trades above is imperfect if multiple trades on same coin. 
    # Better: usage account.positions for current open state.
    current_positions = account.positions
    
    total_closed = len(closed_trades)
    
    wins = [t for t in closed_trades if t["pnl"] > 0]
    win_rate = (len(wins) / total_closed * 100) if total_closed > 0 else 0.0
    
    total_realized_pnl = sum(t["pnl"] for t in closed_trades)
    avg_pnl = (total_realized_pnl / total_closed) if total_closed > 0 else 0.0
    
    # Calculate Unrealized PnL from active positions
    unrealized_pnl = sum(p.get('unrealized_pnl', 0) for p in current_positions.values())
    
    # Max Drawdown Approximation
    peak = account.initial_balance
    max_dd = 0
    curr_balance = account.initial_balance
    
    # Replay balance history roughly
    for t in history:
        if t["result"] == "CLOSED":
            curr_balance = t["balance_after"]
            if curr_balance > peak: peak = curr_balance
            dd = (peak - curr_balance) / peak * 100
            if dd > max_dd: max_dd = dd
            
    summary = f"""
    Strategy Performance Metrics:
    - Initial Balance: ${account.initial_balance}
    - Current Cash: ${account.cash:.2f}
    - Realized PnL: ${total_realized_pnl:.2f}
    - Unrealized PnL: ${unrealized_pnl:.2f}
    - Total Value (Equity): ${account.total_value:.2f}
    
    - Closed Trades: {total_closed}
    - Open Positions: {len(current_positions)}
    - Win Rate (Closed): {win_rate:.1f}%
    - Max Drawdown (Realized): {max_dd:.2f}%
    
    Recent Trade History (Last 20 events):
    {json.dumps(history[-20:], default=str, indent=1)}
    
    Current Positions:
    {json.dumps(current_positions, default=str, indent=1)}
    """
    
    prompt = f"""
    You are a Brutal Hedge Fund Manager reviewing a trading bot's backtest results.
    
    Review the following performance metrics, trade history, and current active positions.
    Even if there are no closed trades, analyze the OPEN positions and the entry logic based on the history log.
    
    DATA:
    {summary}
    
    TASK:
    1. Critique the strategy brutally. Be harsh. Look for weak hands, poor risk management, or lucky streaks. 
    2. Any floating losses in open positions? Roast them.
    3. Analyze the Win Rate vs. Risk/Reward (if any trades closed).
    4. Give a final Score (0-100) on whether this logic is production-ready.
    5. Provide 3 concrete improvements.
    
    OUTPUT FORMAT:
    ## Brutal Review
    [Your critique here]
    
    ## Score: [X]/100
    
    ## Improvements
    1. ...
    """
    
    try:
        completion = await client.chat.completions.create(
            model="google/gemini-2.0-flash-001", 
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )
        review = completion.choices[0].message.content
        
        # Save and Print
        review_path = os.path.join(account.results_dir, "brutal_review.md")
        with open(review_path, "w") as f:
            f.write(review)
            
        print("\n" + "="*40 + " BRUTAL REVIEW " + "="*40)
        print(review)
        print("="*95 + "\n")
        
    except Exception as e:
        logger.error(f"Failed to generate review: {e}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run Trading Bot Backtest")
    parser.add_argument("--days", type=int, default=1, help="Number of days to simulate")
    args = parser.parse_args()
    
    # Calculate steps: 4 candles/hr * 24 hr/day * days
    # Add buffer for indicators (waiting for 50-100 candles)
    STEPS_PER_DAY = 96
    total_steps = args.days * STEPS_PER_DAY
    # fetch ample data
    fetch_limit = total_steps + 500 
    
    # We pass these to run_backtest via global/env or just modify run_backtest signature
    # Since run_backtest is async and currently 0 args, let's just modify the hardcoded values inside run_backtest logic
    # or better, Update run_backtest to accept arguments.
    
    # Small hack: Inject into global scope for simplicity given current structure, 
    # or better, refactor run_backtest to take args.
    
    asyncio.run(run_backtest(days=args.days, fetch_limit=fetch_limit))
