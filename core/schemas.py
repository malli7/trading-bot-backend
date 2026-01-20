"""
Core Data Schemas (DTOs)
========================

Why This Module Exists
----------------------
In a multi-agent system, Agents (LLMs) and Code (Execution) must speak the exact same language.
If an Agent outputs "buy" but the system expects "BUY", the trade fails.

This module acts as the **Type System** / **Contract** that enforces:
1. **Strict Inputs**: Agents only receive data that fits the `AccountState` schema.
2. **Strict Outputs**: Agents must produce decisions that fit the `TradeDecision` schema.

Validation
----------
Any data failing these schemas (e.g., missing "confidence" score) will trigger a validation error
BEFORE it reaches the exchange, acting as a critical safety layer against LLM hallucinations.
"""
from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field, field_validator

# =======================
# Common Enums/Literals
# =======================
# (Using simple strings for now to avoid complexity with Enum serializing in early refactor)
SignalType = str # "BUY", "SELL", "HOLD", "WAIT"

# =======================
# Trading Models
# =======================
class TradeDecision(BaseModel):
    """Represents a final decision for a single asset."""
    coin: str = Field(..., description="Asset symbol (e.g. BTC)")
    signal: SignalType = Field(..., description="Action to take")
    confidence: float = Field(..., ge=0, le=100, description="Confidence score (0-100)")
    reason: str = Field(..., description="Explanation of the decision")
    
    # Optional execution details (present if signal is BUY/SELL)
    leverage: Optional[int] = Field(None, ge=1, le=125)
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    position_size_usd: Optional[float] = None
    
    # Metadata
    invalidation_price: Optional[Union[float, str]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class CycleResult(BaseModel):
    """Output of a full agent cycle run."""
    status: str = "success"
    timestamp: str
    decisions: List[TradeDecision]
    account_summary: Dict[str, Any]

# =======================
# Account Models
# =======================
class Position(BaseModel):
    symbol: str
    size: float
    entry_price: float
    current_price: float
    pnl_unrealized: float
    leverage: int = 1

class AccountState(BaseModel):
    cash: float
    equity: float
    positions: List[Position]
    
# =======================
# API Models
# =======================
class IndicatorResponse(BaseModel):
    market_id: int
    timeframe: str
    indicators: Dict[str, Any]

class AnalysisResponse(BaseModel):
    symbol: str
    market_id: int
    indicator_data: Dict[str, Any]

# =======================
# Consolidation Models
# =======================
class ConsolidationMetrics(BaseModel):
    """Metrics for market consolidation state."""
    symbol: str
    is_consolidating: bool
    market_state: str # "Trending", "Consolidation", "Strong Trend"
    adx: float
    bandwidth: float

class ConsolidationResponse(BaseModel):
    """Response wrapper for consolidation endpoint."""
    results: List[ConsolidationMetrics]
