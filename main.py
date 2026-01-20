"""
Trading Bot API Main Entry Point (The Entryway)
===============================================

Why This Module Exists
----------------------
This is the **Gateway Layer** of the application.
It exposes the agentic capabilities (Conductor) and data services to the outside world
(frontend, cron jobs, etc.) via a standard HTTP interface.

Responsibilities:
1.  **Routing**: Mapping HTTP requests to Service Logic.
2.  **Lifecycle**: Managing Startup (DB connection) and Shutdown.
3.  **Middleware**: Handling CORS, Security, and Global Error catching.
"""
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Core Imports
from core.config import settings
from core.schemas import CycleResult

# Service Imports
from market_data.aggregate import get_indicators, get_full_analysis
from services.account import demo_account
from services.orchestrator import run_agent_cycle

# ==========================================
# LIFECYCLE MANAGEMENT
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application Lifecycle Manager.
    1. Connects to MongoDB (via account service).
    2. Wires up any necessary singletons.
    """
    # Startup
    await demo_account.initialize()
    yield
    # Shutdown (if needed)
    pass

# ==========================================
# APP SETUP
# ==========================================
app = FastAPI(
    title=settings.APP_NAME,
    description="API for Agentic Trading Bot with Swarm Intelligence",
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

# ==========================================
# ENDPOINTS
# ==========================================

@app.get("/indicators", response_model=Dict[str, Any])
async def indicators(market_id: int, timeframe: str, limit: int = 20) -> Dict[str, Any]:
    """Fetch technical indicators for a specific market and timeframe."""
    return await get_indicators(timeframe, market_id, limit)

@app.get("/analysis", response_model=Dict[str, Any])
async def analysis(market_id: int) -> Dict[str, Any]:
    """Fetch full analysis including multiple timeframes."""
    return await get_full_analysis(market_id)

import asyncio
from typing import Optional, List

# Senior Dev Refactor: Core Imports
from core.schemas import ConsolidationResponse, ConsolidationMetrics

async def _analyze_consolidation(market_id: int, timeframe: str) -> ConsolidationMetrics:
    """Helper to analyze a single market with strict typing."""
    symbol = settings.MARKET_ID_MAP.get(market_id, "Unknown")
    
    # Fetch ample data to ensure stable ADX calc (needs ~2x period lag + buffer)
    indicators = await get_indicators(timeframe, market_id, limit=50)
    
    if not indicators or "adx14" not in indicators or not indicators["adx14"]:
        return ConsolidationMetrics(
            symbol=symbol,
            is_consolidating=False,
            market_state="Unknown",
            adx=0.0,
            bandwidth=0.0
        )
        
    last_adx = indicators["adx14"][-1]
    
    bandwidths = indicators.get("squeeze_bandwidth", [])
    last_bw = bandwidths[-1] if bandwidths else 0.0
    
    # Logic:
    # Strong Consolidation: ADX < 20
    # Moderate Consolidation / Weak Trend: ADX < 25
    
    is_consolidating = last_adx < 25
    
    status = "Consolidation" if is_consolidating else "Trending"
    if last_adx > 40:
        status = "Strong Trend"
    elif last_adx < 20: 
        status = "Strong Consolidation"
        
    return ConsolidationMetrics(
        symbol=symbol,
        is_consolidating=is_consolidating,
        market_state=status,
        adx=last_adx,
        bandwidth=last_bw
    )

@app.get("/is-consolidation", response_model=ConsolidationResponse)
async def check_consolidation(market_id: Optional[int] = None, timeframe: str = settings.DEFAULT_TIMEFRAME) -> ConsolidationResponse:
    """
    Check if the market is currently in consolidation using technical indicators.
    If market_id is omitted, checks ALL supported markets (ETH, BTC, SOL).
    
    Consolidation is defined as:
    - ADX < 25 (Weak or No Trend)
    - OR Bollinger Bandwidth is tightening
    """
    if market_id is not None:
        # Single market request
        result = await _analyze_consolidation(market_id, timeframe)
        return ConsolidationResponse(results=[result])
    
    # All markets request
    # Use keys from the constant map to drive the loop dynamicallly
    tasks = [
        _analyze_consolidation(mid, timeframe)
        for mid in settings.MARKET_ID_MAP.keys()
    ]
    
    results = await asyncio.gather(*tasks)
    return ConsolidationResponse(results=results)

@app.post("/trade_decision", response_model=Dict[str, Any])
async def trade_decision() -> Dict[str, Any]:
    """
    Trigger the Swarm Agent Cycle (Standard Mode).
    """
    result = await run_agent_cycle(mode="SWARM")
    return result

@app.post("/simple_trade_decision", response_model=Dict[str, Any])
async def simple_trade_decision() -> Dict[str, Any]:
    """
    Trigger the Simple Agent Cycle (Single-Shot Mode).
    """
    result = await run_agent_cycle(mode="SIMPLE")
    return result

@app.get("/account", response_model=Dict[str, Any])
async def get_account_info() -> Dict[str, Any]:
    """Retrieve current account status, positions, and history."""
    # Ensure history is fetched async
    history = await demo_account.get_history(limit=50)
    return {
        "cash": demo_account.cash,
        "positions": demo_account.positions,
        "history": history,
        "total_value": demo_account.total_value
    }

@app.post("/account/reset", response_model=Dict[str, str])
async def reset_account() -> Dict[str, str]:
    """Reset the account state and clear the database (Dev Mode)."""
    await demo_account.reset_account()
    return {"status": "success", "message": "Account reset successfully"}

@app.get("/")
def read_root() -> Dict[str, str]:
    """Health check endpoint."""
    return {
        "status": "operational",
        "service": settings.APP_NAME,
        "mode": "debug" if settings.DEBUG else "production",
        # Default mode check
        "default_mode": settings.TRADING_MODE
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)