"""
Portfolio Manager Module (The Risk Gatekeeper)
==============================================

Why This Module Exists
----------------------
This is the **Allocation Layer**.
It takes the raw signal from the Swarm (Mind) and decides *if* and *how much* to trade based on conviction.

Responsibilities:
1.  **Sizing Rules**: Determining position size based on confidence score.
2.  **Filtering**: Rejecting low-conviction signals (filtering noise).
3.  **Leverage Assignment**: Assigning leverage tiers based on asset class (defined in config).
"""
import logging
from typing import Dict, Any, Optional
from services.account import demo_account
from core.config import settings

logger = logging.getLogger(__name__)

class PortfolioManager:
    """
    Allocates capital based on Confidence Scores and Risk Limits.
    
    Attributes:
        max_position_size (float): Maximum allowed portfolio % per trade.
        min_confidence_buy (float): Minimum confidence required to enter a trade.
    """
    def __init__(self):
        self.max_position_size = settings.PORTFOLIO_MAX_POS_SIZE
        self.min_confidence_buy = settings.PORTFOLIO_MIN_CONFIDENCE 
        
    def allocate(
        self, 
        signal: str, 
        confidence: float, 
        coin: str, 
        price: float, 
        current_position: Optional[Dict[str, Any]] = None, 
        swarm_reason: Optional[str] = None, 
        swarm_invalidation: Optional[str] = None,
        suggested_leverage: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Determine if we should execute a trade and calculate sizing parameters.
        
        Args:
            signal: BUY | SELL | HOLD
            confidence: 0-100 float
            coin: Asset Symbol (e.g. ETH)
            price: Current market price
            current_position: Existing position dict or None
            swarm_reason: Explanation from Swarm
            swarm_invalidation: Invalidation condition from Swarm
            
        Returns:
            Dict containing the final executable decision.
        """
        # Default Clean Decision (SKIP_TRADE)
        decision = {
            "signal": "SKIP_TRADE",
            "coin": coin,
            "reason": "Initial",
            "invalidation": "None"
        }
        
        # 1. Existing Position Handling
        if current_position:
            if signal == "BUY":
                # If Long -> Hold
                if current_position['sign'] == "LONG":
                     decision["signal"] = "HOLD"
                     decision["reason"] = f"Position exists & Signal BUY ({swarm_reason})"
                     decision["invalidation"] = swarm_invalidation
                else: 
                     # If Short and Signal BUY -> Close Short
                     decision["signal"] = "close"
                     decision["reason"] = f"Signal Flip: Short -> Buy ({swarm_reason})"
                     
            elif signal == "SELL":
                 # If Long -> Close
                 if current_position['sign'] == "LONG":
                     decision["signal"] = "close"
                     decision["reason"] = f"Signal Flip: Long -> Sell ({swarm_reason})"
                 else:
                     # If Short -> Hold Short
                     decision["signal"] = "HOLD"
                     decision["reason"] = f"Position exists (Short) & Signal SELL ({swarm_reason})"
                     decision["invalidation"] = swarm_invalidation

            elif signal == "HOLD":
                 decision["signal"] = "HOLD"
                 decision["reason"] = swarm_reason if swarm_reason else "Swarm voted HOLD"
                 decision["invalidation"] = swarm_invalidation
            
            return decision

        # 2. New Entry Logic (Only if no position)
        if signal in ["HOLD", "WAIT"]:
            decision["signal"] = "SKIP_TRADE"
            decision["reason"] = swarm_reason if swarm_reason else f"Swarm voted {signal}"
            # Pass through the Swarm's invalidation (Regime Shift logic)
            decision["invalidation"] = swarm_invalidation if swarm_invalidation else "Regime Lock"
            return decision
            
        if signal == "BUY" and confidence < self.min_confidence_buy:
             decision["reason"] = f"Confidence {confidence}% < Threshold {self.min_confidence_buy}% ({swarm_reason})"
             return decision
             
        # Add SELL Confidence Check (Chop Filter)
        if signal == "SELL" and confidence < 70.0:
            decision["signal"] = "SKIP_TRADE"
            decision["reason"] = f"Low conviction sell ({confidence}% < 70%) - Likely Chop"
            decision["invalidation"] = swarm_invalidation
            return decision

        # 3. Direction Mapping
        # Assuming Long-Only bias for "BUY" unless specific short logic added later.
        # Architecture supports Shorts if signal is SELL, but strictly speaking we often treat SELL as exit.
        # Here we map SELL to sell_to_enter (Short) if we want to trade both ways.
        
        mapped_signal = "buy_to_enter" if signal == "BUY" else "sell_to_enter"
        
        # 4. Position Sizing
        # High Confidence (80%+) -> Max Size (25%)
        # Med Confidence (60-80%) -> Normal Size (15%)
        # Low Confidence (<60%) -> Small/No Size (10%)
        
        allocation_pct = 0.10 # Default
        if confidence >= 80:
            allocation_pct = 0.25 # High conviction
        elif confidence >= 70:
             allocation_pct = 0.15 # Medium conviction
             
        # Leverage Logic (Agentic)
        if suggested_leverage:
            leverage = suggested_leverage
        else:
            leverage = 1 # Safe default if agent is silent
        
        # 5. Stop Loss / Profit Target (Heuristic)
        # In a real system, these should come from Technical Analysis (ATR, Swing Lows)
        # Here we use fixed % based on direction.
        
        if mapped_signal == "buy_to_enter":
            stop_loss = price * 0.95
            profit_target = price * 1.10
        else:
            stop_loss = price * 1.05
            profit_target = price * 0.90
        
        # Use Swarm Reason if valid, otherwise generic
        final_reason = swarm_reason if swarm_reason and "No reason" not in swarm_reason else f"Swarm {signal} w/ {confidence}% conf"
        
        # Only populate trade params if we are ACTUALLY entering
        decision.update({
             "signal": mapped_signal,
             "leverage": leverage,
             "stop_loss": stop_loss,
             "profit_target": profit_target,
             "reason": final_reason,
             "invalidation": swarm_invalidation
        })
        
        return decision
