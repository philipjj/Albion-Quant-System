import math
from datetime import datetime
from shared.domain.signal import Signal
from shared.domain.opportunity import Opportunity
from shared.domain.alpha import Alpha
from app.core.constants import DANGEROUS_ROUTES, get_distance

def calculate_data_confidence(signal: Signal) -> float:
    """Calculates confidence score based on data age and market liquidity."""
    metadata = signal.metadata
    
    # 1. Exponential Freshness Decay
    age_sec = metadata.get("data_age_seconds") or 0
    age_min = age_sec / 60.0
    freshness = math.exp(-age_min / 45.0)

    # 2. Liquidity Confidence
    volume = metadata.get("daily_volume", 0)
    volume_score = min(1.0, volume / 50.0) if volume > 0 else 0.1

    # 3. Persistence Bonus
    persistence = metadata.get("persistence", 1)
    persistence_bonus = min(0.3, (persistence - 1) * 0.1)

    # 4. Volatility Penalty
    volatility = metadata.get("volatility", 0.05)
    volatility_penalty = max(0.0, volatility * 2.0)

    confidence = (freshness * 0.4) + (volume_score * 0.3) + persistence_bonus - volatility_penalty
    return round(max(0.05, min(1.0, confidence)), 4)

def calculate_fill_probability(volume_24h: int, margin_pct: float) -> float:
    """Estimates execution probability."""
    if volume_24h <= 0: return 0.05
    vol_factor = min(1.0, volume_24h / 150)
    margin_penalty = 1.0
    if margin_pct > 30: margin_penalty = 0.6
    if margin_pct > 100: margin_penalty = 0.1
    return round(vol_factor * margin_penalty, 2)

def derive_opportunity(signal: Signal, market_data: dict) -> Opportunity:
    """Derives an Opportunity from a Signal and market data."""
    volume = market_data.get("daily_volume", 0)
    margin_pct = market_data.get("estimated_margin", 0.0)
    
    fill_prob = calculate_fill_probability(volume, margin_pct)
    
    source_city = market_data.get("source_city", signal.city)
    destination_city = market_data.get("destination_city", signal.city)
    
    dist = get_distance(source_city, destination_city)
    weight = market_data.get("item_weight") or 0.5
    
    # Fix the bug: derive risk_multiplier from DANGEROUS_ROUTES
    risk_multiplier = 1.0
    if (source_city, destination_city) in DANGEROUS_ROUTES:
        risk_multiplier = 2.0
        
    transport_cost = (dist * weight * 250) * risk_multiplier
    
    return Opportunity(
        signal=signal,
        vwap_estimation=market_data.get("vwap_estimation", 0.0),
        slippage=market_data.get("slippage", 0.0),
        fill_probability=fill_prob,
        transport_cost=transport_cost,
        estimated_profit=market_data.get("estimated_profit", 0.0)
    )

def derive_alpha(opportunity: Opportunity) -> Alpha:
    """Derives Alpha from an Opportunity."""
    confidence = calculate_data_confidence(opportunity.signal)
    
    net_profit = opportunity.estimated_profit
    fill_prob = opportunity.fill_probability
    transport_cost = opportunity.transport_cost
    
    # ERPH calculation
    expected_value = (net_profit * fill_prob * confidence) - transport_cost
    
    return Alpha(
        opportunity=opportunity,
        expected_value=round(max(0.0, expected_value), 2),
        decay_risk=0.1,  # Placeholder or derived from volatility
        confidence=confidence
    )
