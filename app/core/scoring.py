import math
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from app.core.logging import log
from app.core.feature_gate import feature_gate
from app.core.config import settings

class ExpectedValueScorer:
    """
    Unifies profitability, execution feasibility, and data trust into 
    a single Expected Value (EV) per hour signal.
    """
    
    A_VELOCITY = 0.5
    B_PERSISTENCE = 0.3
    C_VOLATILITY = 0.8
    
    LOSS_RATE = 1.0  # Cargo value lost on death
    COST_PER_TILE = 100  # Silver per unit per distance tile

    @staticmethod
    def sigmoid(x: float) -> float:
        return 1 / (1 + math.exp(-x))

    def calculate_data_confidence(self, op: Dict[str, Any]) -> float:
        """
        C_data model: Reliability + Freshness + Completeness
        """
        # 1. Endpoint Reliability (0.30)
        reliability = 0.30 if feature_gate.prices_supported else 0.0
        
        # 2. Data Freshness (0.25)
        # Assuming detected_at is ISO format string
        try:
            detected_at = datetime.fromisoformat(op.get("detected_at", datetime.utcnow().isoformat()))
            age_mins = (datetime.utcnow() - detected_at).total_seconds() / 60
            freshness = 0.25 * math.exp(-0.01 * age_mins) # Decay over time
        except:
            freshness = 0.1
            
        # 3. Sample Size / Consistency (0.35)
        # If volume_source is VERIFIED, we trust it more
        sample_size = 0.35 if op.get("volume_source") == "VERIFIED 24H" else 0.15
        
        # 4. Feature Completeness (0.10)
        completeness = 0.10 if feature_gate.orders_supported else 0.02 # Europe API penalty
        
        return reliability + freshness + sample_size + completeness

    def calculate_p_exec(self, sales_velocity: float, persistence: int, volatility: float) -> float:
        """
        P_exec = sigmoid(a*log(vel) + b*persistence - c*volatility)
        """
        # Normalize inputs
        log_vel = math.log(max(1, sales_velocity))
        norm_persistence = min(1.0, persistence / 10.0) # 10 scans = max persistence
        
        raw_score = (self.A_VELOCITY * log_vel) + (self.B_PERSISTENCE * norm_persistence) - (self.C_VOLATILITY * volatility)
        return self.sigmoid(raw_score)

    def score_arbitrage(self, op: Dict[str, Any]) -> float:
        """
        Full Scoring Formula for Arbitrage.
        Handles NoneType safety for all inputs.
        """
        # Ensure all required keys are present and are numbers
        buy_p = op.get("buy_price") or 0.0
        sell_p = op.get("sell_price") or 0.0
        daily_vol = op.get("daily_volume") or 0.0
        volatility = op.get("volatility") or 0.05
        persistence = op.get("persistence") or 1
        
        if buy_p <= 0 or sell_p <= 0:
            return 0.0

        # 1. Quantity (Q)
        max_capital = settings.max_capital_per_trade 
        q_max_capital = max_capital // max(1, buy_p)
        
        sales_velocity = daily_vol / 24.0
        q_max_liquidity = sales_velocity * settings.target_exit_hours
        
        Q = max(1, min(q_max_capital, q_max_liquidity))

        # 2. Effective Prices (Slippage Approximation)
        p_buy_eff = buy_p * (1 + volatility * 0.5)
        p_sell_eff = sell_p * (1 - volatility * 0.5)

        # 3. Costs
        gross_profit = (p_sell_eff - p_buy_eff) * Q
        fees = (op.get("market_fees") or 0.0) * (Q / 1)
        
        # Transport & Risk
        transport = ((op.get("transport_cost") or 0.0) / 1) * Q
        p_death = (op.get("risk_score") or 0.1) * 0.05
        risk_penalty = p_death * (buy_p * Q) * self.LOSS_RATE

        net_profit = gross_profit - fees - transport - risk_penalty

        # 4. Hold Time
        t_hold = 0.5 + 0.25 + (Q / max(0.1, sales_velocity))

        # 5. Execution Probability
        p_exec = self.calculate_p_exec(sales_velocity, persistence, volatility)

        # 6. Data Confidence
        confidence = self.calculate_data_confidence(op)

        # Final EV Score
        ev_score = (net_profit * p_exec / t_hold) * confidence
        return round(max(0.0, ev_score), 2)

scorer = ExpectedValueScorer()
