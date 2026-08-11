"""
Quality Inversion Arbitrage Feature Module.
Detects mispriced items where a higher quality item (e.g. Quality 2/3/4/5)
is listed for a lower sell price than a lower quality item (or lower than buy order max).
"""

from typing import Any
from app.core.opportunity_engine import is_price_valid

QUALITY_NAMES = {
    1: "Normal",
    2: "Good",
    3: "Outstanding",
    4: "Excellent",
    5: "Masterpiece",
}


def detect_quality_inversion(
    quality_prices: dict[int, dict[str, Any]],
    item_id: str,
    city: str,
    item_name: str = "",
    min_profit: int = 5000,
    min_margin: float = 3.0,
    tax_rate: float = 0.08,
    setup_fee_rate: float = 0.025,
    min_volume: int = 1,
    max_price_ratio: float = 2.5,
) -> list[dict[str, Any]]:
    """
    Scans a nested quality price dict {quality: {"sell_price_min": int, "buy_price_max": int, ...}}
    for quality inversions.
    
    Condition: A higher quality item (q_high) has sell_price_min LOWER than a lower quality item (q_low) sell_price_min,
    OR lower than q_low buy_price_max.
    """
    inversions = []
    qualities = sorted(quality_prices.keys())
    
    for i, q_low in enumerate(qualities):
        low_data = quality_prices[q_low]
        low_sp = low_data.get("sell_price_min", 0)
        low_bm = low_data.get("buy_price_max", 0)
        low_vol = low_data.get("volume_24h", 0)
        
        for q_high in qualities[i + 1:]:
            high_data = quality_prices[q_high]
            high_sp = high_data.get("sell_price_min", 0)
            high_bm = high_data.get("buy_price_max", 0)
            high_age = high_data.get("data_age_seconds", 9999)
            high_vol = high_data.get("volume_24h", 0)
            
            if high_sp <= 0 or high_age > 7200:
                continue
            
            if not is_price_valid(high_sp, high_bm, item_id=item_id):
                continue
                
            # Filter zero / low volume items (Anti-Bait safeguard)
            if min_volume > 0:
                if high_vol < min_volume or low_vol < min_volume:
                    continue

            # Case 1: Higher quality listed cheaper than lower quality sell price (Sell undercut)
            if low_sp > 0 and is_price_valid(low_sp, low_bm, item_id=item_id) and high_sp < low_sp:
                # Outlier ratio check: reference price should not be unrealistically wider than high_sp * max_price_ratio
                if max_price_ratio > 0 and low_sp > high_sp * max_price_ratio:
                    continue

                net_payout = low_sp * (1.0 - tax_rate - setup_fee_rate)
                net_profit = net_payout - high_sp
                profit_pct = (net_profit / high_sp) * 100.0 if high_sp > 0 else 0.0
                
                if net_profit >= min_profit and profit_pct >= min_margin:
                    inversions.append({
                        "item_id": item_id,
                        "item_name": item_name or item_id,
                        "city": city,
                        "buy_quality": q_high,
                        "buy_quality_name": QUALITY_NAMES.get(q_high, f"Q{q_high}"),
                        "buy_price": high_sp,
                        "reference_quality": q_low,
                        "reference_quality_name": QUALITY_NAMES.get(q_low, f"Q{q_low}"),
                        "reference_price": low_sp,
                        "inversion_type": "MANUAL_LIST_REQUIRED",
                        "net_profit": round(net_profit, 2),
                        "profit_pct": round(profit_pct, 2),
                        "data_age_seconds": high_age,
                        "daily_volume": high_vol,
                    })

            # Case 2: Higher quality sell price lower than lower quality buy order (Instant fill)
            elif low_bm > 0 and is_price_valid(low_sp or low_bm, low_bm, item_id=item_id) and high_sp < low_bm:
                # Outlier ratio check: reference price should not be unrealistically wider than high_sp * max_price_ratio
                if max_price_ratio > 0 and low_bm > high_sp * max_price_ratio:
                    continue

                net_payout = low_bm * (1.0 - tax_rate)
                net_profit = net_payout - high_sp
                profit_pct = (net_profit / high_sp) * 100.0 if high_sp > 0 else 0.0
                
                if net_profit >= min_profit and profit_pct >= min_margin:
                    inversions.append({
                        "item_id": item_id,
                        "item_name": item_name or item_id,
                        "city": city,
                        "buy_quality": q_high,
                        "buy_quality_name": QUALITY_NAMES.get(q_high, f"Q{q_high}"),
                        "buy_price": high_sp,
                        "reference_quality": q_low,
                        "reference_quality_name": QUALITY_NAMES.get(q_low, f"Q{q_low}"),
                        "reference_price": low_bm,
                        "inversion_type": "INSTANT_BM_FILL",
                        "net_profit": round(net_profit, 2),
                        "profit_pct": round(profit_pct, 2),
                        "data_age_seconds": high_age,
                        "daily_volume": high_vol,
                    })
                    
    return inversions

