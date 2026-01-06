"""
Trading Account Management Module.

This module handles the state of the paper trading account, including
balance, positions, and history tracking. It also manages persistence
using MongoDB for storing decision logs, lessons, and account state.
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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

INITIAL_BALANCE = 1000.0

class PaperTradingAccount:
    """
    Manages a virtual trading account state backed by MongoDB.
    
    Attributes:
        cash (float): Available cash balance.
        positions (Dict): Open positions keyed by symbol.
        history (List): Trade history log.
        db (AsyncIOMotorDatabase): MongoDB Database reference.
    """
    
    def __init__(self, initial_balance: float = INITIAL_BALANCE):
        self.initial_balance = initial_balance
        self.cash = initial_balance
        self.positions: Dict[str, Dict[str, Any]] = {} 
        self.history: List[Dict[str, Any]] = []
        
        # Database connections (Initialized lazily)
        self.db_client: Optional[AsyncIOMotorClient] = None
        self.db: Optional[AsyncIOMotorDatabase] = None
        self.collection = None
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
            self.lessons_collection = self.db.get_collection("lessons_learned")
            self.decision_collection = self.db.get_collection("decision_logs")
            self.sentiment_collection = self.db.get_collection("sentiment_logs")
            
            logger.info("Connected to MongoDB")
            await self.load_state()
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")

    async def log_decision(self, decision: Dict[str, Any]) -> None:
        """
        Log every decision (Trade/Skip/Hold) for Reflection.
        
        Args:
            decision: Dictionary containing trade signal and reasoning.
        """
        if self.decision_collection is None:
            return
            
        try:
            doc = decision.copy()
            doc["timestamp"] = datetime.utcnow().isoformat()
            await self.decision_collection.insert_one(doc)
        except Exception as e:
            logger.error(f"Failed to log decision: {e}")

    async def log_sentiment_analysis(self, data: Dict[str, Any]) -> None:
        """Persist sentiment analysis results."""
        if self.sentiment_collection is None:
            return
            
        try:
            await self.sentiment_collection.insert_one(data)
            logger.info("Sentiment Analysis saved to MongoDB")
        except Exception as e:
            logger.error(f"Failed to save sentiment analysis: {e}")

    async def save_lesson(self, lesson: str, source_decision_id: Optional[str] = None) -> None:
        """
        Save a learned lesson to the database.
        
        Args:
            lesson: The text content of the lesson.
            source_decision_id: Optional ID of the decision that triggered this lesson (for deduplication).
        """
        if self.lessons_collection is None:
            return
        
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
        if self.lessons_collection is None:
            return []
        
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
        """Load account balance and positions from MongoDB."""
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

    async def save_state(self) -> None:
        """Persist current account state to MongoDB."""
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
        
        Args:
            coin: The asset symbol.
            current_price: The exit price.
            reason: Reason for closing (SIGNAL, STOP_LOSS, TAKE_PROFIT).
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
                entry = pos['entry_price']
                qty = pos['quantity']
                
                if pos['sign'] == "LONG":
                    unrealized = (curr - entry) * qty
                else:
                    unrealized = (entry - curr) * qty
                
                # Update floating PnL
                if pos.get('unrealized_pnl') != unrealized:
                    pos['unrealized_pnl'] = unrealized
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
            
            # Position Sizing Logic
            leverage = int(decision.get("leverage", 1))
            stop_loss = decision.get("stop_loss")
            
            # 1. Validation
            if not stop_loss:
                logger.warning(f"Stop Loss missing for {coin}, cannot calculate risk. Skipping.")
                return

            entry_price = current_price
            
            # 2. Risk-Based Sizing: Risk per share = |Entry - StopLoss|
            risk_per_share = abs(entry_price - float(stop_loss))
            if risk_per_share == 0:
                logger.warning("Stop loss equals entry price, invalid.")
                return

            # Max Risk Allowed = 2% of Total Account Value
            account_value = self.total_value
            max_risk_allowed = account_value * 0.02
            
            qty_risk = max_risk_allowed / risk_per_share
            
            # 3. Margin-Based Sizing: Max Margin Allowed = 20% of Total Account Value
            max_margin_allowed = account_value * 0.20
            
            # Position Value = Margin * Leverage
            max_position_value = max_margin_allowed * leverage
            
            qty_margin = max_position_value / entry_price
            
            # 4. Cash Constraint (Hard Limit)
            qty_cash = (self.cash * leverage) / entry_price

            # 5. AI Recommended Sizing (Optional Override)
            qty_ai = float('inf')
            if "position_size_usd" in decision:
                ai_size_usd = decision["position_size_usd"]
                if ai_size_usd > 0:
                     qty_ai = ai_size_usd / entry_price
                     logger.info(f"Risk Agent requested size: ${ai_size_usd:.2f} ({qty_ai:.4f} units)")

            # 6. Final Quantity (Min of Risk Cap, Margin Cap, Cash, and AI Target)
            quantity = min(qty_risk, qty_margin, qty_cash, qty_ai)
            
            if quantity <= 0:
                logger.warning(f"Calculated quantity is {quantity}, skipping.")
                return

            # Recalculate margin required for the final quantity
            position_value_usd = quantity * current_price
            margin_required = position_value_usd / leverage
            
            if margin_required > self.cash:
                 quantity = (self.cash * leverage) / current_price
                 margin_required = self.cash

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
                        f"Margin: {margin_required:.2f} (Limit: {max_margin_allowed:.2f}). "
                        f"Risk: {risk_per_share*quantity:.2f} (Limit: {max_risk_allowed:.2f})")
                        
            self.history.append({
                "action": signal, 
                "coin": coin, 
                "price": current_price, 
                "size": quantity,
                "reason": decision.get("reason"),
                "invalidation": decision.get("invalidation"),
                "time": datetime.utcnow().isoformat(), 
                "result": "OPEN"
            })
            await self.save_state()

        elif signal == "close":
             await self.close_position(coin, current_price, reason="SIGNAL")

        else:
            logger.info(f"Signal: {signal} for {coin} - No action taken")

# Global Account Instance
demo_account = PaperTradingAccount()
