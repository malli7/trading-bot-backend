"""
Trading Bot API Main Entry Point.

This module initializes the FastAPI application, configures CORS,
and defines the API endpoints using the Refactored Services.
"""
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Core Imports
from core.config import settings
from core.schemas import CycleResult, IndicatorResponse, AnalysisResponse

# Service Imports
from data import get_indicators, get_full_analysis
from account import demo_account
from services.orchestrator import run_agent_cycle

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events.
    Initializes the trading account (MongoDB connection).
    """
    await demo_account.initialize()
    yield
    # Cleanup logic if needed

app = FastAPI(
    title=settings.APP_NAME,
    description="API for Agentic Trading Bot with Swarm Intelligence (v2)",
    version="2.1.0",
    lifespan=lifespan,
    debug=settings.DEBUG
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
    # run_agent_cycle now returns a Dict compatible with CycleResult schema
    # But for now we keep Dict[str, Any] as response model to be safe until we verify schema match perfectly
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
    return {"message": f"{settings.APP_NAME} Operational"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)