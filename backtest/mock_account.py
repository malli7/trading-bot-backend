"""
Mock Trading Account for Backtesting.

This class mimics the interface of `PaperTradingAccount` but runs entirely in memory
without database connections. It tracks virtual cash, positions, and logs trades
to a local JSON file for analysis.
"""
import logging
import json
import os
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger("backtest_account")

class MockCursor:
    """Simulates Motor Cursor."""
    def __init__(self, data: List[Dict]):
        self.data = data

    def sort(self, key: str, direction: int) -> 'MockCursor':
        # direction -1 = desc, 1 = asc
        reverse = (direction == -1)
        # Simple sort handling strings/numbers
        try:
            self.data.sort(key=lambda x: x.get(key, ""), reverse=reverse)
        except Exception:
            pass # Best effort
        return self

    def limit(self, n: int) -> 'MockCursor':
        self.data = self.data[:n]
        return self

    async def to_list(self, length: int) -> List[Dict]:
        return self.data[:length]

class MockCollection:
    """Simulates Motor Collection."""
    def __init__(self, name: str):
        self.name = name
        self.data: List[Dict] = []

    def find(self, query: Dict) -> MockCursor:
        # Very basic query simulation
        results = []
        for doc in self.data:
            match = True
            for k, v in query.items():
                # Handle $in operator
                if isinstance(v, dict) and "$in" in v:
                    if doc.get(k) not in v["$in"]:
                        match = False
                        break
                elif doc.get(k) != v:
                    match = False
                    break
            if match:
                results.append(doc)
        return MockCursor(results)

    async def find_one(self, query: Dict) -> Optional[Dict]:
        cursor = self.find(query)
        if cursor.data:
            return cursor.data[0]
        return None

    async def insert_one(self, doc: Dict) -> None:
        self.data.append(doc)

class MockAccount:
    """
    In-memory trading account simulator.
    """
    def __init__(self, initial_balance: float = 1000.0):
        self.initial_balance = initial_balance
        self.cash = initial_balance
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.history: List[Dict[str, Any]] = []
        self.decision_logs: List[Dict[str, Any]] = []
        self.lessons: List[str] = []
        
        # Persistence path
        self.results_dir = os.path.join(os.path.dirname(__file__), "results")
        os.makedirs(self.results_dir, exist_ok=True)
        self.trades_file = os.path.join(self.results_dir, "trades.json")
        
        # Mock Collections
        self.decision_collection = MockCollection("decision_logs")
        self.lessons_collection = MockCollection("lessons_learned")
        self.sentiment_collection = MockCollection("sentiment_logs")
        self.collection = MockCollection("account_state")

    async def initialize(self) -> None:
        """Mock initialization."""
        logger.info(f"MockAccount initialized with ${self.cash:.2f}")

    async def log_decision(self, decision: Dict[str, Any]) -> None:
        """Log decision to memory instead of DB."""
        doc = decision.copy()
        if "timestamp" not in doc:
             doc["timestamp"] = datetime.utcnow().isoformat()
        self.decision_logs.append(doc)
        # Sync to collection
        await self.decision_collection.insert_one(doc)

    async def log_sentiment_analysis(self, data: Dict[str, Any]) -> None:
        """Mock log sentiment."""
        await self.sentiment_collection.insert_one(data)

    async def save_lesson(self, lesson: str, source_decision_id: Optional[str] = None) -> None:
        """Save lesson to memory."""
        self.lessons.append(lesson)
        doc = {
            "timestamp": datetime.utcnow().isoformat(),
            "lesson": lesson,
            "source_decision_id": source_decision_id
        }
        await self.lessons_collection.insert_one(doc)
        logger.info(f"[Mock] Learned: {lesson}")

    async def get_recent_lessons(self, limit: int = 5) -> List[str]:
        """Return recent lessons from memory."""
        return self.lessons[-limit:]

    async def update_positions(self, current_prices: Dict[str, float]) -> None:
        """
        Update PnL and check stops/targets based on provided simulated prices.
        """
        for symbol, pos in list(self.positions.items()):
            if symbol in current_prices:
                curr = current_prices[symbol]
                entry = pos['entry_price']
                qty = pos['quantity']
                
                if pos['sign'] == "LONG":
                    unrealized = (curr - entry) * qty
                else:
                    unrealized = (entry - curr) * qty
                
                pos['unrealized_pnl'] = unrealized
                
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

    async def close_position(self, coin: str, current_price: float, reason: str = "SIGNAL") -> None:
        """Close position and realize PnL."""
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
        
        trade_record = {
            "action": "close", 
            "coin": coin, 
            "price": current_price, 
            "pnl": pnl, 
            "reason": reason,
            "entry_price": entry,
            "sign": pos['sign'],
            "result": "CLOSED",
            "balance_after": self.cash
        }
        
        logger.info(f"Closed {coin} ({reason}). PnL: {pnl:.2f}. Balance: {self.cash:.2f}")
        self.history.append(trade_record)
        self._save_history()

    async def execute_trade(self, decision: Dict[str, Any], current_price: float) -> None:
        """Execute trade on mock account."""
        signal = decision.get("signal")
        coin = decision.get("coin")
        
        if signal in ["buy_to_enter", "sell_to_enter"]:
            if coin in self.positions:
                return

            leverage = int(decision.get("leverage", 1))
            stop_loss = decision.get("stop_loss")
            
            if not stop_loss: return

            entry_price = current_price
            
            # Risk Sizing (Same logic as live)
            risk_per_share = abs(entry_price - float(stop_loss))
            if risk_per_share == 0: return

            account_value = self.total_value
            max_risk_allowed = account_value * 0.02
            qty_risk = max_risk_allowed / risk_per_share
            
            max_margin_allowed = account_value * 0.20
            max_position_value = max_margin_allowed * leverage
            qty_margin = max_position_value / entry_price
            
            qty_cash = (self.cash * leverage) / entry_price
            
            quantity = min(qty_risk, qty_margin, qty_cash)
            
            if quantity <= 0: return

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
                "invalidation": decision.get("invalidation")
            }
            
            record = {
                "action": signal, 
                "coin": coin, 
                "price": current_price, 
                "size": quantity,
                "reason": decision.get("reason"),
                "result": "OPEN",
                "balance_after": self.cash
            }
            logger.info(f"Opened {signal} on {coin} @ {current_price:.2f}")
            self.history.append(record)
            self._save_history()
            
        elif signal == "close":
             await self.close_position(coin, current_price, reason="SIGNAL")

    @property
    def total_value(self) -> float:
        margin_used = sum(p.get('margin', 0) for p in self.positions.values())
        unrealized_pnl = sum(p.get('unrealized_pnl', 0) for p in self.positions.values())
        return self.cash + margin_used + unrealized_pnl

    def _save_history(self):
        """Dump trades to JSON."""
        with open(self.trades_file, "w") as f:
            json.dump(self.history, f, indent=2, default=str)

# Singleton for the patch target
demo_account = MockAccount()
