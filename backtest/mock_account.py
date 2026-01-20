"""
Mock Account Service (The Simulator State)
==========================================

Why This Module Exists
----------------------
To enable risk-free simulation by mimicking the production `PaperTradingAccount` interface.
It allows the agent to interact with a "ghost" ledger that tracks PnL, positions, and history 
in-memory, without touching the real MongoDB or modifying live state.

Key Features:
1.  **In-Memory State**: Fast execution, reset on every run.
2.  **Interface Parity**: precise method signatures match production services.
3.  **Local Logging**: Dumps trade history to JSON for the "Brutal Review".
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

TRADING_FEE_RATE = 0.001 # 0.1% Taker Fee

class MockAccount:
    """
    In-memory trading account simulator.
    """
    def __init__(self, initial_balance: float = 1000.0):
        self.initial_balance = initial_balance
        self.cash = initial_balance
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.pending_orders: List[Dict[str, Any]] = [] # For Limit Orders
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
    
    # ... (initialize, log_decision, etc. unchanged) ...

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

    async def load_state(self) -> None:
        """Mock no-op for state loading."""
        pass

    async def save_state(self) -> None:
        """Mock no-op for state saving."""
        pass

    async def update_position_metadata(self, coin: str, reason: str, invalidation: Optional[str] = None) -> None:
        """Mock metadata update."""
        if coin in self.positions:
            self.positions[coin]["reason"] = reason
            if invalidation:
                self.positions[coin]["invalidation"] = invalidation
            self.positions[coin]["last_decision_timestamp"] = datetime.utcnow().isoformat()
            logger.info(f"[Mock] Updated metadata for {coin}")

    async def update_positions(self, current_prices: Dict[str, float]) -> None:
        """
        Update PnL and check stops/targets based on provided simulated prices.
        Also check Pending Limit Orders for fills.
        """
        # 1. Check Pending Orders
        for order in list(self.pending_orders):
            symbol = order['coin']
            if symbol in current_prices:
                # In a real backtest we'd check High/Low, but here we only have 'current_prices' (Close).
                # To simulate realistic fills, we will assume fill if price crossed limit.
                # Ideally, engine passes the full candle.
                
                curr = current_prices[symbol]
                limit_price = order['limit_price']
                
                # Check Expiry
                if (datetime.utcnow() - order['created_at']).total_seconds() > order['ttl_seconds']:
                    self.pending_orders.remove(order)
                    logger.info(f"Order Expired: {symbol} Buy Limit @ {limit_price}")
                    continue

                if order['sign'] == "LONG" and curr <= limit_price:
                     # Simulate Fill!
                     logger.info(f"Limit Order FILLED: {symbol} Buy @ {limit_price} (Market: {curr})")
                     self.pending_orders.remove(order)
                     await self._execute_filled_order(order, fill_price=limit_price) # Fill at limit

        # 2. Update Open Positions
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
        
        # Deduct Exit Fee
        exit_value = current_price * qty
        fee = exit_value * TRADING_FEE_RATE
        returned_amount -= fee
        
        self.cash += returned_amount
        
        trade_record = {
            "action": "close", 
            "coin": coin, 
            "price": current_price, 
            "pnl": pnl, 
            "fee": fee,
            "reason": reason,
            "entry_price": entry,
            "sign": pos['sign'],
            "result": "CLOSED",
            "time": datetime.utcnow().isoformat(),
            "balance_after": self.cash
        }
        
        logger.info(f"Closed {coin} ({reason}). PnL: {pnl:.2f}. Fee: {fee:.2f}. Balance: {self.cash:.2f}")
        self.history.append(trade_record)
        self._save_history()

    async def execute_trade(self, decision: Dict[str, Any], current_price: float) -> None:
        """
        Execute trade on mock account. 
        Supports LIMIT orders now.
        """
        signal = decision.get("signal")
        coin = decision.get("coin")
        
        if signal in ["buy_to_enter", "sell_to_enter"]:
            if coin in self.positions:
                return
                
            # Check for existing pending orders to avoid dups
            if any(o['coin'] == coin for o in self.pending_orders):
                 return

            order_type = decision.get("order_type", "MARKET")
            limit_price = decision.get("limit_price")
            
            if order_type == "LIMIT" and limit_price:
                 # Clean limit price
                 try:
                     limit_price = float(limit_price)
                 except:     
                     logger.error(f"Invalid Limit Price: {limit_price}")
                     return
                     
                 # Enqueue Pending Order
                 order = {
                     "coin": coin,
                     "sign": "LONG" if signal == "buy_to_enter" else "SHORT",
                     "limit_price": limit_price,
                     "decision_snapshot": decision,
                     "created_at": datetime.utcnow(),
                     "ttl_seconds": 3600 * 4 # 4 Hour Expiry default
                 }
                 self.pending_orders.append(order)
                 logger.info(f"Placed LIMIT {order['sign']} on {coin} @ {limit_price}")
                 return

            # MARKET EXECUTION
            await self._execute_filled_order({
                "coin": coin,
                "sign": "LONG" if signal == "buy_to_enter" else "SHORT",
                "decision_snapshot": decision
            }, fill_price=current_price)
            
        elif signal == "close":
             await self.close_position(coin, current_price, reason="SIGNAL")

    async def _execute_filled_order(self, order_context: Dict, fill_price: float) -> None:
        """Internal helper to book the trade state once filled."""
        coin = order_context['coin']
        decision = order_context['decision_snapshot']
        
        leverage = int(decision.get("leverage", 1))
        stop_loss = decision.get("stop_loss")
             
        if not stop_loss: return

        entry_price = fill_price
             
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

        position_value_usd = quantity * entry_price
        
        # Deduct Entry Fee
        fee = position_value_usd * TRADING_FEE_RATE
        if (self.cash - fee) <= 0:
             logger.warning("Not enough cash for fees.")
             return
        self.cash -= fee
        
        margin_required = position_value_usd / leverage
             
        if margin_required > self.cash:
             quantity = (self.cash * leverage) / entry_price
             margin_required = self.cash

        self.cash -= margin_required
             
        self.positions[coin] = {
            "sign": order_context['sign'],
            "entry_price": entry_price,
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
            "action": f"{order_context['sign']}_ENTER", 
            "coin": coin, 
            "price": entry_price, 
            "size": quantity,
            "fee": fee,
            "reason": decision.get("reason"),
            "result": "OPEN",
            "time": datetime.utcnow().isoformat(),
            "balance_after": self.cash
        }
        logger.info(f"Opened {order_context['sign']} on {coin} @ {entry_price:.2f}. Fee: {fee:.2f}")
        self.history.append(record)
        self._save_history()
            


    async def get_last_action_time(self, symbol: str) -> Optional[datetime]:
        """
        Retrieve the datetime of the last action (Entry or Exit) for a specific symbol.
        """
        # Iterate backwards
        for trade in reversed(self.history):
            if trade.get("coin") == symbol:
                try:
                    return datetime.fromisoformat(trade["time"])
                except (ValueError, KeyError):
                    continue
        return None

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
