"""
Backtest Entry Point (The Runner)
=================================

Why This Module Exists
----------------------
This script serves as the CLI entry point for the simulation engine.
It handles argument parsing, configuration initialization, and triggers the `BacktestEngine`.
It effectively separates the "Configuration" concern from the "Execution" concern (in `engine.py`).
"""
import asyncio
import sys
import os
import argparse

# Path Setup
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.engine import BacktestEngine

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Agentic Backtest")
    parser.add_argument("--days", type=int, default=1, help="Days to simulate")
    parser.add_argument("--limit", type=int, default=None, help="Candles to fetch (Default: days*96 + 300 buffer)")
    
    args = parser.parse_args()
    
    # Logic: 96 steps/day (15m candles)
    STEPS_PER_DAY = 96
    needed = args.days * STEPS_PER_DAY
    
    # If limit not specified, calculate minimal needed + buffer for indicators (EMA200 etc)
    if args.limit:
        fetch = args.limit
    else:
        fetch = needed + 300
    
    engine = BacktestEngine(days=args.days, fetch_limit=fetch)
    asyncio.run(engine.run())
