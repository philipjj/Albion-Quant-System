# AQS vNext Master Roadmap

## Building a Modular Synthetic-Economy Quantitative Research Platform with Hermes-Agent

---

# 1. Mission Statement

The objective of this roadmap is to transform the Albion Quant System (AQS) from:

* an advanced market utility,
* a statistical arbitrage scanner,
* and a crafting optimization tool,

into:

> A modular synthetic-economy quantitative research infrastructure capable of probabilistic alpha modeling, execution simulation, self-improving research workflows, historical validation, and adaptive economic intelligence.

This system should resemble:

* a quant research platform,
* a market microstructure simulator,
* a synthetic-economy analytics engine,
* and an autonomous research agent ecosystem.

The system should NOT evolve into:

* an overfit AI trading bot,
* a monolithic heuristic engine,
* or an unstructured ML experiment.

---

# 2. Strategic Role of Hermes-Agent

The project will integrate:

[Hermes-Agent by Nous Research](https://github.com/NousResearch/hermes-agent)

Hermes-Agent will NOT replace AQS.

Instead, Hermes-Agent becomes:

* the autonomous reasoning layer,
* the research orchestration layer,
* the self-improvement layer,
* and the adaptive market intelligence coordinator.

AQS remains:

* the deterministic quantitative engine,
* the execution simulator,
* the feature computation layer,
* and the economic modeling system.

This separation is critical.

---

# 3. Architectural Philosophy

The platform must separate:

1. Market Data Infrastructure
2. Quantitative Feature Engineering
3. Statistical Research
4. Execution Simulation
5. Optimization
6. Autonomous Research Agents
7. Delivery & Visualization

No single module should own multiple responsibilities.

---

# 4. High-Level System Architecture

```text
                        ┌─────────────────────┐
                        │  Albion Data APIs   │
                        └──────────┬──────────┘
                                   │
                        ┌──────────▼──────────┐
                        │    Ingestion Layer   │
                        └──────────┬──────────┘
                                   │
                        ┌──────────▼──────────┐
                        │ Historical Storage   │
                        │ Timescale + Parquet  │
                        └──────────┬──────────┘
                                   │
                        ┌──────────▼──────────┐
                        │ Feature Engineering  │
                        └──────────┬──────────┘
                                   │
                 ┌─────────────────┴─────────────────┐
                 │                                   │
      ┌──────────▼──────────┐            ┌──────────▼──────────┐
      │ Quant Research Layer │            │ Hermes Agent Layer  │
      └──────────┬──────────┘            └──────────┬──────────┘
                 │                                   │
                 └─────────────────┬─────────────────┘
                                   │
                        ┌──────────▼──────────┐
                        │ Signal Generation    │
                        └──────────┬──────────┘
                                   │
                        ┌──────────▼──────────┐
                        │ Execution Simulation │
                        └──────────┬──────────┘
                                   │
                        ┌──────────▼──────────┐
                        │ Optimization Engine  │
                        └──────────┬──────────┘
                                   │
                        ┌──────────▼──────────┐
                        │ Dashboard & Alerts   │
                        └─────────────────────┘
```

---

# 5. Final Repository Structure

```text
AQS/
├── app/
│
├── ingestion/
├── storage/
├── features/
├── models/
├── signals/
├── execution/
├── research/
├── optimization/
├── transport/
├── crafting/
├── regimes/
├── analytics/
├── market_intelligence/
├── ml/
├── agents/
│   ├── hermes/
│   ├── planners/
│   ├── evaluators/
│   ├── autonomous_research/
│   └── memory/
├── api/
├── alerts/
├── dashboard/
├── monitoring/
└── shared/
```

---

# 6. Core System Ontology

The platform must formalize domain entities.

---

## 6.1 MarketSnapshot

Represents:

* order book state,
* spread,
* depth,
* liquidity,
* timestamped market conditions.

Required fields:

```python
MarketSnapshot:
    item_id
    city
    timestamp

    best_bid
    best_ask

    bid_depth
    ask_depth

    spread
    midprice

    rolling_volume
    volatility
```

---

## 6.2 Signal

A Signal is:

> a statistically abnormal market condition.

Examples:

* spread anomalies,
* volatility spikes,
* imbalance events,
* mean reversion candidates.

---

## 6.3 Opportunity

An Opportunity is:

> a Signal after execution simulation.

Includes:

* VWAP estimation,
* slippage,
* fill probability,
* transport cost.

---

## 6.4 Alpha

Alpha is:

> risk-adjusted expected value.

Includes:

* expected utility,
* decay risk,
* execution realism,
* probabilistic success.

---

# 7. Data Infrastructure Migration

---

# 7.1 Replace SQLite

SQLite is no longer sufficient.

Required migration:

## Real-Time Data

Use:

```text
PostgreSQL + TimescaleDB
```

Store:

* active order books,
* latest snapshots,
* opportunities,
* live metrics.

---

## Historical Research Data

Use:

```text
Apache Parquet
```

Partition structure:

```text
/year/month/day/city/item/
```

This enables:

* replay,
* backtesting,
* factor analysis,
* ML datasets,
* historical calibration.

---

## Cache Layer

Use:

```text
Redis
```

For:

* active opportunities,
* hot market snapshots,
* dashboard streams,
* alert queues.

---

# 8. Feature Engineering Layer

Create:

```text
features/
├── volatility.py
├── imbalance.py
├── spread.py
├── liquidity.py
├── mean_reversion.py
├── momentum.py
├── decay.py
├── transport.py
└── focus_efficiency.py
```

Features must NEVER be computed inline inside scanners.

Every feature must:

* be reusable,
* independently testable,
* historically reproducible,
* exportable for ML.

---

# 9. Quantitative Models

---

# 9.1 Ornstein-Uhlenbeck Mean Reversion

Implement:

* mean reversion speed,
* half-life estimation,
* persistence detection.

Primary output:

```python
half_life_seconds
```

Used for:

* signal urgency,
* alpha survival,
* decay modeling.

---

# 9.2 Order Book Imbalance

Implement:

```math
I = (V_bid - V_ask) / (V_bid + V_ask)
```

Use for:

* directional pressure,
* fill probability,
* momentum detection.

---

# 9.3 Liquidity Metrics

Required metrics:

* market depth score,
* spread stability,
* refill speed,
* liquidity resilience.

---

# 10. Execution Simulation Layer

Create:

```text
execution/
├── vwap.py
├── slippage.py
├── fills.py
├── liquidity.py
├── orderbook.py
└── simulation.py
```

---

# 10.1 Replace BEP with VWAP

The engine must:

* traverse order books,
* simulate partial fills,
* consume liquidity tiers,
* estimate realistic execution.

Static weighted blending is deprecated.

---

# 10.2 Fill Probability Modeling

Probability inputs:

* imbalance,
* volatility,
* spread stability,
* liquidity,
* regime,
* historical execution success.

Output:

```python
P_fill
```

---

# 10.3 Alpha Decay Modeling

Estimate:

* expected alpha lifetime,
* opportunity exhaustion,
* decay velocity.

Used to:

* prioritize alerts,
* rank opportunities,
* estimate urgency.

---

# 11. Research & Backtesting Layer

Create:

```text
research/
├── replay/
├── backtesting/
├── calibration/
├── diagnostics/
├── benchmarks/
├── experiments/
└── notebooks/
```

---

# 11.1 Replay Engine

The replay engine must:

* reconstruct historical market states,
* replay signals chronologically,
* simulate execution,
* compare predicted EV vs realized outcomes.

---

# 11.2 Calibration Framework

All probabilities must be empirically validated.

Example:

If:

```python
P_fill = 0.8
```

Then historically:

~80% of similar trades should succeed.

This separates:

* probabilistic systems,
  from:
* heuristic systems.

---

# 11.3 Quant Metrics

Required metrics:

| Metric            | Purpose               |
| ----------------- | --------------------- |
| Hit Rate          | Signal profitability  |
| EV Error          | Model calibration     |
| Alpha Decay       | Signal lifetime       |
| Sharpe-like Ratio | Risk-adjusted quality |
| Drawdown          | Stability             |
| Slippage Error    | Execution realism     |

---

# 12. Regime Engine

Create:

```text
regimes/
├── classifier.py
├── volatility_regime.py
├── liquidity_regime.py
├── manipulation.py
└── trend_regime.py
```

---

# 12.1 Market States

Supported regimes:

| Regime         | Meaning                |
| -------------- | ---------------------- |
| Stable         | Efficient market       |
| Trending       | Momentum persistence   |
| Mean-Reverting | Statistical reversion  |
| Illiquid       | Low confidence         |
| Adversarial    | Manipulated conditions |

---

# 13. Market Intelligence Layer

Rename:

```text
meta/
```

to:

```text
market_intelligence/
```

This system models:

* patch changes,
* killboard volatility,
* PvP intensity,
* item demand shifts,
* seasonal cycles,
* meta changes.

This becomes:

> synthetic economic intelligence.

---

# 14. Hermes-Agent Integration Strategy

Hermes-Agent should become the autonomous coordination layer.

It should NOT directly own:

* market math,
* execution simulation,
* deterministic quantitative calculations.

Hermes should instead:

* coordinate research,
* analyze patterns,
* propose experiments,
* generate hypotheses,
* evaluate signal quality,
* orchestrate self-improvement.

---

# 14.1 Create Agent Layer

```text
agents/
├── hermes/
├── planners/
├── evaluators/
├── autonomous_research/
└── memory/
```

---

# 14.2 Hermes Agent Roles

---

## Research Planner Agent

Responsibilities:

* propose new factors,
* suggest experiments,
* identify weak-performing signals.

Example:

```text
"Signals with high spread but low liquidity fail frequently.
Suggest integrating spread stability into EV weighting."
```

---

## Signal Evaluator Agent

Responsibilities:

* review signal outcomes,
* compare expected vs realized EV,
* detect calibration drift.

---

## Strategy Research Agent

Responsibilities:

* test combinations of features,
* identify profitable regime-specific behavior,
* generate experimental strategies.

---

## Market Intelligence Agent

Responsibilities:

* analyze patch notes,
* detect meta shifts,
* infer demand changes.

---

## Alert Prioritization Agent

Responsibilities:

* rank urgency,
* estimate alpha decay,
* summarize market context.

---

# 14.3 Hermes Memory Integration

The agent memory layer should store:

* previous research findings,
* failed experiments,
* calibration history,
* regime observations,
* signal diagnostics.

This allows:

* adaptive research,
* iterative improvement,
* self-evaluating workflows.

---

# 14.4 Hermes Safety Constraints

Hermes must NEVER:

* autonomously mutate production logic,
* overwrite scoring models,
* alter execution code directly.

Instead:

Hermes generates:

* recommendations,
* experiment proposals,
* research reports,
* diagnostics.

Human approval remains required.

---

# 15. Optimization Layer

Create:

```text
optimization/
├── cargo.py
├── routing.py
├── focus.py
├── capital.py
└── portfolio.py
```

---

# 15.1 Portfolio Optimization

Optimize:

* cargo allocation,
* capital efficiency,
* opportunity bundling,
* inventory overlap,
* route utility.

---

# 15.2 Focus Optimization

Crafting should optimize:

* silver per focus,
* marginal focus efficiency,
* recursive production value.

---

# 15.3 Route Optimization

Use:

* transport risk,
* killboard activity,
* travel time,
* carrying weight,
* route danger.

This becomes:

> a logistics optimization engine.

---

# 16. Dashboard & Observability

Create:

```text
dashboard/
```

Recommended stack:

```text
FastAPI + React
```

Alternative:

```text
FastAPI + Streamlit
```

---

# 16.1 Required Visualizations

Implement:

* spread heatmaps,
* liquidity depth charts,
* alpha decay timelines,
* regime overlays,
* transport risk maps,
* fill probability surfaces,
* volatility clustering.

The UI should resemble:

* Bloomberg Terminal,
* quant analytics dashboards,
* institutional research platforms.

Avoid:

* gaming aesthetics,
* flashy MMO styling.

---

# 17. ML Layer

ML should be used selectively.

Good ML targets:

* fill probability,
* alpha survival,
* regime classification,
* anomaly detection,
* demand forecasting.

Avoid:

* generic AI price prediction hype.

---

# 18. CI/CD & Engineering Standards

The agent must enforce:

---

## Code Quality

Required:

* Ruff
* Black
* MyPy
* Pytest

---

## Testing Layers

Required test types:

* unit tests,
* integration tests,
* replay validation tests,
* execution simulation tests,
* calibration tests.

---

## Containerization

Use:

```text
Docker + Docker Compose
```

Services:

* API
* TimescaleDB
* Redis
* Workers
* Hermes Agent
* Dashboard

---

# 19. Development Execution Order

The implementation MUST follow this sequence.

---

# Stage 1 — Foundation Refactor

1. Repository restructure
2. Introduce domain models
3. Split core monolith
4. Add storage abstraction layer
5. Migrate SQLite → TimescaleDB
6. Add Parquet historical storage
7. Add Redis cache layer

---

# Stage 2 — Quant Infrastructure

8. Build feature engineering layer
9. Add feature snapshot persistence
10. Implement OU half-life
11. Implement liquidity metrics
12. Implement imbalance metrics
13. Add regime classification

---

# Stage 3 — Execution Realism

14. Build VWAP engine
15. Add order book traversal
16. Add slippage modeling
17. Add fill probability estimation
18. Add alpha decay modeling

---

# Stage 4 — Research Systems

19. Build replay engine
20. Add backtesting framework
21. Add diagnostics layer
22. Add calibration framework
23. Add statistical benchmarking

---

# Stage 5 — Hermes Integration

24. Integrate Hermes-Agent
25. Build research planner agent
26. Build evaluator agent
27. Build strategy experimentation agent
28. Build market intelligence agent
29. Add memory persistence
30. Add autonomous research workflows

---

# Stage 6 — Optimization Systems

31. Build transport optimizer
32. Add cargo allocation solver
33. Add focus optimization
34. Add portfolio allocation engine

---

# Stage 7 — Platform & UI

35. Build dashboard
36. Add live streaming updates
37. Add analytics visualizations
38. Add weekly quant reports
39. Add research reporting system

---

# Stage 8 — Advanced Research

40. Add ML pipelines
41. Add anomaly detection
42. Add strategy attribution
43. Add adaptive calibration
44. Add autonomous factor research

---

# 20. Final Deliverable

The final platform should behave like:

> A modular synthetic-economy quantitative research infrastructure capable of:

* modeling fragmented virtual economies,
* estimating executable alpha,
* simulating liquidity interaction,
* validating signals historically,
* optimizing capital allocation,
* autonomously researching market behavior,
* and visualizing synthetic economic microstructure.

---

# 21. Final Positioning

AQS should no longer be described as:

```text
Albion trading bot
```

or:

```text
MMORPG arbitrage scanner
```

Instead:

```text
Synthetic-Economy Quantitative Research Infrastructure
```
