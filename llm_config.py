"""
Centralized Configuration for LLM Models.

This module defines the specific model IDs used across the system.
Change model assignments here to update them globally.
"""

# ==========================================
# SWARM AGENTS
# ==========================================
# diverse models for different perspectives
SWARM_MODELS = [
    {"id": "google/gemini-3-flash-preview", "role": "Conservative Risk Manager"},
    {"id": "google/gemini-3-flash-preview", "role": "Aggressive Trend Follower"},
    {"id": "google/gemini-3-flash-preview", "role": "Pattern Recognition Specialist"},
]

# ==========================================
# MASTER AGGREGATOR
# ==========================================
# Capable and fast model for synthesis
MASTER_MODEL_ID = "google/gemini-3-flash-preview"

# ==========================================
# RISK MANAGER
# ==========================================
# Fast, smart model for Risk assessment
RISK_MODEL_ID = "google/gemini-3-flash-preview"

# ==========================================
# REFLECTION AGENT
# ==========================================
# Model for reviewing past performance
REFLECTION_MODEL_ID = "google/gemini-3-flash-preview"
