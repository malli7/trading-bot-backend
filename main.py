from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os
from data import get_indicators, get_full_analysis
from trading_agent import run_agent_cycle, demo_account, run_sentiment_analysis

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    await demo_account.initialize()

@app.get("/indicators")
async def indicators(market_id: int, timeframe: str, limit: int = 20):
    return await get_indicators(timeframe, market_id, limit)

@app.get("/analysis")
async def analysis(market_id: int):
    return await get_full_analysis(market_id)

@app.post("/trade_decision")
async def trade_decision():
    """
    Trigger the AI Agent to analyze markets and make a decision.
    """
    result = await run_agent_cycle()
    return result

@app.post("/sentiment")
async def sentiment_analysis():
    """
    Trigger the AI Agent to analyze market regime.
    """
    result = await run_sentiment_analysis()
    return result

@app.get("/account")
def get_account_info():
    return {
        "cash": demo_account.cash,
        "positions": demo_account.positions,
        "history": demo_account.history,
        "total_value": demo_account.total_value
    }

@app.get("/")
def read_root():
    return {"message": "Trading Bot Backend"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)