
# Antigravity Trading System (Alpha v2)

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.13-blue.svg)
![Status](https://img.shields.io/badge/status-active-success.svg)

> **Institutional-Grade AI Trading Agent (Neuro-Symbolic Architecture)**.
> Combines Large Language Models (Swarm Intelligence) with Quantitative Risk Engineering (Volatility Targeting).

---

## 📖 Executive Summary

This system is not a standard "if/then" trading bot. It is an **Autonomous Agentic System** designed for Swing Trading crypto assets. It utilizes a **Neuro-Symbolic** approach:
1.  **AI (Right Brain):** Use LLMs to simulate a specific investment committee ("Swarm") for qualitative analysis (Trend, Structure, Sentiment).
2.  **Quant (Left Brain):** Use strict mathematical models for Risk Management (Kelly Criterion, Volatility Targeting, Variance Analysis).

The goal is to outperform a passive **BTC Buy & Hold** strategy by avoiding drawdowns in "Choppy" regimes and sizing up aggressively in "Trending" regimes.

---

## 🏗 System Architecture

The codebase follows a modular **Service-Oriented Architecture (SOA)** with strict separation of concerns.

```mermaid
graph TD
    Data[Market Data Service] -->|OHLCV + Indicators| Orchestrator
    
    subgraph "Cognitive Layer (Agents)"
        Swarm[Swarm Intelligence]
        Reflect[Reflection Agent]
        RiskAgent[Risk Officer Agent]
    end
    
    subgraph "Mathematical Layer (Core)"
        RiskEng[Risk Engine (Vol Target)]
        PortHeat[Correlation Matrix]
    end
    
    Orchestrator -->|Context| Swarm
    Orchestrator -->|Performance| Reflect
    
    Swarm -->|Proposed Trade| Orchestrator
    Orchestrator -->|Validation| RiskAgent
    
    RiskAgent -.->|Consults| RiskEng
    RiskEng -.->|Hard Limits| RiskAgent
    
    Orchestrator -->|Execution| Account[Execution Service]
    Account -->|Persistence| MongoDB[(MongoDB)]
```

### Key Modules
| Module | Responsibility | key Technology |
| :--- | :--- | :--- |
| **`services/orchestrator.py`** | The "Brain". Manages the Learn -> Think -> Act loop. | AsyncIO, Dependency Injection |
| **`agents/swarm.py`** | "Alpha Hunters". Multiple LLM personas (Trend, Mean Rev) debate direction. | Chain-of-Thought Prompting |
| **`agents/risk_manager.py`** | "The Gatekeeper". Synthesizes Math limits with AI intuition. | OpenAI API, JSON Mode |
| **`core/risk_engine.py`** | "The Law". Calculates Volatility Adjusted Sizing & Correlation Penalties. | ATR, Standard Deviation |
| **`backtest/run.py`** | Time-Travel Simulator. Replays historical data through the *exact* live agents. | Parallel Processing |

---

## 🚀 Getting Started

### Prerequisites
*   Python 3.10+
*   MongoDB (cloud or local)
*   OpenRouter API Key (Supports GPT-4, Claude 3.5, Llama 3)

### Installation

1.  **Clone the Repository**
    ```bash
    git clone https://github.com/malli7/trading-bot-backend.git
    cd trading-bot-backend
    ```

2.  **Install Dependencies**
    It is recommended to use a virtual environment.
    ```bash
    python -m venv virtual
    source virtual/bin/activate
    pip install -r requirements.txt
    ```

3.  **Configuration**
    Create a `.env` file in the project root:
    ```env
    OPENROUTER_API_KEY=sk-or-v1-...
    MONGO_URI=mongodb+srv://...
    ```

### Running the System

**Live Trading Mode:**
Starts the `TradingOrchestrator` service running on a 15-minute cron schedule.
```bash
python main.py
```

**Backtest Mode:**
Simulates the last N days using historical data.
```bash
python backtest/run.py --days 30
```

---

## 🧠 Risk Management (The "Alpha")

Most retail bots fail because they act as "Gamblers". This system acts as a "Casino".

### 1. Volatility Targeting
We do not use fixed sizing (e.g., "$100 per trade").
*   **Formula:** `Size = (Target_Vol / Instrument_Vol) * Equity`
*   **Effect:** If Bitcoin becomes highly volatile, position size **reduces** automatically. If Bitcoin is stable, size **increases**. This keeps portfolio heat constant.

### 2. Correlation Checks
The `RiskEngine` calculates exposure to "Crypto Beta".
*   If you are Long BTC, the system applies a "Correction Penalty" to a proposed Long ETH trade, preventing over-leveraging on correlated assets.

### 3. Validation
The `RiskAssessmentAgent` (LLM) is given the "Hard Cap" from the math engine. It can lower the risk based on news/sentiment, but it is **forbidden** from exceeding the mathematical safety limit.

---

## ⚠️ Important Disclaimer

**For Educational and Research Purposes Only.**

*   Cryptocurrency trading involves substantial risk of loss and is not suitable for every investor.
*   This software is provided "AS IS", without warranty of any kind.
*   Past performance (backtesting) is NOT indicative of future results.
*   The authors are not registered financial advisors.

---
