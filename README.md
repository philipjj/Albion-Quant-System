# Albion Quant System (AQS) - Institutional Market Intelligence

AQS is an advanced quantitative trading and market-making intelligence engine for Albion Online. Unlike standard arbitrage tools, AQS models **market microstructure**, **execution slippage**, and **adversarial price regimes** to identify alpha that survives real-world market conditions.

---

## 🏗 Architecture
The system is built on a 5-layer quantitative stack:

1.  **Ingestion Layer:** Multi-threaded collector interfacing with the Albion Data Project API (Prices, History, and Order Depth).
2.  **Statistical Engine:** Performs anomaly detection, Z-Score regime classification, and volatility EWMA.
3.  **Execution Simulator:** Models order book depth, calculates slippage curves, and estimates Market Absorption (OAC).
4.  **Personalization Engine:** Factors in player-specific Specialization (Spec), Focus Efficiency, and local tax rates.
5.  **Alpha Ranker:** Multiplicative scoring engine that ranks opportunities by survival-adjusted Expected Value (EV/hr).

---

## 📐 Mathematical Models

### 1. The Alpha Score (Execution-Aware EV)
Instead of additive scoring, AQS uses **Multiplicative Dampening**. If any single risk factor (like lack of liquidity) is catastrophic, the opportunity score correctly collapses toward zero.

$$A = P \times V \times T \times OAC \times R$$

*   **P (Realized Profit):** $Revenue - (Cost + Fees + Transport + RiskPenalty)$
*   **V (Velocity):** $DailyVolume / 24$
*   **T (Trust/Regime):** Scaled by Z-Score (see below).
*   **OAC (Absorption):** Estimation of buy-side depth relative to position size.
*   **R (Risk):** Route danger and item value density penalty.

### 2. Regime Detection (Z-Score)
To detect market manipulation, pumps, and dumps, the system calculates the statistical distance of the current price from the 24-hour mean.

$$Z = \frac{P_{current} - \mu_{24h}}{\sigma_{24h}}$$

*   $|Z| > 2.5$: Classified as **Adversarial Regime** (Manipulation). Score penalized by 85%.
*   $1.5 < |Z| < 2.5$: Classified as **Volatile Regime**. Score penalized by 40%.

### 3. Order Book Absorption Coefficient (OAC)
Models the "Ghost Liquidity" trap where a high spread exists on paper but lacks depth.

$$OAC = \min\left(1, \frac{\sum \text{BuyDepth}_{\text{within } 3\%}}{\text{TargetQuantity}}\right)$$

### 4. Blended Execution Price (BEP)
Prevents relying on thin "Ask" prices by blending the top of the order book.

$$BEP = (0.7 \times \text{SellMin}) + (0.3 \times \text{BuyMax})$$

---

## 📂 Project Structure

```text
AQS/
├── app/
│   ├── alerts/         # Discord Bot & Notification Logic
│   ├── arbitrage/      # Cross-city Transport Scanner
│   ├── crafting/       # Recursive Crafting Cost Optimizer
│   ├── core/           
│   │   ├── constants.py# Game Mechanics (RRR, Taxes, Station Fees)
│   │   ├── scoring.py  # The Alpha Ranker (Scientific Scoring)
│   │   └── market_utils# Price Blending & Statistical Helpers
│   ├── db/             # SQLAlchemy Models & Migrations
│   └── ingestion/      # Multi-endpoint Market Collector
├── workers/            # Background Schedulers & Jobs
├── data/               # Persistent SQLite & JSON Storage
├── main.py             # System Entry Point
└── STACKMAP.md         # Developer & CI/CD Documentation
```

---

## 🚀 Getting Started

### Prerequisites
*   Python 3.10+
*   FastAPI & Uvicorn
*   Discord Bot Token (optional for alerts)

### Installation
```bash
git clone https://github.com/philipjj/Albion-Quant-System.git
cd Albion-Quant-System
pip install -r requirements.txt
```

### Execution
```bash
# Start the full system (API + Scheduler + Bot)
python main.py

# CLI Mode: Run a single deep scan
python main.py --scan
```

---

## 🛡 Disclaimer
AQS is a market analysis tool. It does not automate gameplay or interact with the Albion Online game client. All data is sourced from the crowdsourced Albion Data Project.
