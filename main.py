"""
Trading Bot API Main Entry Point.

This module initializes the FastAPI application, configures CORS,
and defines the API endpoints for market data, analysis, and trade execution.
"""
from contextlib import asynccontextmanager
import os
from typing import Dict, Any, List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Project Imports
from data import get_indicators, get_full_analysis
from trading_agent import run_agent_cycle, demo_account

# Load environment variables
load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events.
    Initializes the trading account (MongoDB connection).
    """
    await demo_account.initialize()
    yield
    # Cleanup logic if needed (e.g. close DB connection)
    # if demo_account.db_client: demo_account.db_client.close()

app = FastAPI(
    title="Trading Bot API",
    description="API for Agentic Trading Bot with Swarm Intelligence",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/indicators", response_model=Dict[str, Any])
async def indicators(market_id: int, timeframe: str, limit: int = 20) -> Dict[str, Any]:
    """Fetch technical indicators for a specific market and timeframe."""
    return await get_indicators(timeframe, market_id, limit)

@app.get("/analysis", response_model=Dict[str, Any])
async def analysis(market_id: int) -> Dict[str, Any]:
    """Fetch full analysis including multiple timeframes."""
    return await get_full_analysis(market_id)

@app.post("/trade_decision", response_model=Dict[str, Any])
async def trade_decision() -> Dict[str, Any]:
    """
    Trigger the AI Agent Cycle.
    
    1. Reflection (Review past)
    2. Data Collection
    3. Swarm Analysis (Consensus)
    4. Portfolio Allocation
    5. Execution
    """
    result = await run_agent_cycle()
    return result

@app.get("/account", response_model=Dict[str, Any])
def get_account_info() -> Dict[str, Any]:
    """Retrieve current account status, positions, and history."""
    return {
        "cash": demo_account.cash,
        "positions": demo_account.positions,
        "history": demo_account.history,
        "total_value": demo_account.total_value
    }

@app.get("/")
def read_root() -> Dict[str, str]:
    """Health check endpoint."""
    return {"message": "Trading Bot Backend Operational"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)