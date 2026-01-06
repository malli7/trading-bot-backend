
"""
Institutional Risk Engine.

This module provides the mathematical backend for:
1. Volatility Targeting (sizing based on ATR).
2. Correlation Management (haircuts for correlated assets).
3. Portfolio Heat Limits.
"""
from typing import Dict, List, Optional
import math

class RiskEngine:
    def __init__(self):
        # Target Annualized Volatility for the Portfolio (e.g., 40% is aggressive but standard for Crypto Swing)
        self.TARGET_VOL = 0.40 
        
        # Hardcoded Correlation Matrix (approximate for Crypto Beta)
        # In a real HFT system, this would update live via covariance matrix calculation.
        self.CORRELATION_MATRIX = {
            "BTC": {"BTC": 1.0, "ETH": 0.85, "SOL": 0.75},
            "ETH": {"BTC": 0.85, "ETH": 1.0, "SOL": 0.80},
            "SOL": {"BTC": 0.75, "ETH": 0.80, "SOL": 1.0}
        }
        
        self.MAX_CORRELATED_EXPOSURE_RATIO = 1.5 # Max 1.5x equity in highly correlated assets

    def calculate_vol_target_size(
        self, 
        account_equity: float, 
        current_price: float, 
        atr_value: float, 
        atr_period: str = "1d" # '1d', '4h', '1h' - assumes ATR is normalized to price units
    ) -> float:
        """
        Calculate position size to adjust trade risk to a fixed portfolio volatility target.
        
        Formula:
        Size = (Equity * Target_Vol) / (Annualized Instrument Vol)
        
        But simpler for swing trading using ATR:
        Risk Unit = N * ATR
        We want Risk Unit to be X% of Equity.
        """
        if atr_value <= 0:
            return 0.0
            
        # 1. Estimate Daily Volatility from ATR (assuming 14-period ATR on timeframe)
        # If ATR is from 1h candles, we scale it to Daily.
        # Volatility = ATR / Price
        daily_vol_est = 0.0
        
        # Simple heuristic scaling factors to convert timeframe ATR to Daily Vol
        # Sqrt(Time) rule: 1 Day = 24 hours. 
        # If ATR is 1h, Daily Vol ~ 1h_ATR * sqrt(24)
        scale_factor = 1.0
        if "1h" in atr_period:
            scale_factor = math.sqrt(24)
        elif "4h" in atr_period:
            scale_factor = math.sqrt(6)
        elif "15m" in atr_period:
            scale_factor = math.sqrt(96)
            
        daily_vol_price = atr_value * scale_factor
        instrument_daily_vol_pct = daily_vol_price / current_price
        
        # 2. Target Daily Volatility for Account
        # Target Annual = 40%. Target Daily = 40% / 16 (sqrt(256)) ~= 2.5%
        target_daily_vol_pct = self.TARGET_VOL / 16.0
        
        # 3. Calculate Allocation
        # How much exposure do we need to match instrument vol to target vol?
        # Exposure * Instrument_Vol = Equity * Target_Vol
        # Exposure = Equity * (Target_Vol / Instrument_Vol)
        
        allocation_pct = target_daily_vol_pct / instrument_daily_vol_pct
        
        # Cap allocation to sensible limits (e.g., max 3x leverage)
        allocation_pct = min(allocation_pct, 3.0) 
        
        position_size_usd = account_equity * allocation_pct
        return position_size_usd

    def check_correlation_risk(
        self, 
        new_symbol: str, 
        new_size_usd: float, 
        current_positions: Dict[str, Dict]
    ) -> float:
        """
        Calculate the correlation adjustment factor.
        If adding this trade increases Portfolio Beta beyond limits, reduce size.
        
        Returns:
            float: Sizing factor (0.0 to 1.0). 1.0 means no reduction.
        """
        total_correlated_exposure = 0.0
        
        # 1. Sum up weighted exposure
        for symbol, pos in current_positions.items():
            # Get correlation between New Asset and Existing Asset
            corr = self.CORRELATION_MATRIX.get(new_symbol, {}).get(symbol, 0.5) # Default 0.5 if unknown
            
            # Position value
            pos_value = pos['quantity'] * pos['current_price'] # Need current price in pos, or approx with entry
            
            # Weighted exposure
            total_correlated_exposure += pos_value * corr
            
        # Add the new proposed exposure (correlation 1.0 with itself)
        total_correlated_exposure += new_size_usd * 1.0
        
        # 2. Check against Equity (Need Equity passed in, or assume Ratio check)
        # We will return the raw exposure for now? No, we need a penalty.
        # Let's assume this check is done OUTSIDE or we pass Equity.
        
        return 1.0 # Placeholder for simple logic: Logic implemented in Agent
        
    def apply_correlation_penalty(
        self,
        account_equity: float,
        new_symbol: str,
        proposed_size_usd: float,
        current_positions: Dict[str, Dict]
    ) -> float:
        """
        Returns the finalized size after correlation penalty.
        """
        total_risk_load = 0.0
        
        # Calculate existing load
        for symbol, pos in current_positions.items():
            corr = self.CORRELATION_MATRIX.get(new_symbol, {}).get(symbol, 0.8)
            # Use entry_price as proxy for current value if current not avail, roughly ok for sizing
            val = pos['quantity'] * pos['entry_price'] 
            total_risk_load += val * corr
            
        # Proposed load
        projected_load = total_risk_load + proposed_size_usd
        
        limit = account_equity * self.MAX_CORRELATED_EXPOSURE_RATIO
        
        if projected_load > limit:
            # We need to reduce proposed_size
            # total_risk_load + reduced_size = limit
            reduced_size = max(0, limit - total_risk_load)
            return reduced_size
            
        return proposed_size_usd

risk_engine = RiskEngine()
