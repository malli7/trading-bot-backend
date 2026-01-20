"""
Trading Account execution Module (The Body)
===========================================

Why This Module Exists
----------------------
This is the **Execution Layer** of the agent. 
While the Agents (Mind) make decisions, this module (Body) holds the keys to the wallet.

Responsibilities:
1.  **State Management**: Tracks Cash, Positions, and History.
2.  **Gatekeeping**: Enforces hard limits (Max Margin, Max Risk) from `config.py` 
    *before* any trade is executed, regardless of what the AI suggests.
3.  **Persistence**: Saves state to MongoDB so the bot doesn't "forget" its money on restart.
"""
import os
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

import certifi
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from dotenv import load_dotenv

# Load env variables (ensures we have MONGO_URI)
load_dotenv()

from core.config import settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

INITIAL_BALANCE = settings.ACCOUNT_INITIAL_BALANCE


class PaperTradingAccount:
    """
    Manages a virtual trading account state backed by MongoDB.
    
    Attributes:
        cash (float): Available cash balance.
        positions (Dict): Open positions keyed by symbol.
        db (AsyncIOMotorDatabase): MongoDB Database reference.
    """
    
    def __init__(self, initial_balance: float = INITIAL_BALANCE):
        self.initial_balance = initial_balance
        self.cash = initial_balance
        self.positions: Dict[str, Dict[str, Any]] = {} 
        # self.history removed to avoid memory/doc size issues
        
        # Database connections (Initialized lazily)
        self.db_client: Optional[AsyncIOMotorClient] = None
        self.db: Optional[AsyncIOMotorDatabase] = None
        self.collection = None
        self.history_collection = None
        self.sentiment_collection = None
        self.lessons_collection = None
        self.decision_collection = None

    async def initialize(self) -> None:
        """Initialize MongoDB connection and load persistence state."""
        mongo_uri = os.getenv("MONGO_URI")
        if not mongo_uri:
            logger.error("MONGO_URI not found in env")
            return

        try:
            self.db_client = AsyncIOMotorClient(mongo_uri, tlsCAFile=certifi.where())
            # Use 'trading_bot' database
            self.db = self.db_client["trading_bot"]
            
            # Setup Collections
            self.collection = self.db.get_collection("account_state")
            self.history_collection = self.db.get_collection("trade_history") # New collection
            self.lessons_collection = self.db.get_collection("lessons_learned")
            self.decision_collection = self.db.get_collection("decision_logs")
            self.sentiment_collection = self.db.get_collection("sentiment_logs")
            
            logger.info("Connected to MongoDB")
            await self.load_state()
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")

    # ... log_decision, log_sentiment, save_lesson ... (unchanged logic, skipping re-write in tool call if possible, but simpler to replace block if contiguous)
    # Actually, execute_trade and getters are lower down.
    # I will replace the block from init to reset_account, keeping the logging helpers if they are in between.
    
    async def log_decision(self, decision: Dict[str, Any]) -> None:
        """Log every decision (Trade/Skip/Hold)."""
        if self.decision_collection is None: return
        try:
            doc = decision.copy()
            doc["timestamp"] = datetime.utcnow().isoformat()
            await self.decision_collection.insert_one(doc)
        except Exception as e:
            logger.error(f"Failed to log decision: {e}")

    async def log_sentiment_analysis(self, data: Dict[str, Any]) -> None:
        """Persist sentiment analysis results."""
        if self.sentiment_collection is None: return
        try:
            await self.sentiment_collection.insert_one(data)
        except Exception as e:
            logger.error(f"Failed to save sentiment analysis: {e}")

    async def save_lesson(self, lesson: str, source_decision_id: Optional[str] = None) -> None:
        """Save a learned lesson to the database."""
        if self.lessons_collection is None: return
        try:
            doc = {
                "timestamp": datetime.utcnow().isoformat(),
                "lesson": lesson,
                "source_decision_id": source_decision_id
            }
            await self.lessons_collection.insert_one(doc)
            logger.info(f"Lesson saved: {lesson}")
        except Exception as e:
            logger.error(f"Failed to save lesson: {e}")

    async def get_recent_lessons(self, limit: int = 5) -> List[str]:
        """Fetch the most recent lessons learned."""
        if self.lessons_collection is None: return []
        try:
            cursor = self.lessons_collection.find().sort("timestamp", -1).limit(limit)
            lessons = []
            async for doc in cursor:
                lessons.append(doc.get("lesson", ""))
            return lessons
        except Exception as e:
            logger.error(f"Failed to fetch lessons: {e}")
            return []

    async def load_state(self) -> None:
        """Load account balance and positions. Migrate history if needed."""
        if self.collection is None: return

        try:
            data = await self.collection.find_one({"_id": "account_main"})
            if data:
                self.cash = float(data.get("cash", self.initial_balance))
                self.positions = data.get("positions", {})
                
                # MIGRATION: Check for legacy history list
                legacy_history = data.get("history")
                if legacy_history and isinstance(legacy_history, list) and len(legacy_history) > 0:
                    logger.warning(f"Migrating {len(legacy_history)} trades to 'trade_history' collection...")
                    if self.history_collection is not None:
                        # Bulk insert
                        await self.history_collection.insert_many(legacy_history)
                        # Remove from account_state
                        await self.collection.update_one(
                            {"_id": "account_main"}, 
                            {"$unset": {"history": ""}}
                        )
                    logger.info("Migration complete.")
                
                logger.info("Account state loaded from MongoDB")
            else:
                logger.info("No existing account state found, starting fresh.")
                await self.save_state()
        except Exception as e:
            logger.error(f"Failed to load state from DB: {e}")

    async def save_state(self) -> None:
        """Persist current account state (excluding history)."""
        if self.collection is None: return

        try:
            data = {
                "_id": "account_main",
                "cash": self.cash,
                "positions": self.positions,
                "last_updated": datetime.utcnow().isoformat()
            }
            # History is NOT saved here anymore
            await self.collection.replace_one({"_id": "account_main"}, data, upsert=True)
        except Exception as e:
            logger.error(f"Failed to save state to DB: {e}")

    async def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch trade history from separate collection."""
        if self.history_collection is None: return []
        try:
            cursor = self.history_collection.find().sort("time", -1).limit(limit)
            results = []
            async for doc in cursor:
                if "_id" in doc:
                    doc["_id"] = str(doc["_id"])
                results.append(doc)
            return results
        except Exception as e:
            logger.error(f"Failed to get history: {e}")
            return []

    async def reset_account(self) -> None:
        """Reset changes and drop collections."""
        self.cash = self.initial_balance
        self.positions = {}
        # self.history = [] # Removed

        if self.collection is not None:
            await self.collection.drop()
        if self.decision_collection is not None:
            await self.decision_collection.drop()
        if self.lessons_collection is not None:
            await self.lessons_collection.drop()
        if self.sentiment_collection is not None:
            await self.sentiment_collection.drop()
        if self.history_collection is not None:
            await self.history_collection.drop() # Drop separate history

        await self.save_state()
        logger.info("Account reset complete.")

    @property
    def total_value(self) -> float:
        """Calculate total account value (Cash + Margin + Unrealized PnL)."""
        margin_used = sum(p.get('margin', 0) for p in self.positions.values())
        unrealized_pnl = sum(p.get('unrealized_pnl', 0) for p in self.positions.values())
        return self.cash + margin_used + unrealized_pnl

    @property
    def total_return_pct(self) -> float:
        """Calculate total return percentage."""
        return ((self.total_value - self.initial_balance) / self.initial_balance) * 100.0

    def get_positions_str(self) -> str:
        """Format open positions as a human-readable string."""
        if not self.positions:
            return "no open positions"
        
        pos_strings = []
        for symbol, pos in self.positions.items():
            unrealized = pos.get('unrealized_pnl', 0.0)
            p_str = (f"Symbol: {symbol} Side: {pos['sign']} Entry: {pos['entry_price']} "
                     f"Lev: {pos['leverage']}x Margin: {pos.get('margin',0):.2f} Unr. PNL: {unrealized:.2f}")
            pos_strings.append(p_str)
        return ", ".join(pos_strings)

    async def close_position(self, coin: str, current_price: float, reason: str = "SIGNAL") -> None:
        """
        Close an existing position.
        """
        if coin not in self.positions:
            return
            
        pos = self.positions.pop(coin)
        margin = pos.get('margin', 0.0)
        entry = pos['entry_price']
        qty = pos['quantity']
        
        if pos['sign'] == "LONG":
            pnl = (current_price - entry) * qty
        else:
            pnl = (entry - current_price) * qty
            
        returned_amount = margin + pnl
        
        # Deduct Exit Fee
        exit_value = current_price * qty
        fee = exit_value * settings.TRADING_FEE_RATE
        returned_amount -= fee
        
        self.cash += returned_amount
        
        logger.info(f"Closed {coin} ({reason}). PnL: {pnl:.2f}. Fee: {fee:.2f}. New Balance: {self.cash:.2f}")
        
        # Log to History Collection
        log_entry = {
            "action": "close", 
            "coin": coin, 
            "price": current_price, 
            "pnl": pnl, 
            "reason": reason,
            "time": datetime.utcnow().isoformat(), 
            "result": "CLOSED"
        }
        if self.history_collection is not None:
            await self.history_collection.insert_one(log_entry)
            
        await self.save_state()

    async def update_positions(self, current_prices: Dict[str, float]) -> None:
        """
        Update Unrealized PnL for all positions and check Stop Loss / Take Profit.
        
        Args:
            current_prices: Dictionary mapping symbols to current prices.
        """
        state_changed = False
        # Iterate over a copy since we might modify the dict (close positions)
        for symbol, pos in list(self.positions.items()):
            if symbol in current_prices:
                curr = current_prices[symbol]
                # Update stored current price for external agents
                pos['current_price'] = curr
                
                entry = pos['entry_price']
                qty = pos['quantity']
                
                if pos['sign'] == "LONG":
                    pnl_unrealized = (curr - entry) * qty
                else:
                    pnl_unrealized = (entry - curr) * qty
                
                # Update floating PnL
                if pos.get('unrealized_pnl') != pnl_unrealized:
                    pos['unrealized_pnl'] = pnl_unrealized
                    state_changed = True
                
                # Check Stop Loss
                sl = pos.get('stop_loss')
                if sl:
                    if (pos['sign'] == "LONG" and curr <= sl) or \
                       (pos['sign'] == "SHORT" and curr >= sl):
                        await self.close_position(symbol, curr, reason="STOP_LOSS")
                        continue
                
                # Check Take Profit
                tp = pos.get('take_profit')
                if tp:
                    if (pos['sign'] == "LONG" and curr >= tp) or \
                       (pos['sign'] == "SHORT" and curr <= tp):
                         await self.close_position(symbol, curr, reason="TAKE_PROFIT")
                         continue
        
        if state_changed:
            await self.save_state()

    async def update_position_metadata(self, coin: str, reason: str, invalidation: Optional[str] = None) -> None:
        """
        Update the reasoning/invalidation for an existing open position.
        """
        if coin in self.positions:
            self.positions[coin]["reason"] = reason
            if invalidation:
                self.positions[coin]["invalidation"] = invalidation
            self.positions[coin]["last_decision_timestamp"] = datetime.utcnow().isoformat()
            await self.save_state()
            logger.info(f"Updated metadata for {coin} position.")

    def _calculate_safe_quantity(self, current_price: float, decision: Dict[str, Any]) -> float:
        """
        Calculate the safe trade quantity based on Risk, Margin, and Cash limits.
        """
        leverage = int(decision.get("leverage", 1))
        stop_loss = decision.get("stop_loss")
        account_value = self.total_value

        # 1. Zero Check
        if current_price <= 0: return 0.0

        # 2. Risk Sizing
        risk_per_share = abs(current_price - float(stop_loss)) if stop_loss else 0.0
        
        if risk_per_share == 0:
            qty_risk = float('inf')
        else:
            max_risk_allowed = account_value * settings.MAX_RISK_PER_TRADE
            qty_risk = max_risk_allowed / risk_per_share
            
        # 3. Margin Sizing
        max_margin_allowed = account_value * settings.MAX_MARGIN_PER_POS
        max_position_value = max_margin_allowed * leverage
        qty_margin = max_position_value / current_price
        
        # 4. Cash Constraint
        qty_cash = (self.cash * leverage) / current_price
        
        # 5. AI Recommendation
        qty_ai = float('inf')
        if "position_size_usd" in decision:
            ai_size = decision["position_size_usd"]
            if ai_size and ai_size > 0:
                qty_ai = ai_size / current_price
                
        return min(qty_risk, qty_margin, qty_cash, qty_ai)

    async def get_last_action_time(self, symbol: str) -> Optional[datetime]:
        """
        Retrieve the datetime of the last action.
        Uses efficient Mongo query instead of array scan.
        """
        if self.history_collection is None:
            return None
            
        try:
            # Sort descending by time, matching symbol
            doc = await self.history_collection.find_one(
                {"coin": symbol},
                sort=[("time", -1)]
            )
            if doc and "time" in doc:
                return datetime.fromisoformat(doc["time"])
        except Exception as e:
             logger.error(f"Error checking last action time: {e}")
        return None

    async def execute_trade(self, decision: Dict[str, Any], current_price: float) -> None:
        """
        Execute a trade entry based on a decision.
        
        Args:
            decision: The decision dictionary (signal, stop_loss, leverage, etc.)
            current_price: The current market price for entry.
        """
        signal = decision.get("signal")
        coin = decision.get("coin")

        # Fallback to last_decision if signal is missing (compatibility fix)
        if not signal and "last_decision" in decision:
            signal = decision["last_decision"]
            logger.info(f"Signal missing for {coin}, using last_decision: {signal}")
        
        if signal in ["buy_to_enter", "sell_to_enter"]:
            if coin in self.positions:
                logger.warning(f"Position already exists for {coin}, skipping {signal}")
                return
            
            # 1. Validation
            leverage = int(decision.get("leverage", 1))
            stop_loss = decision.get("stop_loss")
            
            if not stop_loss:
                logger.warning(f"Stop Loss missing for {coin}, cannot calculate risk. Skipping.")
                return

            # 2. Calculate Quantity (Helper Refactor)
            quantity = self._calculate_safe_quantity(current_price, decision)
            
            if quantity <= 0:
                logger.warning(f"Calculated quantity is {quantity}, skipping.")
                return

            # 3. Fee Check & Execution
            position_value_usd = quantity * current_price
            
            # Deduct Entry Fee
            fee = position_value_usd * settings.TRADING_FEE_RATE
            if (self.cash - fee) <= 0:
                 logger.warning("Not enough cash for fees.")
                 return
                 
            # Deduct Margin
            margin_required = position_value_usd / leverage
            if margin_required > (self.cash - fee):
                 # Auto-adjust if fee reduced cash below margin req
                 # Strict Approach: Fail
                 logger.warning(f"Insufficient cash for Margin + Fee. Req: {margin_required+fee}, Avail: {self.cash}")
                 return

            self.cash -= fee
            self.cash -= margin_required
            
            self.positions[coin] = {
                "sign": "LONG" if signal == "buy_to_enter" else "SHORT",
                "entry_price": current_price,
                "quantity": quantity,
                "leverage": leverage,
                "margin": margin_required,
                "stop_loss": stop_loss,
                "take_profit": decision.get("profit_target"),
                "unrealized_pnl": 0.0,
                "reason": decision.get("reason"),
                "invalidation": decision.get("invalidation"),
                "timestamp": datetime.utcnow().isoformat()
            }
            
            logger.info(f"Executed {signal} on {coin}. "
                        f"Price: {current_price}, Qty: {quantity:.4f}, Lev: {leverage}x. "
                        f"Margin: {margin_required:.2f}. "
                        f"Fee: {fee:.2f}. ")
            
            entry_log = {
                "action": signal, 
                "coin": coin, 
                "price": current_price, 
                "size": quantity,
                "reason": decision.get("reason"),
                "invalidation": decision.get("invalidation"),
                "time": datetime.utcnow().isoformat(), 
                "result": "OPEN"
            }
            if self.history_collection is not None:
                await self.history_collection.insert_one(entry_log)
                
            await self.save_state()

        elif signal == "close":
             await self.close_position(coin, current_price, reason="SIGNAL")

        else:
            logger.info(f"Signal: {signal} for {coin} - No action taken")

# Global Account Instance
demo_account = PaperTradingAccount()
