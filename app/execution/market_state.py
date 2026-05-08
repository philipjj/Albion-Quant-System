from dataclasses import dataclass

@dataclass(frozen=True)
class MarketState:
    """
    Immutable representation of the market state for an item.
    """
    spread: float
    vwap_buy: float
    vwap_sell: float
    imbalance: float
    liquidity_score: float
    volatility: float
    manipulation_risk: float
