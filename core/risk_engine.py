
"""
Institutional Risk Engine
=========================

Why This Module Exists (The "Why")
----------------------------------
In professional trading, "Risk" is not just "Stop Loss". It is a statistical property of the portfolio.
This module implements two critical institutional concepts often missing in retail bots:

1. **Volatility Targeting (The "Annual Total Volume" question)**
   - *Problem*: A $1000 trade in a stable stablecoin is SAFE. A $1000 trade in a volatile meme coin is DANGEROUS.
   - *Solution*: We don't size by "$ Amount". We size by "Volatility Contribution".
   - *Mechanism*: If an asset is 2x as volatile (ATR), we trade 0.5x the size.
   - *Goal*: Ensure the portfolio's Daily PnL Volatility remains constant (Targeting ~40% Annualized Vol).

2. **Correlation Penalties (The "Cluster Risk" problem)**
   - *Problem*: Buying BTC, ETH, and SOL simultaneously is often just ONE big bet, not three.
   - *Solution*: If you add a new trade that is highly correlated to existing positions, we drastically reduce its allowed size.
   - *Goal*: Prevent "Illusion of Diversification" where a market crash wipes out the entire account because everything moves together.

Usage
-----
Used by the `RiskAssessmentAgent` to calculate a "Quant Cap" (Maximum Safe Size).
The Agent may suggest a size, but this module provides the mathematical ceiling that cannot be breached safely.
"""
from typing import Dict, List, Optional
import math

from core.config import settings

class RiskEngine:
    def __init__(self):
        # Configuration driven by core.config.settings
        self.TARGET_VOL = settings.RISK_TARGET_VOL
        self.CORRELATION_MATRIX = settings.RISK_CORRELATION_MATRIX
        self.MAX_CORRELATED_EXPOSURE_RATIO = settings.RISK_MAX_CORRELATED_EXPOSURE

    def calculate_vol_target_size(
        self, 
        account_equity: float, 
        current_price: float, 
        atr_value: float, 
        atr_period: str = "1d"
    ) -> float:
        """
        Calculate position size to adjust trade risk to a fixed portfolio volatility target.
        
        Args:
            account_equity: Total account value.
            current_price: Asset price.
            atr_value: Average True Range (volatility).
            atr_period: Timeframe of ATR ('1d', '4h', '1h').
            
        Returns:
            float: Recommended position size in USD.
        """
        if atr_value <= 0:
            return 0.0
            
        # 1. Estimate Daily Volatility from ATR (assuming 14-period ATR on timeframe)
        daily_vol_est = 0.0
        
        # Sqrt(Time) rule scaling
        scale_factor = 1.0
        if "1h" in atr_period:
            scale_factor = math.sqrt(24)
        elif "4h" in atr_period:
            scale_factor = math.sqrt(6)
        elif "15m" in atr_period:
            scale_factor = math.sqrt(96)
            
        daily_vol_price = atr_value * scale_factor
        instrument_daily_vol_pct = daily_vol_price / current_price if current_price > 0 else 0
        
        if instrument_daily_vol_pct == 0:
            return 0.0
        
        # 2. Target Daily Volatility for Account
        # Target Annual = settings.RISK_TARGET_VOL. Target Daily = Annual / 16 (sqrt(256))
        target_daily_vol_pct = self.TARGET_VOL / 16.0
        
        # 3. Calculate Allocation
        # Exposure = Equity * (Target_Vol / Instrument_Vol)
        allocation_pct = target_daily_vol_pct / instrument_daily_vol_pct
        
        # Cap allocation to sensible limits (e.g., max 3x leverage implied)
        allocation_pct = min(allocation_pct, 3.0) 
        
        position_size_usd = account_equity * allocation_pct
        return position_size_usd

    def apply_correlation_penalty(
        self,
        account_equity: float,
        new_symbol: str,
        proposed_size_usd: float,
        current_positions: Dict[str, Dict]
    ) -> float:
        """
        Reduces position size if portfolio is already heavy on correlated assets.
        Enforces Portfolio Heat Limits.
        """
        total_risk_load = 0.0
        
        # Calculate existing load
        for symbol, pos in current_positions.items():
            # Get correlation from Matrix in settings
            corr = self.CORRELATION_MATRIX.get(new_symbol, {}).get(symbol, 0.5)
            
            # Use entry_price as proxy for current value if current not avail
            val = pos['quantity'] * pos['entry_price'] 
            total_risk_load += val * corr
            
        # Proposed load
        projected_load = total_risk_load + proposed_size_usd
        
        limit = account_equity * self.MAX_CORRELATED_EXPOSURE_RATIO
        
        if projected_load > limit:
            # We need to reduce proposed_size
            reduced_size = max(0, limit - total_risk_load)
            return reduced_size
            
        return proposed_size_usd

risk_engine = RiskEngine()
