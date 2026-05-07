import math
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.core.feature_gate import feature_gate


class ExpectedValueScorer:
    """
    Institutional-grade Expected Value scoring engine.

    Core Model:
        EV/hr =
            (
                RealizedNetProfit
                * ExecutionProbability
                * DataConfidence
                * LiquidityConfidence
                * SpreadConfidence
            )
            / EffectiveCycleHours

    Features:
    - Dynamic slippage curve
    - Liquidity-aware sizing
    - Volatility-adjusted confidence
    - Route risk decay
    - Manipulation penalties
    - Persistence weighting
    - Spread realism detection
    - Capital efficiency normalization
    """

    # ============================================================
    # EXECUTION MODEL WEIGHTS
    # ============================================================

    A_VELOCITY = 0.72
    B_PERSISTENCE = 0.41
    C_VOLATILITY = 1.18
    D_SPREAD = 0.55

    # ============================================================
    # RISK MODEL
    # ============================================================

    LOSS_RATE = 1.0
    BASE_DEATH_FACTOR = 0.035

    # ============================================================
    # MARKET IMPACT MODEL
    # ============================================================

    BASE_SLIPPAGE = 0.0025
    IMPACT_EXPONENT = 1.12

    # ============================================================
    # TIME MODEL
    # ============================================================

    BASE_CRAFT_TIME = 0.08
    BASE_TRANSPORT_TIME = 0.20
    BASE_SELL_DELAY = 0.40

    # ============================================================
    # SAFETY LIMITS
    # ============================================================

    MAX_SPREAD_RATIO = 0.65
    MAX_VOLATILITY = 1.5
    MAX_RISK_SCORE = 1.0

    # ============================================================
    # HELPERS
    # ============================================================

    @staticmethod
    def sigmoid(x: float) -> float:
        return 1.0 / (1.0 + math.exp(-x))

    @staticmethod
    def clamp(v: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, v))

    # ============================================================
    # DATA CONFIDENCE
    # ============================================================

    def calculate_data_confidence(self, op: dict[str, Any]) -> float:
        """
        Confidence score:
            0.0 = garbage
            1.0 = highly trustworthy
        """

        confidence = 0.0

        # --------------------------------------------------------
        # Endpoint reliability
        # --------------------------------------------------------

        if feature_gate.prices_supported:
            confidence += 0.30
        else:
            confidence += 0.08

        # --------------------------------------------------------
        # Freshness decay
        # --------------------------------------------------------

        try:
            detected = datetime.fromisoformat(
                op.get("detected_at", datetime.utcnow().isoformat())
            )

            if detected.tzinfo is not None:
                now = datetime.now(timezone.utc)
            else:
                now = datetime.utcnow()

            age_minutes = max(
                0.0,
                (now - detected).total_seconds() / 60.0
            )

            freshness = math.exp(-0.012 * age_minutes)
            confidence += 0.28 * freshness

        except Exception:
            confidence += 0.05

        # --------------------------------------------------------
        # Volume verification
        # --------------------------------------------------------

        volume_source = op.get("volume_source", "ESTIMATED")

        if volume_source == "VERIFIED 24H":
            confidence += 0.24
        else:
            confidence += 0.08

        # --------------------------------------------------------
        # Orderbook completeness
        # --------------------------------------------------------

        if feature_gate.orders_supported:
            confidence += 0.12
        else:
            confidence += 0.03

        # --------------------------------------------------------
        # Volatility penalty
        # --------------------------------------------------------

        volatility = float(op.get("volatility") or 0.05)

        vol_penalty = min(0.20, volatility * 0.25)
        confidence -= vol_penalty

        return self.clamp(confidence, 0.05, 1.0)

    # ============================================================
    # LIQUIDITY CONFIDENCE
    # ============================================================

    def calculate_liquidity_confidence(
        self,
        daily_volume: float,
        quantity: float,
    ) -> float:
        """
        Penalizes oversized positions relative to actual market flow.
        """

        if daily_volume <= 0:
            return 0.10

        participation_rate = quantity / max(1.0, daily_volume)

        # <2% participation = excellent
        if participation_rate <= 0.02:
            return 1.0

        decay = math.exp(-participation_rate * 8.0)
        return self.clamp(decay, 0.05, 1.0)

    # ============================================================
    # SPREAD CONFIDENCE
    # ============================================================

    def calculate_spread_confidence(
        self,
        buy_price: float,
        sell_price: float,
    ) -> float:
        """
        Wide spreads often indicate:
        - fake liquidity
        - stale listings
        - manipulated markets
        """

        if sell_price <= 0:
            return 0.0

        spread_ratio = (sell_price - buy_price) / sell_price

        if spread_ratio <= 0:
            return 0.0

        if spread_ratio > self.MAX_SPREAD_RATIO:
            return 0.05

        confidence = 1.0 - (spread_ratio / self.MAX_SPREAD_RATIO)
        return self.clamp(confidence, 0.05, 1.0)

    # ============================================================
    # EXECUTION PROBABILITY
    # ============================================================

    def calculate_p_exec(
        self,
        sales_velocity: float,
        persistence: int,
        volatility: float,
        spread_ratio: float,
    ) -> float:
        """
        Probability opportunity can actually be executed profitably.
        """

        log_vel = math.log(max(1.0, sales_velocity))

        persistence_norm = min(1.0, persistence / 12.0)

        spread_penalty = spread_ratio * self.D_SPREAD

        raw_score = (
            (self.A_VELOCITY * log_vel)
            + (self.B_PERSISTENCE * persistence_norm)
            - (self.C_VOLATILITY * volatility)
            - spread_penalty
        )

        return self.clamp(
            self.sigmoid(raw_score),
            0.01,
            0.99,
        )

    # ============================================================
    # DYNAMIC SLIPPAGE MODEL
    # ============================================================

    def calculate_slippage(
        self,
        quantity: float,
        daily_volume: float,
        volatility: float,
    ) -> float:
        """
        Market impact model.

        Larger share of daily volume =
        exponentially worse execution.
        """

        if daily_volume <= 0:
            return 0.25

        participation = quantity / max(1.0, daily_volume)

        impact = (
            self.BASE_SLIPPAGE
            + (
                participation ** self.IMPACT_EXPONENT
            ) * (0.35 + volatility)
        )

        return self.clamp(impact, 0.0, 0.80)

    # ============================================================
    # HOLD TIME MODEL
    # ============================================================

    def calculate_hold_time(
        self,
        quantity: float,
        sales_velocity: float,
        is_crafting: bool,
        risk_score: float,
    ) -> float:
        """
        Total expected cycle time in hours.
        """

        liquidation_time = quantity / max(0.1, sales_velocity)

        transport_time = self.BASE_TRANSPORT_TIME * (1.0 + risk_score)

        craft_time = self.BASE_CRAFT_TIME if is_crafting else 0.0

        total = (
            self.BASE_SELL_DELAY
            + transport_time
            + craft_time
            + liquidation_time
        )

        return max(0.25, total)

    # ============================================================
    # POSITION SIZING
    # ============================================================

    def calculate_position_size(
        self,
        buy_price: float,
        daily_volume: float,
        volatility: float,
    ) -> float:
        """
        Dynamic sizing based on:
        - available capital
        - market liquidity
        - volatility
        """

        if buy_price <= 0:
            return 0.0

        capital_limit = (
            settings.max_capital_per_trade / buy_price
        )

        liquidity_limit = (
            (daily_volume / 24.0)
            * settings.target_exit_hours
        )

        volatility_penalty = 1.0 / (1.0 + (volatility * 2.5))

        quantity = min(capital_limit, liquidity_limit)
        quantity *= volatility_penalty

        return max(1.0, quantity)

    # ============================================================
    # MAIN SCORING
    # ============================================================

    def score_arbitrage(self, op: dict[str, Any]) -> float:
        """
        Master EV/hr scoring function.
        """

        # --------------------------------------------------------
        # INPUTS
        # --------------------------------------------------------

        buy_price = float(op.get("buy_price") or 0.0)
        sell_price = float(op.get("sell_price") or 0.0)

        if buy_price <= 0 or sell_price <= 0:
            return 0.0

        daily_volume = float(op.get("daily_volume") or 0.0)

        volatility = self.clamp(
            float(op.get("volatility") or 0.05),
            0.0,
            self.MAX_VOLATILITY,
        )

        persistence = int(op.get("persistence") or 1)

        risk_score = self.clamp(
            float(op.get("risk_score") or 0.05),
            0.0,
            self.MAX_RISK_SCORE,
        )

        is_crafting = "craft_cost" in op

        # --------------------------------------------------------
        # POSITION SIZE
        # --------------------------------------------------------

        quantity = self.calculate_position_size(
            buy_price,
            daily_volume,
            volatility,
        )

        # --------------------------------------------------------
        # SLIPPAGE
        # --------------------------------------------------------

        slippage = self.calculate_slippage(
            quantity,
            daily_volume,
            volatility,
        )

        effective_buy = buy_price * (1.0 + slippage)
        effective_sell = sell_price * (1.0 - slippage)

        # --------------------------------------------------------
        # SPREAD ANALYSIS
        # --------------------------------------------------------

        spread_ratio = (
            (sell_price - buy_price) / sell_price
            if sell_price > 0 else 1.0
        )

        # --------------------------------------------------------
        # GROSS PROFIT
        # --------------------------------------------------------

        gross_profit = (
            (effective_sell - effective_buy)
            * quantity
        )

        # --------------------------------------------------------
        # FEES
        # --------------------------------------------------------

        market_fees = float(op.get("market_fees") or 0.0)
        market_fees *= quantity

        transport_cost = float(op.get("transport_cost") or 0.0)
        transport_cost *= quantity

        # --------------------------------------------------------
        # DEATH / FAILURE RISK
        # --------------------------------------------------------

        death_probability = (
            risk_score * self.BASE_DEATH_FACTOR
        )

        cargo_value = effective_buy * quantity

        risk_penalty = (
            death_probability
            * cargo_value
            * self.LOSS_RATE
        )

        # --------------------------------------------------------
        # NET PROFIT
        # --------------------------------------------------------

        realized_profit = (
            gross_profit
            - market_fees
            - transport_cost
            - risk_penalty
        )

        if realized_profit <= 0:
            return 0.0

        # --------------------------------------------------------
        # VELOCITY
        # --------------------------------------------------------

        sales_velocity = max(
            0.1,
            daily_volume / 24.0
        )

        # --------------------------------------------------------
        # HOLD TIME
        # --------------------------------------------------------

        hold_hours = self.calculate_hold_time(
            quantity,
            sales_velocity,
            is_crafting,
            risk_score,
        )

        # --------------------------------------------------------
        # EXECUTION PROBABILITY
        # --------------------------------------------------------

        p_exec = self.calculate_p_exec(
            sales_velocity,
            persistence,
            volatility,
            spread_ratio,
        )

        # --------------------------------------------------------
        # CONFIDENCE LAYERS
        # --------------------------------------------------------

        data_confidence = self.calculate_data_confidence(op)

        liquidity_confidence = self.calculate_liquidity_confidence(
            daily_volume,
            quantity,
        )

        spread_confidence = self.calculate_spread_confidence(
            buy_price,
            sell_price,
        )

        # --------------------------------------------------------
        # CAPITAL EFFICIENCY
        # --------------------------------------------------------

        capital_used = effective_buy * quantity

        if capital_used <= 0:
            return 0.0

        capital_efficiency = realized_profit / capital_used

        # --------------------------------------------------------
        # FINAL EV SCORE
        # --------------------------------------------------------

        ev_hourly = (
            (
                realized_profit
                * p_exec
                * data_confidence
                * liquidity_confidence
                * spread_confidence
            )
            / hold_hours
        )

        # --------------------------------------------------------
        # CAPITAL EFFICIENCY BOOST
        # --------------------------------------------------------

        ev_hourly *= (1.0 + (capital_efficiency * 1.5))

        # --------------------------------------------------------
        # ABSORPTION PENALTY (OAC)
        # --------------------------------------------------------

        oac = float(op.get("oac") or 1.0)
        ev_hourly *= (0.2 + (oac * 0.8)) # Dampen but don't zero out completely

        # --------------------------------------------------------
        # EXTREME MANIPULATION FILTER
        # --------------------------------------------------------

        if spread_ratio > 0.80:
            ev_hourly *= 0.05

        if volatility > 0.90:
            ev_hourly *= 0.30

        # Z-Score Regime Detection: Detect abnormal spikes or crashes
        z_score = abs(float(op.get("z_score") or 0.0))
        if z_score > 2.5:
            # Price is in an extreme anomaly regime (manipulation/pump)
            ev_hourly *= 0.15
        elif z_score > 1.5:
            # Elevated volatility regime
            ev_hourly *= 0.60

        if daily_volume <= 1:
            ev_hourly *= 0.20

        # --------------------------------------------------------
        # FINAL SAFETY CLAMP
        # --------------------------------------------------------

        return round(max(0.0, ev_hourly), 2)


scorer = ExpectedValueScorer()