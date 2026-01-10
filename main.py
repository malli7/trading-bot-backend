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

@app.post("/trade_decision", response_model=Dict[str, Any])
async def trade_decision() -> Dict[str, Any]:
    """
    Trigger the AI Agent Cycle (The Conductor).
    Executes: Learn -> See -> Think -> Decide -> Act.
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
        "mode": "debug" if settings.DEBUG else "production"
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)