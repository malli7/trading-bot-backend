import os
import json
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, List
from openai import AsyncOpenAI
from motor.motor_asyncio import AsyncIOMotorClient
import certifi
from data import get_full_analysis
from prompt import SYSTEM_PROMPT, USER_PROMPT

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
INITIAL_BALANCE = 1000.0
MARKET_IDS = {
    "ETH": 0,
    "BTC": 1,
    "SOL": 2
}

class PaperTradingAccount:
    def __init__(self, initial_balance: float = INITIAL_BALANCE):
        self.initial_balance = initial_balance
        self.cash = initial_balance
        self.positions: Dict[str, Dict[str, Any]] = {} 
        self.history: List[Dict[str, Any]] = []
        self.db_client = None
        self.db = None
        self.collection = None
        # DO NOT load state in __init__ as it requires async

    async def initialize(self):
        """Initialize MongoDB connection and load state"""
        mongo_uri = os.getenv("MONGO_URI")
        if not mongo_uri:
            logger.error("MONGO_URI not found in env")
            return

        try:
            self.db_client = AsyncIOMotorClient(mongo_uri, tlsCAFile=certifi.where())
            self.db = self.db_client.get_database("trading_bot")
            self.collection = self.db.get_collection("account_state")
            logger.info("Connected to MongoDB")
            await self.load_state()
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")

    async def load_state(self):
        if self.collection is None:
            return

        try:
            # We use a fixed ID for the single account
            data = await self.collection.find_one({"_id": "account_main"})
            if data:
                self.cash = float(data.get("cash", self.initial_balance))
                self.positions = data.get("positions", {})
                self.history = data.get("history", [])
                logger.info("Account state loaded from MongoDB")
            else:
                logger.info("No existing account state found, starting fresh.")
                await self.save_state()
        except Exception as e:
            logger.error(f"Failed to load state from DB: {e}")

    async def save_state(self):
        if self.collection is None:
            return

        try:
            data = {
                "_id": "account_main",
                "cash": self.cash,
                "positions": self.positions,
                "history": self.history,
                "last_updated": datetime.utcnow().isoformat()
            }
            await self.collection.replace_one({"_id": "account_main"}, data, upsert=True)
        except Exception as e:
            logger.error(f"Failed to save state to DB: {e}")

    @property
    def total_value(self) -> float:
        margin_used = sum(p['margin'] for p in self.positions.values())
        unrealized_pnl = sum(p.get('unrealized_pnl', 0) for p in self.positions.values())
        return self.cash + margin_used + unrealized_pnl

    @property
    def total_return_pct(self) -> float:
        return ((self.total_value - self.initial_balance) / self.initial_balance) * 100.0

    def get_positions_str(self) -> str:
        if not self.positions:
            return "no open positions"
        
        pos_strings = []
        for symbol, pos in self.positions.items():
            unrealized = pos.get('unrealized_pnl', 0.0)
            p_str = (f"Symbol: {symbol} Side: {pos['sign']} Entry: {pos['entry_price']} "
                     f"Lev: {pos['leverage']}x Margin: {pos['margin']:.2f} Unr. PNL: {unrealized:.2f}")
            pos_strings.append(p_str)
        return ", ".join(pos_strings)

    async def close_position(self, coin: str, current_price: float, reason: str = "SIGNAL"):
        if coin not in self.positions:
            return
            
        pos = self.positions.pop(coin)
        margin = pos['margin']
        entry = pos['entry_price']
        qty = pos['quantity']
        
        if pos['sign'] == "LONG":
            pnl = (current_price - entry) * qty
        else:
            pnl = (entry - current_price) * qty
            
        returned_amount = margin + pnl
        self.cash += returned_amount
        
        logger.info(f"Closed {coin} ({reason}). PnL: {pnl:.2f}. New Balance: {self.cash:.2f}")
        self.history.append({
            "action": "close", 
            "coin": coin, 
            "price": current_price, 
            "pnl": pnl, 
            "reason": reason,
            "time": datetime.utcnow().isoformat(), 
            "result": "CLOSED"
        })
        await self.save_state()

    async def update_positions(self, current_prices: Dict[str, float]):
        """Update PnL and check for Stops/Take Profits"""
        state_changed = False
        # Iterate over a copy since we might modify the dict (close positions)
        for symbol, pos in list(self.positions.items()):
            if symbol in current_prices:
                curr = current_prices[symbol]
                entry = pos['entry_price']
                qty = pos['quantity']
                
                if pos['sign'] == "LONG":
                    unrealized = (curr - entry) * qty
                else:
                    unrealized = (entry - curr) * qty
                
                if pos.get('unrealized_pnl') != unrealized:
                    pos['unrealized_pnl'] = unrealized
                    state_changed = True
                
                # Check Stop Loss
                sl = pos.get('stop_loss')
                if sl:
                    if pos['sign'] == "LONG" and curr <= sl:
                        await self.close_position(symbol, curr, reason="STOP_LOSS")
                        continue
                    elif pos['sign'] == "SHORT" and curr >= sl:
                        await self.close_position(symbol, curr, reason="STOP_LOSS")
                        continue
                
                # Check Take Profit
                tp = pos.get('take_profit')
                if tp:
                    if pos['sign'] == "LONG" and curr >= tp:
                         await self.close_position(symbol, curr, reason="TAKE_PROFIT")
                         continue
                    elif pos['sign'] == "SHORT" and curr <= tp:
                         await self.close_position(symbol, curr, reason="TAKE_PROFIT")
                         continue
        
        # Save if PnL updated usually fine, or just on close. 
        # Persistence of PnL is nice for UI to see it without re-fetch.
        if state_changed:
            await self.save_state()

    async def execute_trade(self, decision: Dict[str, Any], current_price: float):
        signal = decision.get("signal")
        coin = decision.get("coin")
        
        if signal in ["buy_to_enter", "sell_to_enter"]:
            if coin in self.positions:
                logger.warning(f"Position already exists for {coin}, skipping {signal}")
                return
            
            # Position Sizing Logic check
            quantity = float(decision.get("quantity", 0))
            leverage = int(decision.get("leverage", 1))
            
            # Basic validation
            if quantity <= 0:
                logger.warning("Invalid quantity, skipping")
                return

            position_value_usd = quantity * current_price
            margin_required = position_value_usd / leverage
            
            if margin_required > self.cash:
                logger.warning(f"Insufficient cash for trade. Needed: {margin_required}, Have: {self.cash}")
                return
            
            self.cash -= margin_required
            
            self.positions[coin] = {
                "sign": "LONG" if signal == "buy_to_enter" else "SHORT",
                "entry_price": current_price,
                "quantity": quantity,
                "leverage": leverage,
                "margin": margin_required,
                "stop_loss": decision.get("stop_loss"),
                "take_profit": decision.get("profit_target"),
                "unrealized_pnl": 0.0,
                "timestamp": datetime.utcnow().isoformat()
            }
            logger.info(f"Executed {signal} on {coin} @ {current_price} with {margin_required:.2f} margin")
            self.history.append({"action": signal, "coin": coin, "price": current_price, "time": datetime.utcnow().isoformat(), "result": "OPEN"})
            await self.save_state()

        elif signal == "close":
             await self.close_position(coin, current_price, reason="SIGNAL")

        else:
            logger.info(f"Signal: {signal} for {coin} - No action taken")

# Global Account Instance
demo_account = PaperTradingAccount()

async def get_all_market_data():
    """Fetch data for all tracked markets"""
    import asyncio
    
    # IDs defined in data.py logic: ETH=0, BTC=1, SOL=2
    ids = [(0, "ETH"), (1, "BTC"), (2, "SOL")]
    
    tasks = [get_full_analysis(mid) for mid, _ in ids]
    results = await asyncio.gather(*tasks)
    
    # Results is a list of dicts: { "symbol": "BTC", "indicator_data": {...} }
    # We want a dict: { "BTC": { ... }, "ETH": { ... } }
    
    all_data = {}
    prices = {}
    
    for res in results:
        symbol = res['symbol']
        # Try to extract current price from the latest 5m midPrice
        try:
            current_price = res['indicator_data']['15m']['midPrices'][-1]
            prices[symbol] = current_price
        except (KeyError, IndexError):
            prices[symbol] = 0.0
            
        all_data[symbol] = res['indicator_data']
        
    return all_data, prices

async def run_agent_cycle():
    """Main function to run one trading cycle"""
    
    # Ensure DB is initialized if not already
    if demo_account.collection is None:
        await demo_account.initialize()

    # 1. Gather Data
    market_data, current_prices = await get_all_market_data()
    
    # Update positions with new prices
    await demo_account.update_positions(current_prices)
    
    # 2. Format Prompt
    # Need to make sure json dumping handles standard types
    market_state_str = json.dumps(market_data, default=str)
    
    formatted_user_prompt = USER_PROMPT.format(
        ALL_INDICATOR_DATA=market_state_str,
        TOTAL_RETURN=f"{demo_account.total_return_pct:.2f}",
        AVAILABLE_CASH=f"${demo_account.cash:.2f}",
        ACCOUNT_VALUE=f"${demo_account.total_value:.2f}",
        OPEN_POSITIONS=demo_account.get_positions_str()
    )
    
    full_prompt = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": formatted_user_prompt}
    ]
    
    # 3. Call AI
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        logger.error("OPENROUTER_API_KEY not found in env")
        return {"status": "error", "message": "Missing API Key"}
        
    client = AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )
    
    #model = "nex-agi/deepseek-v3.1-nex-n1:free"
    #model = "nvidia/nemotron-3-nano-30b-a3b:free" 
    model = "google/gemini-3-flash-preview" 
    # # Defaulting to a high capability model, or we can use deepseek/deepseek-chat
    # User had "deepseek" in snippets, maybe deepseek-chat is better/cheaper?
    # Let's try to stick to something standard unless configured.
    # I'll use "openai/gpt-4o" as it's reliable for complex JSON following.
    
    try:
        completion = await client.chat.completions.create(
            model=model,
            messages=full_prompt,
            temperature=0.1
        )
        
        response_content = completion.choices[0].message.content
        logger.info(f"AI Response provided")
        
        # 4. Parse Decision
        # Handles potential markdown code blocks
        clean_content = response_content.strip()
        if clean_content.startswith("```json"):
            clean_content = clean_content[7:]
        if clean_content.endswith("```"):
            clean_content = clean_content[:-3]
        
        decision_data = json.loads(clean_content)
        
        # Ensure it is a list
        decisions = []
        if isinstance(decision_data, dict):
             decisions = [decision_data]
        elif isinstance(decision_data, list):
             decisions = decision_data
        else:
             logger.warning("Unknown decision format")
        
        results = []
        for decision in decisions:
            target_coin = decision.get("coin")
            if target_coin and target_coin in current_prices:
                await demo_account.execute_trade(decision, current_prices[target_coin])
                results.append(decision)
        
        return {
            "status": "success", 
            "decisions": results, 
            "account_summary": {
                "cash": demo_account.cash,
                "positions": demo_account.positions
            }
        }
        
    except Exception as e:
        logger.exception("Error in trading cycle")
        return {"status": "error", "message": str(e)}

