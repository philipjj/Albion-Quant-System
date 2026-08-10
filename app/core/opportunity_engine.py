"""
AQS Opportunity Engine — Redesigned from Player Perspective
============================================================

Three opportunity types, modeled exactly as a player would think:

1. BLACK MARKET (BM) FLIP
   Buy cheapest sell order in any royal city → instant-sell to BM buy order in Caerleon.
   BM pays zero tax, zero setup fee on the seller side.
   Net profit = bm_buy_price - cheapest_royal_sell_price
   Risk = travel through red/black zones to Caerleon.

2. CRAFTING → SELL (Royal market OR Black Market)
   Profit = revenue - material_cost_after_rrr - station_fee - market_tax
   Material cost is AFTER resource return rate (RRR).
   City crafting bonus: 33% RRR for matching category, 18% elsewhere.
   With Focus: +59% to production bonus → higher RRR.
   Revenue target is either BM buy order (0 tax) or royal city sell order (4% tax premium).

3. ROYAL CITY ARBITRAGE
   Buy cheapest sell_price_min in city A → sell at buy_price_max in city B.
   Instant-fill (no listing wait) using existing buy orders.
   Net = buy_price_max_B - sell_price_min_A - 4% tax.
   Only count buy_price_max not sell_price_min on the sell side — that's what
   a player actually gets paid immediately without waiting for a fill.

PRICE VALIDITY / OUTLIER RULES (the critical piece)
-----------------------------------------------------
Data from AODP is volunteer-uploaded. It can be:
  - Stale (no one scanned that city recently)
  - Manipulated (one player posted 1 item at 50x price to spoof the feed)
  - Ghost (sell order exists but has already been bought since last scan)

Validity checks applied:
  1. sell_price_min must be > 0
  2. buy_price_max must be > 0 for arb/BM (we need a real buyer)
  3. sell_price_min / buy_price_max ratio must be < 5x (>5x = manipulation)
  4. data_age_seconds < max_age_per_type (BM: 3600s, royal: 7200s)
  5. If sell_price_min * daily_volume > 0 → prefer; lone single-item outliers
     are suppressed by requiring buy_price_max as sanity anchor.
  6. Cross-city sanity: if sell_price_min in city A > 3x sell_price_min in city B
     for same item, flag as potential manipulation and use median instead.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.constants import calculate_station_fee

from app.execution.slippage import estimate_market_impact, calculate_safe_trade_limit, calculate_effective_price

# ─── Market Constants ────────────────────────────────────────────────────────

PREMIUM_TAX = 0.04  # 4% market sales tax (premium player)
NON_PREMIUM_TAX = 0.08  # 8%
SETUP_FEE = 0.025  # 2.5% listing fee (only paid when YOU list, not when buying)
BM_TAX = 0.0  # Black Market: zero fees to seller

# RRR (Resource Return Rate) — how much material comes back after crafting
# RRR = LPB / (1 + LPB)  where LPB = Local Production Bonus
BASE_LPB = 0.18  # 18% base — all royal cities, all items
REFINING_BONUS_LPB = 0.40  # +40% for matching city refining resource
CRAFT_BONUS_LPB = 0.15  # +15% for matching city crafting category
FOCUS_BONUS_LPB = 0.59  # +59% when using Focus


def rrr(city: str, category: str, use_focus: bool = False) -> float:
    """
    Returns Resource Return Rate as a fraction (0.0 – 0.99).
    Delegates to authoritative calculate_rrr in app.core.market_utils.
    """
    from app.core.market_utils import calculate_rrr
    return calculate_rrr(city, category, tier=4, use_focus=use_focus)


# Each city has crafting & refining specialities — items crafted here get higher RRR
CITY_CRAFT_BONUSES: dict[str, dict[str, list[str]]] = {
    "Martlock": {
        "refining": ["hide", "leather"],
        "crafting": ["axe", "quarterstaff", "frost_staff", "plate_shoes", "plate_boots", "leather_armor", "offhand", "off_hand"],
    },
    "Bridgewatch": {
        "refining": ["rock", "stone", "block", "stoneblock"],
        "crafting": ["crossbow", "dagger", "cursed_staff", "curse_staff", "plate_armor", "cloth_shoes", "cloth_boots"],
    },
    "Thetford": {
        "refining": ["ore", "bar", "metalbar"],
        "crafting": ["mace", "nature_staff", "fire_staff", "cloth_helmet", "cloth_headgear", "leather_armor"],
    },
    "Lymhurst": {
        "refining": ["fiber", "cloth"],
        "crafting": ["sword", "bow", "arcane_staff", "leather_helmet", "leather_hood", "leather_shoes", "leather_boots"],
    },
    "Fort Sterling": {
        "refining": ["wood", "planks"],
        "crafting": ["hammer", "spear", "holy_staff", "plate_helmet", "cloth_armor"],
    },
    "Caerleon": {
        "refining": [],
        "crafting": ["cooked_food", "food", "war_gloves", "shapeshifter_staff", "gathering_gear", "gathering_tool", "tool"],
    },
    "Brecilien": {
        "refining": [],
        "crafting": ["potion", "bag", "cape"],
    },
}

ROYAL_CITIES = ["Bridgewatch", "Martlock", "Lymhurst", "Fort Sterling", "Thetford"]
BM_CITY = "Black Market"
CAERLEON = "Caerleon"
BRECILIEN = "Brecilien"
ALL_SELL_CITIES = ROYAL_CITIES + [CAERLEON, BRECILIEN]

# Routes that pass through dangerous zones (Caerleon ring roads / Mists)
DANGEROUS_DESTINATIONS = {CAERLEON, BM_CITY, BRECILIEN}

# ─── Data Age Limits ─────────────────────────────────────────────────────────

MAX_AGE_BM_SECONDS = 3600  # 1 hour — BM orders clear quickly
MAX_AGE_ROYAL_SECONDS = 7_200  # 2 hours — royal city market limit
MAX_AGE_CRAFTING_SECONDS = 14_400  # 4 hours — acceptable for material cost calc

# ─── Outlier / Manipulation Detection ────────────────────────────────────────

MAX_SELL_TO_BUY_RATIO = 5.0  # If sell_min > buy_max * 5 → single-item manipulation
MIN_PRICE = 100  # Ignore anything below 100 silver (test orders)
ABSOLUTE_MAX_PRICE = 500_000_000  # 500M cap — anything higher is a troll order
MIN_ROYAL_VOLUME = 0  # Allow data with 0 or missing reported volume from community API
MIN_BM_VOLUME = 0      # BM orders are NPC generated


def get_min_realistic_price(item_id: str = "") -> int:
    """
    Returns minimum realistic market price based on item tier in Albion Online.
    Prevents corrupt 100-200 silver listings for high-tier equipment (T5-T8) from poisoning cost calculations.
    """
    if not item_id or not item_id.startswith("T"):
        return MIN_PRICE
    try:
        tier = int(item_id[1])
        tier_min_map = {
            4: 500,
            5: 1_500,
            6: 4_000,
            7: 12_000,
            8: 35_000,
        }
        return tier_min_map.get(tier, MIN_PRICE)
    except (ValueError, IndexError):
        return MIN_PRICE


def is_price_valid(sell_min: int, buy_max: int, daily_volume: int = 0, item_id: str = "") -> bool:
    """
    Returns True if the price pair looks like a real market, not manipulation or corrupt test data.
    """
    min_allowed = get_min_realistic_price(item_id) if item_id else MIN_PRICE
    if sell_min <= min_allowed:
        return False
    if sell_min > ABSOLUTE_MAX_PRICE:
        return False
    if buy_max > 0:
        if (sell_min / buy_max) > 8.0:
            return False
        if (buy_max / sell_min) > 8.0:
            return False

    return True


def is_bm_price_valid(bm_buy_price: int, item_value: float = 0.0) -> bool:
    """
    BM price should always be ABOVE royal sell price.
    Uses ItemValue as an anchor to detect unrealistic prices.
    """
    if bm_buy_price <= MIN_PRICE:
        return False
    if bm_buy_price > ABSOLUTE_MAX_PRICE:
        return False
    if item_value > 0 and (bm_buy_price / item_value) > 5000:
        return False
    return True


def cross_city_outlier_check(prices_by_city: dict[str, int]) -> dict[str, int]:
    """
    If one city's sell_price_min is >3x the median of other cities → outlier.
    Replace with median. This catches single-player manipulation.
    Example: Bridgewatch T7 sword at 50M when every other city shows 2M → discard.
    """
    valid = [p for p in prices_by_city.values() if p > MIN_PRICE]
    if len(valid) < 2:
        return prices_by_city

    sorted_prices = sorted(valid)
    median = sorted_prices[len(sorted_prices) // 2]

    cleaned = {}
    for city, price in prices_by_city.items():
        if price > median * 3:
            # Outlier — do NOT use this price as a buy source (player trap)
            cleaned[city] = 0  # Zeroed out = skipped by scanner
        else:
            cleaned[city] = price
    return cleaned


# ─── Opportunity Dataclasses ─────────────────────────────────────────────────


@dataclass
class BMOpportunity:
    """
    Black Market flip: buy in royal city, run to Caerleon, sell to BM buy order.
    No tax on the BM sell side. Risk = travel to Caerleon.
    """

    item_id: str
    item_name: str
    buy_city: str  # Where to buy the item (cheapest royal city)
    buy_price: int  # sell_price_min in buy_city (what you pay)
    bm_buy_price: int  # Black Market buy order (what BM pays you)
    net_profit: int  # bm_buy_price - buy_price (no fees on BM side)
    profit_pct: float  # net_profit / buy_price * 100
    daily_volume: int  # Volume in buy city (how many units trade daily)
    data_age_buy: int  # Age of buy city price in seconds
    data_age_bm: int  # Age of BM price in seconds
    quality: int = 1  # Black Market order quality
    buy_quality: int = 1  # Fulfilling item quality (>= order quality)
    can_be_crafted: bool = False  # If True, crafting route also shown
    craft_cost: float = 0.0  # If can_be_crafted, what it costs to craft
    craft_city: str = ""  # Best city to craft in
    safe_limit: int = 1
    roi: float = 0.0
    profit_per_kg: float = 0.0
    score: float = 0.0  # Ranking score

    @property
    def mode(self) -> str:
        """BUY = transport only; CRAFT+RUN = craft then transport to BM"""
        if self.can_be_crafted and self.craft_cost > 0 and self.craft_cost < self.buy_price:
            return "CRAFT+RUN"
        return "BUY+RUN"

    @property
    def effective_cost(self) -> float:
        if self.mode == "CRAFT+RUN":
            return self.craft_cost
        return float(self.buy_price)

    @property
    def effective_profit(self) -> float:
        return self.bm_buy_price - self.effective_cost


@dataclass
class EnchantingOpportunity:
    """
    Buy base item + runes/souls/relics in Caerleon, enchant at Artifact Foundry, sell to BM.
    Zero transport risk.
    """
    target_item_id: str
    target_item_name: str
    base_item_id: str
    base_price: int
    material_id: str
    material_qty: int
    material_price: int
    bm_buy_price: int
    net_profit: int
    profit_pct: float
    total_cost: int
    safe_limit: int
    roi: float = 0.0
    score: float = 0.0
    quality: int = 1
    data_age_base: int = 9999
    data_age_material: int = 9999
    data_age_bm: int = 9999
    base_city: str = "Caerleon"

@dataclass
class CraftingOpportunity:
    """
    Craft item using materials, sell on market or to BM.
    Profit = revenue - material_cost_after_rrr - station_fee - market_tax
    """

    item_id: str
    item_name: str
    craft_city: str  # Where to craft (best RRR bonus city)
    sell_city: str  # Where to sell (may differ from craft city)
    sell_mode: str  # "BM" or "MARKET"
    material_cost_gross: float  # Total ingredient cost (before RRR)
    rrr_used: float  # Resource return rate applied (e.g. 0.33)
    material_cost_net: float  # Cost after RRR = gross * (1 - rrr)
    station_fee: float  # Crafting station fee in silver
    sell_price: int  # Price you sell at (BM buy order or market sell_min)
    revenue_net: float  # After tax: sell_price * (1 - tax) or sell_price if BM
    profit: float  # revenue_net - material_cost_net - station_fee
    profit_pct: float  # profit / material_cost_gross * 100
    daily_volume: int
    data_age_materials: int  # Age of material prices
    data_age_sell: int  # Age of sell price
    quality: int = 1
    use_focus: bool = False
    ingredients: list[dict] = field(default_factory=list)
    safe_limit: int = 1
    roi: float = 0.0
    profit_per_kg: float = 0.0
    score: float = 0.0

@dataclass
class RefiningOpportunity:
    """
    Refining raw materials into refined goods (e.g. Wood -> Planks).
    Profit = revenue - material_cost_after_rrr - station_fee - market_tax
    Requires dedicated RRR logic (36.7% / 53.9%).
    """

    item_id: str
    item_name: str
    refine_city: str
    sell_city: str
    material_cost_gross: float
    rrr_used: float
    material_cost_net: float
    station_fee: float
    sell_price: int
    revenue_net: float
    profit: float
    profit_pct: float
    daily_volume: int
    data_age_materials: int
    data_age_sell: int
    quality: int = 1
    use_focus: bool = False
    focus_cost: float = 0.0
    silver_per_focus: float = 0.0
    safe_limit: int = 1
    roi: float = 0.0
    profit_per_kg: float = 0.0
    buy_city: str = ""
    ingredients: list[dict] = field(default_factory=list)
    score: float = 0.0


@dataclass
class ArbitrageOpportunity:
    """
    Royal city to royal city (or Caerleon) arbitrage.
    Buy cheapest sell_price_min → sell via instant-fill on buy_price_max in dest.
    Only counts EXISTING buy orders (buy_price_max > 0) — not listing and waiting.
    """

    item_id: str
    item_name: str
    buy_city: str
    sell_city: str
    buy_price: int  # sell_price_min at source
    sell_price: int  # buy_price_max at destination (instant fill)
    gross_profit: int  # sell - buy
    tax_paid: float  # 4% of sell_price
    net_profit: float  # gross - tax
    profit_pct: float  # net / buy * 100
    daily_volume: int
    data_age_buy: int
    data_age_sell: int
    is_dangerous_route: bool  # Caerleon destination = dangerous
    quality: int = 1
    safe_limit: int = 1
    roi: float = 0.0
    profit_per_kg: float = 0.0
    score: float = 0.0


@dataclass
class MarketMakingOpportunity:
    """
    Intra-city or Inter-city market making (spread capture).
    Place Buy Order at buy_price_max + 1, wait for fill.
    Place Sell Order at sell_price_min - 1, wait for fill.
    Profit = (sell_price * (1 - tax - setup_fee)) - (buy_price * (1 + setup_fee))
    """
    
    item_id: str
    item_name: str
    source_city: str
    destination_city: str
    buy_price: int  # buy_price_max in source + 1
    sell_price: int  # sell_price_min in destination - 1
    gross_profit: int  # sell - buy
    setup_fees: float  # (buy + sell) * 0.025
    tax_paid: float    # sell * 0.04
    net_profit: float  # gross - setup_fees - tax_paid
    profit_pct: float  # net_profit / total_capital_required * 100
    daily_volume: int
    data_age_buy: int
    data_age_sell: int
    is_dangerous_route: bool
    quality: int = 1
    safe_limit: int = 1
    roi: float = 0.0
    profit_per_kg: float = 0.0
    score: float = 0.0


@dataclass
class QualityInversionOpportunity:
    """
    Quality Mispricing Arbitrage.
    Buy higher quality item (e.g. Q2/Q3/Q4/Q5) listed cheaper than a lower quality item in the same city.
    """
    item_id: str
    item_name: str
    city: str
    buy_quality: int
    buy_quality_name: str
    buy_price: int
    reference_quality: int
    reference_quality_name: str
    reference_price: int
    inversion_type: str  # "sell_undercut" or "buy_order_flip"
    net_profit: float
    profit_pct: float
    data_age_seconds: int
    daily_volume: int
    safe_limit: int = 1
    score: float = 0.0


# ─── The Scanner ─────────────────────────────────────────────────────────────


class OpportunityScanner:
    """
    Unified market scanner. Reads from the prices dict (item_id → city → quality → data).
    Produces ranked lists of BM, crafting, and arbitrage opportunities.

    Price dict format (same as what your DB/collector produces):
    {
        item_id: {
            city: {
                quality: {
                    "sell_price_min": int,
                    "buy_price_max": int,
                    "volume_24h": int,
                    "data_age_seconds": int,
                    "is_black_market": bool,
                    "item_value": float,
                }
            }
        }
    }
    """

    def __init__(
        self,
        min_bm_profit: int = 10_000,
        min_bm_profit_pct: float = 5.0,
        min_craft_profit: int = 5_000,
        min_craft_profit_pct: float = 3.0,
        min_arb_profit: int = 5_000,
        min_arb_profit_pct: float = 5.0,
        min_mm_volume: int = 10,
        min_mm_profit: int = 5_000,
        min_mm_profit_pct: float = 2.0,
        min_roi: float = 2.0,
        use_focus: bool = False,
        premium: bool = None,
        default_trade_volume: int = 1,
        use_slippage: bool = True,
    ):
        self.min_bm_profit = min_bm_profit
        self.min_bm_profit_pct = min_bm_profit_pct
        self.min_craft_profit = min_craft_profit
        self.min_craft_profit_pct = min_craft_profit_pct
        self.min_arb_profit = min_arb_profit
        self.min_arb_profit_pct = min_arb_profit_pct
        self.min_mm_volume = min_mm_volume
        self.min_mm_profit = min_mm_profit
        self.min_mm_profit_pct = min_mm_profit_pct
        self.min_roi = min_roi
        self.use_focus = use_focus
        self._override_premium = premium
        self.setup_fee = SETUP_FEE
        self.default_trade_volume = default_trade_volume
        self.use_slippage = use_slippage
        self.allow_enchant_transport = False

    @property
    def is_premium(self) -> bool:
        if self._override_premium is not None:
            return self._override_premium
        return settings.is_premium

    @property
    def tax(self) -> float:
        return PREMIUM_TAX if self.is_premium else NON_PREMIUM_TAX

    # ── Internal helpers ────────────────────────────────────────────────────

    def _get_price(self, prices: dict, item_id: str, city: str, quality: int = 1) -> dict | None:
        """Safe price lookup with None if missing."""
        return prices.get(item_id, {}).get(city, {}).get(quality)

    def _cheapest_royal_sell(
        self, prices: dict, item_id: str, quality: int = 1
    ) -> tuple[str, int, int, int]:
        """
        Returns (city, sell_price_min, volume, data_age) for the cheapest
        valid sell order across all royal cities.
        Applies cross-city outlier check first.
        """
        city_prices = {}
        for city in ROYAL_CITIES:
            p = self._get_price(prices, item_id, city, quality)
            if p and p.get("sell_price_min", 0) > 0:
                city_prices[city] = p["sell_price_min"]

        if not city_prices:
            return ("", 0, 0, 0)

        # Outlier filter — removes manipulation spikes
        cleaned = cross_city_outlier_check(city_prices)

        best_city, best_price = "", 0
        for city, price in cleaned.items():
            if price <= 0:
                continue
            p = self._get_price(prices, item_id, city, quality)
            if not p:
                continue
            buy_max = p.get("buy_price_max", 0)
            if not is_price_valid(price, buy_max, p.get("volume_24h", 0)):
                continue
            age = p.get("data_age_seconds", 9999)
            if age > MAX_AGE_ROYAL_SECONDS:
                continue
            if best_price == 0 or price < best_price:
                best_city = city
                best_price = price

        if not best_city:
            return ("", 0, 0, 0)

        p = self._get_price(prices, item_id, best_city, quality)
        return (
            best_city,
            best_price,
            p.get("volume_24h", 0),
            p.get("data_age_seconds", 9999),
        )

    def _dynamic_min_margin(self, buy_price: float, is_dangerous: bool, default_min: float) -> float:
        """Dynamic minimum margin curve for high-risk routes."""
        if not is_dangerous:
            return default_min

        LOW_PRICE = 100_000
        HIGH_PRICE = 1_000_000
        MIN_MARGIN = max(default_min, 15.0)
        MAX_MARGIN = max(default_min * 2.5, 40.0)

        if buy_price <= LOW_PRICE:
            return MIN_MARGIN
        if buy_price >= HIGH_PRICE:
            return MAX_MARGIN

        t = (buy_price - LOW_PRICE) / (HIGH_PRICE - LOW_PRICE)
        return MIN_MARGIN + t * (MAX_MARGIN - MIN_MARGIN)

    def _apply_weight_penalty(self, score: float, profit_per_kg: float) -> float:
        """
        Adjust score based on transport efficiency (Silver/kg).
        If profit per kg is very low, the item requires too many mammoth trips, penalizing the score.
        """
        if profit_per_kg <= 0:
            return score * 0.1
            
        if profit_per_kg > 1000:
            return score * 1.1  # Bonus for high value density (e.g. artifacts)
        elif profit_per_kg > 500:
            return score * 1.0  # Neutral
        elif profit_per_kg > 200:
            return score * 0.8  # Mild penalty
        else:
            # Severe penalty for very heavy, low margin items (e.g. raw stone)
            penalty = max(0.1, profit_per_kg / 250.0)
            return score * penalty

    def _score_bm(self, opp: BMOpportunity) -> float:
        """
        Rank BM opportunities.
        Factors: profit, margin, volume, data freshness.
        A player cares most about: absolute profit × how fast it sells × how confident the price is.
        """
        freshness = max(0.1, 1.0 - opp.data_age_bm / MAX_AGE_BM_SECONDS)
        vol_score = min(1.0, opp.daily_volume / 50.0) if opp.daily_volume > 0 else 0.2
        margin_bonus = min(2.0, opp.profit_pct / 20.0)  # 20% margin = 1.0 multiplier
        
        # Capital At Risk Premium (5% expected loss from ganks)
        capital_risk_premium = opp.buy_price * 0.05
        
        score = (opp.effective_profit * freshness * vol_score * margin_bonus) - capital_risk_premium
        score = self._apply_weight_penalty(score, getattr(opp, "profit_per_kg", 0.0))
        return round(max(0.0, score), 2)

    def _score_craft(self, opp: CraftingOpportunity) -> float:
        freshness = max(0.1, 1.0 - opp.data_age_sell / MAX_AGE_CRAFTING_SECONDS)
        vol_score = min(1.0, opp.daily_volume / 30.0) if opp.daily_volume > 0 else 0.2
        score = opp.profit * freshness * vol_score
        
        # Only apply weight penalty if we are transporting it to a different city
        if opp.craft_city != opp.sell_city:
            score = self._apply_weight_penalty(score, getattr(opp, "profit_per_kg", 0.0))
            
        return round(score, 2)

    def _score_arb(self, opp: ArbitrageOpportunity) -> float:
        freshness_buy = max(0.1, 1.0 - opp.data_age_buy / MAX_AGE_ROYAL_SECONDS)
        freshness_sell = max(0.1, 1.0 - opp.data_age_sell / MAX_AGE_ROYAL_SECONDS)
        freshness = min(freshness_buy, freshness_sell)
        vol_score = min(1.0, opp.daily_volume / 30.0) if opp.daily_volume > 0 else 0.2
        danger_penalty = 0.5 if opp.is_dangerous_route else 1.0
        
        capital_risk_premium = opp.buy_price * 0.05 if opp.is_dangerous_route else 0.0
        
        score = (opp.net_profit * freshness * vol_score * danger_penalty) - capital_risk_premium
        score = self._apply_weight_penalty(score, getattr(opp, "profit_per_kg", 0.0))
        return round(max(0.0, score), 2)

    def _score_refining(self, opp: RefiningOpportunity) -> float:
        freshness_mat = max(0.1, 1.0 - opp.data_age_materials / MAX_AGE_ROYAL_SECONDS)
        freshness_sell = max(0.1, 1.0 - opp.data_age_sell / MAX_AGE_ROYAL_SECONDS)
        freshness = min(freshness_mat, freshness_sell)
        vol_score = min(1.0, opp.daily_volume / 100.0) if opp.daily_volume > 0 else 0.2
        
        score = opp.profit * freshness * vol_score
        score = self._apply_weight_penalty(score, getattr(opp, "profit_per_kg", 0.0))
        return round(max(0.0, score), 2)

    def _score_mm(self, opp: MarketMakingOpportunity) -> float:
        freshness_buy = max(0.1, 1.0 - opp.data_age_buy / MAX_AGE_ROYAL_SECONDS)
        freshness_sell = max(0.1, 1.0 - opp.data_age_sell / MAX_AGE_ROYAL_SECONDS)
        freshness = min(freshness_buy, freshness_sell)
        
        # Volume is extremely important for market making to reduce time risk
        vol_score = min(1.0, opp.daily_volume / 500.0) if opp.daily_volume > 0 else 0.1
        
        danger_penalty = 0.5 if opp.is_dangerous_route else 1.0
        capital_risk_premium = opp.buy_price * 0.05 if opp.is_dangerous_route else 0.0
        
        score = (opp.net_profit * freshness * vol_score * danger_penalty) - capital_risk_premium
        score = self._apply_weight_penalty(score, getattr(opp, "profit_per_kg", 0.0))
        return round(max(0.0, score), 2)

    # ── Public scan methods ─────────────────────────────────────────────────

    def scan_enchanting(
        self,
        prices: dict,
        item_names: dict[str, str],
        item_categories: dict[str, str],
    ) -> list[EnchantingOpportunity]:
        """
        Find risk-free Caerleon enchantment flips.
        Buys base item in Caerleon + materials in Caerleon -> Enchants -> Sells to BM.
        """
        results = []
        target_ids = set()
        for item_id in prices:
            if "@" in item_id:
                target_ids.add(item_id)
            else:
                for ench in [1, 2, 3]:
                    target_ids.add(f"{item_id}@{ench}")

        for item_id in target_ids:
            reqs = self._get_enchant_requirements(item_id)
            if not reqs:
                continue
            base_item_id, material_id, material_qty = reqs

            for quality in [1, 2, 3, 4, 5]:
                # Get BM buy order
                bm_data = self._get_price(prices, item_id, BM_CITY, quality)
                if not bm_data:
                    continue
                bm_price = bm_data.get("buy_price_max", 0)
                bm_volume = bm_data.get("volume_24h", 0)
                bm_age = bm_data.get("data_age_seconds", 9999)

                if bm_price <= 0 or not is_bm_price_valid(bm_price) or bm_age > MAX_AGE_BM_SECONDS:
                    continue

                # Get Base item price in Caerleon (check all qualities 1..quality to find cheapest available base item)
                base_price, base_age, base_vol = 0, 9999, 0
                base_city = CAERLEON
                for q in range(1, quality + 1):
                    base_data = self._get_price(prices, base_item_id, CAERLEON, q)
                    if base_data and base_data.get("sell_price_min", 0) > 0 and base_data.get("data_age_seconds", 9999) <= MAX_AGE_ROYAL_SECONDS:
                        cand_sp = base_data["sell_price_min"]
                        cand_bm = base_data.get("buy_price_max", 0)
                        if is_price_valid(cand_sp, cand_bm, item_id=base_item_id):
                            if base_price == 0 or cand_sp < base_price:
                                base_price = cand_sp
                                base_age = base_data.get("data_age_seconds", 9999)
                                base_vol = base_data.get("volume_24h", 0)

                if base_price <= 0:
                    for q in range(1, quality + 1):
                        r_city, r_price, r_vol, r_age = self._cheapest_royal_sell(prices, base_item_id, q)
                        if r_price > 0 and (base_price == 0 or r_price < base_price):
                            base_city, base_price, base_vol, base_age = r_city, r_price, r_vol, r_age

                if base_price <= 0 or base_age > MAX_AGE_ROYAL_SECONDS:
                    continue

                if not getattr(self, "allow_enchant_transport", False) and base_city != CAERLEON:
                    continue

                # Get Material price in Caerleon (with fallback to cheapest royal city if Caerleon mat un-scanned)
                mat_data = self._get_price(prices, material_id, CAERLEON, 1) # Mats are always Q1
                mat_price, mat_age, mat_vol = 0, 9999, 0
                mat_city = CAERLEON
                if mat_data and mat_data.get("sell_price_min", 0) > 0 and mat_data.get("data_age_seconds", 9999) <= MAX_AGE_ROYAL_SECONDS:
                    cand_sp = mat_data["sell_price_min"]
                    cand_bm = mat_data.get("buy_price_max", 0)
                    if is_price_valid(cand_sp, cand_bm, item_id=material_id):
                        mat_price = cand_sp
                        mat_age = mat_data.get("data_age_seconds", 9999)
                        mat_vol = mat_data.get("volume_24h", 0)

                if mat_price <= 0:
                    mat_city, mat_price, mat_vol, mat_age = self._cheapest_royal_sell(prices, material_id, 1)

                if mat_price <= 0 or mat_age > MAX_AGE_ROYAL_SECONDS:
                    continue

                # Apply slippage model for bulk material purchase quantity
                effective_mat_unit = calculate_effective_price(mat_price, material_qty, mat_vol, is_buy=True)
                total_mat_cost = effective_mat_unit * material_qty
                
                # Apply slippage model for base item and target sell
                trade_vol = self.default_trade_volume if self.use_slippage else 1
                effective_base = calculate_effective_price(base_price, trade_vol, base_vol, is_buy=True)
                effective_bm = calculate_effective_price(bm_price, trade_vol, bm_volume, is_buy=False)
                
                # Revenue after market tax (selling on Black Market pays market tax)
                revenue_net = effective_bm * (1.0 - self.tax)
                total_cost = effective_base + total_mat_cost
                net_profit = revenue_net - total_cost

                # Higher margin required if base item needs transport from another city
                is_dangerous = (base_city != CAERLEON)
                min_profit_silver = max(self.min_bm_profit, 1000) if self.min_bm_profit > 0 else 1000
                if net_profit < min_profit_silver:
                    continue

                profit_pct = (net_profit / total_cost) * 100
                min_pct = self._dynamic_min_margin(base_price, is_dangerous=is_dangerous, default_min=1.0) if is_dangerous else 1.0
                if profit_pct < min_pct:
                    continue

                safe_limit = calculate_safe_trade_limit(bm_volume, max_slippage_pct=0.03)

                opp = EnchantingOpportunity(
                    target_item_id=item_id,
                    target_item_name=item_names.get(item_id, item_id),
                    base_item_id=base_item_id,
                    base_price=effective_base,
                    material_id=material_id,
                    material_qty=material_qty,
                    material_price=effective_mat_unit,
                    bm_buy_price=effective_bm,
                    net_profit=round(net_profit, 0),
                    profit_pct=round(profit_pct, 2),
                    total_cost=total_cost,
                    safe_limit=safe_limit,
                    roi=round((net_profit / total_cost) * 100, 2),
                    quality=quality,
                    data_age_base=base_age,
                    data_age_material=mat_age,
                    data_age_bm=bm_age,
                    base_city=base_city,
                )
                
                # Score based on profit, age, volume
                freshness = max(0.1, 1.0 - (bm_age + base_age) / (MAX_AGE_BM_SECONDS + MAX_AGE_ROYAL_SECONDS))
                vol_score = min(1.0, bm_volume / 50.0) if bm_volume > 0 else 0.2
                opp.score = round(net_profit * freshness * vol_score, 2)
                
                results.append(opp)

        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def _get_enchant_requirements(self, target_item_id: str) -> tuple[str, str, int] | None:
        """
        Returns (required_base_item_id, material_id, material_qty)
        """
        if "@" not in target_item_id:
            return None

        base_item_id, enchant_str = target_item_id.rsplit("@", 1)
        try:
            enchant = int(enchant_str)
        except ValueError:
            return None

        # Non-enchantable at Artifact Foundry in Albion Online: Off-hands, Bags, Satchels, Capes, Royal items
        base_upper = base_item_id.upper()
        if any(x in base_upper for x in [
            "BAG", "SATC", "INSIGHT", "CAPE", "_OFF", "OFF_", "OFFHAND", "SHIELD", "TORCH",
            "BOOK", "TOME", "HORN", "ORB", "TOTEM", "TALISMAN", "LAMP", "SKULL",
            "CENSER", "MUISAK", "TAPROOT", "ROYAL"
        ]):
            return None

        tier = 4
        if base_item_id.startswith("T"):
            try:
                tier = int(base_item_id[1])
            except ValueError:
                pass

        if enchant == 1:
            mat_type = "RUNE"
            required_base = base_item_id
        elif enchant == 2:
            mat_type = "SOUL"
            required_base = f"{base_item_id}@1"
        elif enchant == 3:
            mat_type = "RELIC"
            required_base = f"{base_item_id}@2"
        else:
            return None

        material_id = f"T{tier}_{mat_type}"
        qty = self._get_enchant_qty(base_item_id)
        return required_base, material_id, qty

    @staticmethod
    def _get_enchant_qty(item_id: str) -> int:
        """
        Calculate required runes/souls/relics/shards per level for enchantable equipment in Albion Online:
        - 1H Mainhand Weapons: 288 per level (12 primary resources * 24)
        - 2H Weapons & Dual Weapons: 384 per level (16 primary resources * 24)
        - Chest Armors: 192 per level (8 primary resources * 24)
        - Headgear & Footwear: 96 per level (4 primary resources * 24)
        (Note: Off-hands, Bags, Satchels, and Capes cannot be enchanted at the Artifact Foundry).
        """
        item_id_upper = item_id.upper()

        # 1. 1-Handed Mainhand Weapons -> 288
        if any(x in item_id_upper for x in ["MAIN_", "MAINHAND", "1H_"]):
            return 288

        # 2. 2-Handed Weapons / Dual Weapons -> 384
        if any(x in item_id_upper for x in [
            "2H_", "_2H", "BOW", "WARBOW", "LONGBOW", "CROSSBOW", "STAFF", "DOUBLE",
            "CLAYMORE", "DUAL", "HALBERD", "SCYTHE", "POLEHAMMER", "FLAIL", "GLAIVE",
            "TRIDENT", "HARPOON", "KATAR", "CLAW", "KNUCKLES", "SHAPESHIFTER", "QUARTERSTAFF"
        ]):
            return 384

        # 3. Chest Armors -> 192
        if any(x in item_id_upper for x in ["ARMOR", "ROBE", "JACKET", "GARB"]):
            return 192

        # 4. Headgear & Footwear -> 96
        return 96

        # Default fallback for equipment
        return 192

    def scan_black_market(
        self,
        prices: dict,
        item_names: dict[str, str],
        recipes: dict,
        item_categories: dict[str, str],
        item_values: dict[str, float] = None,
        item_weights: dict[str, float] = None,
    ) -> list[BMOpportunity]:
        """
        Find items where BM buy order > cheapest royal city sell order.
        Also checks: can we CRAFT it cheaper than buying from royal city?
        """
        results = []

        for item_id in prices:
            for quality in [1, 2, 3, 4, 5]:
                # Get BM buy order
                bm_data = self._get_price(prices, item_id, BM_CITY, quality)
                if not bm_data:
                    bm_data = self._get_price(prices, item_id, CAERLEON, quality)
                if not bm_data:
                    continue

                bm_price = bm_data.get("buy_price_max", 0)
                bm_age = bm_data.get("data_age_seconds", 9999)

                item_val = item_values.get(item_id, 0.0) if item_values else 0.0
                if not is_bm_price_valid(bm_price, item_val):
                    continue
                if bm_age > MAX_AGE_BM_SECONDS:
                    continue

                # Get Caerleon buy price (0 risk transport to BM) or fallback to cheapest royal city
                # Fulfill with equal OR higher quality (cheapest available)
                best_buy_city, best_buy_price, best_volume, best_buy_age, best_buy_quality = "", 0, 0, 9999, quality
                
                for q in range(quality, 6):
                    buy_data = self._get_price(prices, item_id, CAERLEON, q)
                    if buy_data and buy_data.get("sell_price_min", 0) > 0 and buy_data.get("data_age_seconds", 9999) <= MAX_AGE_ROYAL_SECONDS:
                        cand_sp = buy_data["sell_price_min"]
                        cand_bm = buy_data.get("buy_price_max", 0)
                        if is_price_valid(cand_sp, cand_bm, item_id=item_id):
                            city = CAERLEON
                            price = cand_sp
                            age = buy_data.get("data_age_seconds", 9999)
                            vol = buy_data.get("volume_24h", 0)
                        else:
                            city, price, vol, age = self._cheapest_royal_sell(prices, item_id, q)
                    else:
                        city, price, vol, age = self._cheapest_royal_sell(prices, item_id, q)
                        
                    if price > 0 and age <= MAX_AGE_ROYAL_SECONDS:
                        if best_buy_price == 0 or price < best_buy_price:
                            best_buy_city = city
                            best_buy_price = price
                            best_volume = vol
                            best_buy_age = age
                            best_buy_quality = q

                buy_city, buy_price, volume, buy_age = best_buy_city, best_buy_price, best_volume, best_buy_age
                
                if buy_price <= 0 or buy_age > MAX_AGE_ROYAL_SECONDS:
                    continue

                # Apply slippage model
                trade_vol = self.default_trade_volume if self.use_slippage else 1
                effective_buy_price = calculate_effective_price(buy_price, trade_vol, volume, is_buy=True)
                effective_bm_price = calculate_effective_price(bm_price, trade_vol, volume, is_buy=False)
                safe_limit = calculate_safe_trade_limit(volume, max_slippage_pct=0.03)

                # Spread check: We do not allow BM prices > 8x royal buy price (unrealistic spread manipulation)
                if effective_bm_price > effective_buy_price * 8.0:
                    continue

                # Revenue after market tax on BM sale
                revenue_net = effective_bm_price * (1.0 - self.tax)
                net_profit = revenue_net - effective_buy_price
                if net_profit <= 0:
                    continue

                profit_pct = (net_profit / effective_buy_price) * 100
                
                # Caerleon -> BM is 0 risk, so we accept much lower margins.
                is_dangerous = (buy_city != CAERLEON)
                min_profit_silver = max(self.min_bm_profit, 1000) if self.min_bm_profit > 0 else 1000
                if net_profit < min_profit_silver:
                    continue
                    
                dynamic_min_pct = self._dynamic_min_margin(buy_price, is_dangerous=is_dangerous, default_min=self.min_bm_profit_pct)
                if not is_dangerous:
                    # Very low margin threshold for 0-risk inside-Caerleon flips
                    dynamic_min_pct = min(1.0, dynamic_min_pct)
                    
                if profit_pct < dynamic_min_pct:
                    continue

                # Check if item can be crafted cheaper
                can_craft = item_id in recipes
                craft_cost = 0.0
                craft_city = ""
                if can_craft:
                    craft_cost, craft_city = self._estimate_craft_cost(
                        item_id, prices, recipes, item_categories, quality
                    )

                weight = item_weights.get(item_id, 0.0) if item_weights else 0.0

                opp = BMOpportunity(
                    item_id=item_id,
                    item_name=item_names.get(item_id, item_id),
                    buy_city=buy_city,
                    buy_price=effective_buy_price,
                    bm_buy_price=effective_bm_price,
                    net_profit=net_profit,
                    profit_pct=round(profit_pct, 2),
                    daily_volume=volume,
                    data_age_buy=buy_age,
                    data_age_bm=bm_age,
                    quality=quality,
                    buy_quality=best_buy_quality,
                    can_be_crafted=can_craft and craft_cost > 0 and craft_cost < effective_buy_price,
                    craft_cost=craft_cost,
                    craft_city=craft_city,
                    safe_limit=safe_limit,
                )
                opp.roi = round(opp.effective_profit / opp.effective_cost * 100, 2) if opp.effective_cost > 0 else 0.0
                min_roi_required = self.min_roi if is_dangerous else 1.0
                if opp.roi < min_roi_required:
                    continue
                opp.profit_per_kg = round(opp.effective_profit / weight, 2) if weight > 0 else opp.effective_profit
                opp.score = self._score_bm(opp)
                results.append(opp)

        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def scan_crafting(
        self,
        prices: dict,
        item_names: dict[str, str],
        recipes: dict,
        item_categories: dict[str, str],
        item_values: dict[str, float],
        item_weights: dict[str, float] = None,
    ) -> list[CraftingOpportunity]:
        """
        For each craftable item, find the best city to craft it in and the best
        city/venue (BM or market) to sell it at. Compares net revenue vs net cost.
        """
        results = []

        for item_id, recipe in recipes.items():
            for quality in [1]:  # Crafting always produces quality 1 at base
                category = item_categories.get(item_id, "")

                # Find best craft city (highest RRR for this item's category)
                best_rrr = -1.0
                best_craft_city = "Caerleon"  # fallback (18% only)
                for city in ROYAL_CITIES:
                    r = rrr(city, category, self.use_focus)
                    if r > best_rrr:
                        best_rrr = r
                        best_craft_city = city

                # Calculate material cost (gross and net after RRR)
                material_cost_gross, ingredient_details, mat_age = self._calc_material_cost(
                    item_id, recipe, prices, best_craft_city, quality=1
                )
                if material_cost_gross <= 0:
                    continue

                # RRR only applies to returnable resources (Planks, Cloth, etc.)
                material_cost_net = 0.0
                for ing in ingredient_details:
                    if ing.get("is_returnable"):
                        material_cost_net += ing["line_cost"] * (1.0 - best_rrr)
                    else:
                        material_cost_net += ing["line_cost"]

                # Station fee: nutrition cost = item_val * 0.1125, silver fee = (nutrition * station_tax) / 100
                item_val = item_values.get(item_id, 0.0)
                station_tax = getattr(settings, "station_tax_per_100_nutrition", 500.0)
                station_fee = calculate_station_fee(item_val, station_tax)

                total_cost = material_cost_net + station_fee

                # Evaluate all sell destinations
                best_opp = None

                # — Sell to Black Market (pays market tax)
                bm_data = self._get_price(prices, item_id, BM_CITY, 1)
                if bm_data and best_craft_city == "Caerleon":
                    bm_price = bm_data.get("buy_price_max", 0)
                    bm_age = bm_data.get("data_age_seconds", 9999)
                    bm_vol = bm_data.get("volume_24h", 1)
                    if bm_price > 0 and bm_age <= MAX_AGE_BM_SECONDS and bm_vol >= MIN_BM_VOLUME:
                        trade_vol = self.default_trade_volume if self.use_slippage else 1
                        effective_bm_price = calculate_effective_price(bm_price, trade_vol, bm_vol, is_buy=False)
                        safe_limit = calculate_safe_trade_limit(bm_vol, max_slippage_pct=0.03)

                        revenue_net = effective_bm_price * (1.0 - self.tax)
                        profit = revenue_net - total_cost
                        pct = (profit / material_cost_gross * 100) if material_cost_gross > 0 else 0
                        roi = (profit / total_cost * 100) if total_cost > 0 else 0
                        if profit >= self.min_craft_profit and pct >= self.min_craft_profit_pct and roi >= self.min_roi:
                            opp = CraftingOpportunity(
                                item_id=item_id,
                                item_name=item_names.get(item_id, item_id),
                                craft_city=best_craft_city,
                                sell_city=CAERLEON,
                                sell_mode="BM",
                                material_cost_gross=round(material_cost_gross, 0),
                                rrr_used=best_rrr,
                                material_cost_net=round(material_cost_net, 0),
                                station_fee=round(station_fee, 0),
                                sell_price=effective_bm_price,
                                revenue_net=round(revenue_net, 0),
                                profit=round(profit, 0),
                                profit_pct=round(pct, 2),
                                daily_volume=bm_vol,
                                data_age_materials=mat_age,
                                data_age_sell=bm_age,
                                use_focus=self.use_focus,
                                ingredients=ingredient_details,
                                safe_limit=safe_limit,
                            )
                            opp.roi = roi
                            opp.score = self._score_craft(opp)
                            best_opp = opp

                # — Sell on royal market (best price across all cities)
                # — Sell on royal market (best price across all cities)
                craft_sell_map = {}
                for sell_city in ALL_SELL_CITIES:
                    if sell_city == "Caerleon" and best_craft_city != "Caerleon":
                        continue
                    p = self._get_price(prices, item_id, sell_city, quality)
                    if p:
                        sp = p.get("sell_price_min", 0)
                        if sp > 0:
                            craft_sell_map[sell_city] = sp

                cleaned_craft_sell = cross_city_outlier_check(craft_sell_map)

                for sell_city in ALL_SELL_CITIES:
                    if sell_city == "Caerleon" and best_craft_city != "Caerleon":
                        continue
                    if cleaned_craft_sell.get(sell_city, 0) == 0:
                        continue  # Outlier / manipulated sell price in this city

                    sell_data = self._get_price(prices, item_id, sell_city, quality)
                    if not sell_data:
                        continue
                    sell_price = sell_data.get("sell_price_min", 0)
                    sell_age = sell_data.get("data_age_seconds", 9999)
                    sell_vol = sell_data.get("volume_24h", 0)
                    buy_max = sell_data.get("buy_price_max", 0)

                    if sell_price <= 0 or sell_vol < MIN_ROYAL_VOLUME:
                        continue
                    if sell_age > MAX_AGE_ROYAL_SECONDS:
                        continue
                    if not is_price_valid(sell_price, buy_max):
                        continue

                    # Revenue = sell_price - setup_fee - tax
                    # We list at sell_price_min (undercutting existing orders)
                    trade_vol = self.default_trade_volume if self.use_slippage else 1
                    effective_sell_price = calculate_effective_price(sell_price, trade_vol, sell_vol, is_buy=False)
                    safe_limit = calculate_safe_trade_limit(sell_vol, max_slippage_pct=0.03)

                    revenue_net = effective_sell_price * (1.0 - self.tax - SETUP_FEE)
                    profit = revenue_net - total_cost
                    pct = (profit / material_cost_gross * 100) if material_cost_gross > 0 else 0
                    roi = (profit / total_cost * 100) if total_cost > 0 else 0

                    # Anti-manipulation: Royal market crafting margins > 100% are player bait traps
                    if pct > 100.0:
                        continue

                    if profit < self.min_craft_profit:
                        continue
                    if pct < self.min_craft_profit_pct:
                        continue
                    if roi < self.min_roi:
                        continue

                    opp = CraftingOpportunity(
                        item_id=item_id,
                        item_name=item_names.get(item_id, item_id),
                        craft_city=best_craft_city,
                        sell_city=sell_city,
                        sell_mode="MARKET",
                        material_cost_gross=round(material_cost_gross, 0),
                        rrr_used=best_rrr,
                        material_cost_net=round(material_cost_net, 0),
                        station_fee=round(station_fee, 0),
                        sell_price=effective_sell_price,
                        revenue_net=round(revenue_net, 0),
                        profit=round(profit, 0),
                        profit_pct=round(pct, 2),
                        daily_volume=sell_vol,
                        data_age_materials=mat_age,
                        data_age_sell=sell_age,
                        use_focus=self.use_focus,
                        ingredients=ingredient_details,
                        safe_limit=safe_limit,
                    )
                    opp.roi = roi
                    opp.score = self._score_craft(opp)

                    if best_opp is None or opp.score > best_opp.score:
                        best_opp = opp

                if best_opp:
                    results.append(best_opp)

                # ── Caerleon Craft → BM / Caerleon Market (zero-transport) ──
                # Even though Caerleon has no city crafting bonus (base 18% RRR
                # vs 33%+ in a bonus Royal city), the ZERO transport cost and
                # ZERO travel risk to the Black Market can make these profitable.
                # Evaluate independently so both Royal and Caerleon opps surface.
                if best_craft_city != CAERLEON:
                    caerleon_rrr = rrr(CAERLEON, category, self.use_focus)
                    cae_cost_gross, cae_ingredients, cae_mat_age = (
                        self._calc_material_cost(
                            item_id, recipe, prices, CAERLEON, quality=1
                        )
                    )
                    if cae_cost_gross > 0:
                        cae_cost_net = 0.0
                        for ing in cae_ingredients:
                            if ing.get("is_returnable"):
                                cae_cost_net += ing["line_cost"] * (
                                    1.0 - caerleon_rrr
                                )
                            else:
                                cae_cost_net += ing["line_cost"]

                        cae_station_fee = (
                            calculate_station_fee(item_val, settings.station_tax_per_100_nutrition)
                            if item_val > 0
                            else 0.0
                        )
                        cae_total_cost = cae_cost_net + cae_station_fee
                        best_cae_opp = None

                        # — Sell to Black Market (0 tax — BM is in Caerleon)
                        cae_bm_data = self._get_price(
                            prices, item_id, BM_CITY, 1
                        )
                        if cae_bm_data:
                            cae_bm_price = cae_bm_data.get("buy_price_max", 0)
                            cae_bm_age = cae_bm_data.get(
                                "data_age_seconds", 9999
                            )
                            cae_bm_vol = cae_bm_data.get("volume_24h", 1)
                            if (
                                cae_bm_price > 0
                                and cae_bm_age <= MAX_AGE_BM_SECONDS
                                and cae_bm_vol >= MIN_BM_VOLUME
                            ):
                                profit = cae_bm_price - cae_total_cost
                                pct = (
                                    (profit / cae_cost_gross * 100)
                                    if cae_cost_gross > 0
                                    else 0
                                )
                                roi = (profit / cae_total_cost * 100) if cae_total_cost > 0 else 0
                                if (
                                    profit >= self.min_craft_profit
                                    and pct >= self.min_craft_profit_pct
                                    and roi >= self.min_roi
                                ):
                                    opp = CraftingOpportunity(
                                        item_id=item_id,
                                        item_name=item_names.get(
                                            item_id, item_id
                                        ),
                                        craft_city=CAERLEON,
                                        sell_city=CAERLEON,
                                        sell_mode="BM",
                                        material_cost_gross=round(
                                            cae_cost_gross, 0
                                        ),
                                        rrr_used=caerleon_rrr,
                                        material_cost_net=round(
                                            cae_cost_net, 0
                                        ),
                                        station_fee=round(cae_station_fee, 0),
                                        sell_price=cae_bm_price,
                                        revenue_net=float(cae_bm_price),
                                        profit=round(profit, 0),
                                        profit_pct=round(pct, 2),
                                        daily_volume=cae_bm_vol,
                                        data_age_materials=cae_mat_age,
                                        data_age_sell=cae_bm_age,
                                        use_focus=self.use_focus,
                                        ingredients=cae_ingredients,
                                    )
                                    opp.roi = roi
                                    opp.score = self._score_craft(opp)
                                    best_cae_opp = opp

                        # — Sell on Caerleon market (regular market, with tax)
                        cae_sell_data = self._get_price(
                            prices, item_id, CAERLEON, quality
                        )
                        if cae_sell_data:
                            cae_sp = cae_sell_data.get("sell_price_min", 0)
                            cae_sell_age = cae_sell_data.get(
                                "data_age_seconds", 9999
                            )
                            cae_sell_vol = cae_sell_data.get("volume_24h", 0)
                            cae_buy_max = cae_sell_data.get(
                                "buy_price_max", 0
                            )
                            if (
                                cae_sp > 0
                                and cae_sell_age <= MAX_AGE_ROYAL_SECONDS
                                and cae_sell_vol >= MIN_ROYAL_VOLUME
                                and is_price_valid(cae_sp, cae_buy_max)
                            ):
                                revenue_net = cae_sp * (
                                    1.0 - self.tax - SETUP_FEE
                                )
                                profit = revenue_net - cae_total_cost
                                pct = (
                                    (profit / cae_cost_gross * 100)
                                    if cae_cost_gross > 0
                                    else 0
                                )
                                roi = (profit / cae_total_cost * 100) if cae_total_cost > 0 else 0
                                if (
                                    profit >= self.min_craft_profit
                                    and pct >= self.min_craft_profit_pct
                                    and roi >= self.min_roi
                                ):
                                    opp = CraftingOpportunity(
                                        item_id=item_id,
                                        item_name=item_names.get(
                                            item_id, item_id
                                        ),
                                        craft_city=CAERLEON,
                                        sell_city=CAERLEON,
                                        sell_mode="MARKET",
                                        material_cost_gross=round(
                                            cae_cost_gross, 0
                                        ),
                                        rrr_used=caerleon_rrr,
                                        material_cost_net=round(
                                            cae_cost_net, 0
                                        ),
                                        station_fee=round(cae_station_fee, 0),
                                        sell_price=cae_sp,
                                        revenue_net=round(revenue_net, 0),
                                        profit=round(profit, 0),
                                        profit_pct=round(pct, 2),
                                        daily_volume=cae_sell_vol,
                                        data_age_materials=cae_mat_age,
                                        data_age_sell=cae_sell_age,
                                        use_focus=self.use_focus,
                                        ingredients=cae_ingredients,
                                    )
                                    opp.roi = roi
                                    weight = item_weights.get(item_id, 0.0) if item_weights else 0.0
                                    opp.profit_per_kg = round(profit / weight, 2) if weight > 0 else profit
                                    opp.score = self._score_craft(opp)
                                    if (
                                        best_cae_opp is None
                                        or opp.score > best_cae_opp.score
                                    ):
                                        best_cae_opp = opp

                        if best_cae_opp:
                            results.append(best_cae_opp)

        results.sort(key=lambda x: x.score, reverse=True)
        return results
    def scan_refining(
        self,
        prices: dict,
        item_names: dict,
        recipes: dict,
        categories: dict,
        values: dict,
        weights: dict,
    ) -> list[RefiningOpportunity]:
        """
        Scans for refining opportunities (Raw Material -> Refined Material).
        Uses specialized RRR (36.7% / 53.9%).
        """
        from app.core.market_utils import calculate_rrr, get_refining_category

        results = []
        
        # We only care about items that are crafted (have recipes) and are refining subcategories
        refining_subs = ['planks', 'metalbar', 'leather', 'cloth', 'stoneblock']
        
        for item_id, recipe in recipes.items():
            # Check if this item is a refined resource
            refine_cat = get_refining_category(item_id)
            if not refine_cat:
                continue
                
            # For each quality (usually quality 1 for resources, but keeping loop for consistency)
            for quality in [1, 2, 3, 4, 5]:
                # 1. Calculate ingredient costs in the cheapest royal city
                ingredients = recipe.get("ingredients", [])
                if not ingredients:
                    continue
                    
                total_material_gross = 0.0
                mat_age = 0
                mat_data_found = True
                buy_city = ""
                ingredients_detail = []
                
                for ing in ingredients:
                    ing_id = ing["item_id"]
                    ing_qty = ing["quantity"]
                    
                    src_city, src_price, src_vol, src_age = self._cheapest_royal_sell(prices, ing_id, quality)
                    if src_price <= 0 or src_age > 7200 or src_vol < MIN_ROYAL_VOLUME: # MAX_AGE_ROYAL_SECONDS
                        mat_data_found = False
                        break
                        
                    total_material_gross += src_price * ing_qty
                    mat_age = max(mat_age, src_age)
                    if not buy_city:
                        buy_city = src_city

                    ing_name = item_names.get(ing_id, ing_id)
                    ingredients_detail.append({
                        "item_id": ing_id,
                        "name": ing_name,
                        "quantity": ing_qty,
                        "unit_price": src_price,
                        "buy_city": src_city,
                        "is_returnable": True,
                    })
                    
                if not mat_data_found:
                    continue
                    
                # 2. Find the best city to refine in (max RRR)
                best_refine_city = ""
                best_rrr = 0.0
                
                # ALL_SELL_CITIES except Caerleon
                royal_cities = ["Martlock", "Bridgewatch", "Thetford", "Lymhurst", "Fort Sterling"]
                for city in royal_cities:
                    city_rrr = calculate_rrr(city, refine_cat, 1, self.use_focus)
                    if city_rrr > best_rrr:
                        best_rrr = city_rrr
                        best_refine_city = city
                        
                if not best_refine_city:
                    continue
                    
                # 3. Calculate net costs
                material_cost_net = total_material_gross * (1.0 - best_rrr)
                item_value = values.get(item_id, 0.0)
                station_tax = getattr(settings, "station_tax_per_100_nutrition", 500.0)
                station_fee = calculate_station_fee(item_value, station_tax)
                total_cost = material_cost_net + station_fee
                
                # 4. Find the best market to sell the refined material
                best_sell_city = ""
                best_sell_price = 0
                best_sell_vol = 0
                best_sell_age = 0
                
                # Exclude Caerleon since transporting from a Royal City to Caerleon is risky
                all_sell = ["Martlock", "Bridgewatch", "Thetford", "Lymhurst", "Fort Sterling"]
                sell_price_map = {}
                for sell_city in all_sell:
                    p = self._get_price(prices, item_id, sell_city, quality)
                    if p:
                        sp = p.get("sell_price_min", 0)
                        if sp > 0:
                            sell_price_map[sell_city] = sp

                cleaned_sell = cross_city_outlier_check(sell_price_map)

                for sell_city in all_sell:
                    if cleaned_sell.get(sell_city, 0) == 0:
                        continue  # Outlier / manipulated sell price in this city

                    p = self._get_price(prices, item_id, sell_city, quality)
                    if not p:
                        continue
                        
                    sell_sp = p.get("sell_price_min", 0)
                    sell_age = p.get("data_age_seconds", 9999)
                    sell_vol = p.get("volume_24h", 0)
                    
                    if sell_sp > best_sell_price and sell_age <= 7200 and sell_vol >= MIN_ROYAL_VOLUME:
                        best_sell_price = sell_sp
                        best_sell_city = sell_city
                        best_sell_vol = sell_vol
                        best_sell_age = sell_age
                        
                if best_sell_price <= 0:
                    continue
                    
                # 5. Apply slippage and calculate profit
                trade_vol = self.default_trade_volume if self.use_slippage else 1
                effective_sell_price = calculate_effective_price(best_sell_price, trade_vol, best_sell_vol, is_buy=False)
                safe_limit = calculate_safe_trade_limit(best_sell_vol, max_slippage_pct=0.03)

                revenue_net = effective_sell_price * (1.0 - self.tax - self.setup_fee)
                profit = revenue_net - total_cost
                profit_pct = (profit / total_material_gross * 100) if total_material_gross > 0 else 0
                roi = (profit / total_cost * 100) if total_cost > 0 else 0
                
                # Anti-manipulation: Royal market refining margins > 100% are player bait traps
                if profit_pct > 100.0:
                    continue

                if profit >= self.min_craft_profit and profit_pct >= self.min_craft_profit_pct and roi >= self.min_roi:
                    focus_cost = 0.0
                    silver_per_focus = 0.0
                    
                    weight = weights.get(item_id, 0.0)
                    profit_per_kg = profit / weight if weight > 0 else 0.0

                    opp = RefiningOpportunity(
                        item_id=item_id,
                        item_name=item_names.get(item_id, item_id),
                        refine_city=best_refine_city,
                        sell_city=best_sell_city,
                        material_cost_gross=round(total_material_gross, 0),
                        rrr_used=best_rrr,
                        material_cost_net=round(material_cost_net, 0),
                        station_fee=round(station_fee, 0),
                        sell_price=effective_sell_price,
                        revenue_net=round(revenue_net, 0),
                        profit=round(profit, 0),
                        profit_pct=round(profit_pct, 2),
                        daily_volume=best_sell_vol,
                        data_age_materials=mat_age,
                        data_age_sell=best_sell_age,
                        quality=quality,
                        use_focus=self.use_focus,
                        focus_cost=focus_cost,
                        silver_per_focus=silver_per_focus,
                        roi=round(roi, 4),
                        profit_per_kg=round(profit_per_kg, 2),
                        safe_limit=safe_limit,
                        buy_city=buy_city,
                        ingredients=ingredients_detail,
                    )
                    opp.score = self._score_refining(opp)
                    results.append(opp)
                    
        # Sort by score desc
        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def scan_arbitrage(
        self,
        prices: dict,
        item_names: dict[str, str],
        item_weights: dict[str, float] = None,
    ) -> list[ArbitrageOpportunity]:
        """
        Find items where buy_price_max at destination > sell_price_min at source.
        Only uses EXISTING BUY ORDERS (buy_price_max) as the destination price —
        this means instant fill, no waiting. A player would NEVER count on
        listing at sell_price_min in another city and waiting days for a fill.
        """
        results = []
        seen = set()  # Dedup: same item+route

        # Diagnostics: count how many items pass each filter stage
        _diag = {
            "total_pairs": 0,
            "no_sources": 0,
            "no_dest_data": 0,
            "dest_no_buy": 0,
            "dest_too_old": 0,
            "low_profit": 0,
            "low_pct": 0,
            "outlier_filtered": 0,
            "src_age_filtered": 0,
            "src_invalid_price": 0,
            "passed": 0,
        }

        for item_id in prices:
            for quality in [1, 2, 3, 4, 5]:
                # Get all valid source prices (where we buy)
                sources = []
                for city in ROYAL_CITIES:
                    p = self._get_price(prices, item_id, city, quality)
                    if not p:
                        continue
                    sell_min = p.get("sell_price_min", 0)
                    buy_max = p.get("buy_price_max", 0)
                    age = p.get("data_age_seconds", 9999)
                    if sell_min <= 0 or age > MAX_AGE_ROYAL_SECONDS:
                        _diag["src_age_filtered"] += 1
                        continue
                    if not is_price_valid(sell_min, buy_max, item_id=item_id):
                        _diag["src_invalid_price"] += 1
                        continue
                    sources.append((city, sell_min, p.get("volume_24h", 0), age))

                if not sources:
                    _diag["no_sources"] += 1
                    continue

                # Outlier check on sources and destinations
                src_price_map = {c: p for c, p, _, _ in sources}
                cleaned_src = cross_city_outlier_check(src_price_map)

                dest_price_map = {}
                for city in ROYAL_CITIES:
                    d = self._get_price(prices, item_id, city, quality)
                    if d:
                        bm = d.get("buy_price_max", 0)
                        if bm > 0:
                            dest_price_map[city] = bm
                cleaned_dest = cross_city_outlier_check(dest_price_map)

                # For each valid source, look for a destination with a buy order
                for src_city, src_sell, src_vol, src_age in sources:
                    if cleaned_src.get(src_city, 0) == 0:
                        _diag["outlier_filtered"] += 1
                        continue  # Outlier filtered

                    for dest_city in ROYAL_CITIES:  # Caerleon excluded — same risk as BM
                        if dest_city == src_city:
                            continue

                        if cleaned_dest.get(dest_city, 0) == 0:
                            _diag["outlier_filtered"] += 1
                            continue  # Destination outlier / manipulation filtered

                        _diag["total_pairs"] += 1

                        dest_data = self._get_price(prices, item_id, dest_city, quality)
                        if not dest_data:
                            _diag["no_dest_data"] += 1
                            continue

                        dest_buy_max = dest_data.get("buy_price_max", 0)
                        dest_age = dest_data.get("data_age_seconds", 9999)
                        dest_vol = dest_data.get("volume_24h", 0)

                        if dest_buy_max <= 0 or dest_vol < MIN_ROYAL_VOLUME:
                            _diag["dest_no_buy"] += 1
                            continue
                        if dest_age > MAX_AGE_ROYAL_SECONDS:
                            _diag["dest_too_old"] += 1
                            continue

                        # Apply slippage model
                        daily_vol = min(src_vol, dest_vol) if dest_vol > 0 else src_vol
                        trade_vol = self.default_trade_volume if self.use_slippage else 1
                        effective_src_sell = calculate_effective_price(src_sell, trade_vol, daily_vol, is_buy=True)
                        effective_dest_buy_max = calculate_effective_price(dest_buy_max, trade_vol, daily_vol, is_buy=False)
                        safe_limit = calculate_safe_trade_limit(daily_vol, max_slippage_pct=0.03)

                        # Net profit: you pay effective_src_sell, you receive effective_dest_buy_max - 4% tax
                        # (No setup fee because you're filling an existing buy order)
                        revenue = effective_dest_buy_max * (1.0 - self.tax)
                        net_profit = revenue - effective_src_sell
                        pct = (net_profit / effective_src_sell * 100) if effective_src_sell > 0 else 0
                        roi = (net_profit / effective_src_sell * 100) if effective_src_sell > 0 else 0

                        if net_profit < self.min_arb_profit:
                            _diag["low_profit"] += 1
                            continue
                            
                        # Anti-manipulation: Royal-to-Royal Arbitrage margins over 100% are player bait traps
                        if pct > 100.0:
                            _diag["outlier_filtered"] += 1
                            continue

                        is_dangerous = dest_city in DANGEROUS_DESTINATIONS
                        dynamic_min_pct = self._dynamic_min_margin(src_sell, is_dangerous=is_dangerous, default_min=self.min_arb_profit_pct)
                        
                        if pct < dynamic_min_pct or roi < self.min_roi:
                            _diag["low_pct"] += 1
                            continue

                        key = f"{item_id}:{quality}:{src_city}:{dest_city}"
                        if key in seen:
                            continue
                        seen.add(key)

                        _diag["passed"] += 1
                        opp = ArbitrageOpportunity(
                            item_id=item_id,
                            item_name=item_names.get(item_id, item_id),
                            buy_city=src_city,
                            sell_city=dest_city,
                            buy_price=src_sell,
                            sell_price=dest_buy_max,
                            gross_profit=effective_dest_buy_max - effective_src_sell,
                            tax_paid=round(effective_dest_buy_max * self.tax, 0),
                            net_profit=round(net_profit, 0),
                            profit_pct=round(pct, 2),
                            daily_volume=daily_vol,
                            data_age_buy=src_age,
                            data_age_sell=dest_age,
                            is_dangerous_route=dest_city in DANGEROUS_DESTINATIONS,
                            quality=quality,
                            safe_limit=safe_limit,
                        )
                        opp.roi = round(roi, 2)
                        weight = item_weights.get(item_id, 0.0) if item_weights else 0.0
                        opp.profit_per_kg = round(net_profit / weight, 2) if weight > 0 else net_profit
                        opp.score = self._score_arb(opp)
                        results.append(opp)

        # Log filter diagnostics
        import logging

        _log = logging.getLogger("app.core.opportunity_engine")
        _log.info(f"[ARB DIAG] Filter pipeline: {_diag}")

        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def scan_market_making(
        self, prices: dict, item_names: dict, item_categories: dict, item_weights: dict = None
    ) -> list[MarketMakingOpportunity]:
        """
        Scan for intra-city and inter-city spread captures (Market Making).
        Place buy order at buy_price_max + 1 in source city.
        Place sell order at sell_price_min - 1 in destination city.
        """
        results = []
        _diag = {"total": 0, "no_data": 0, "low_vol": 0, "low_profit": 0, "low_pct": 0, "passed": 0}

        # User baseline requirement — volume floor set to 0 to prevent dropping snapshot data
        min_volume = 0

        for item_id, city_data in prices.items():
            valid_cities = [c for c in city_data.keys() if c in ROYAL_CITIES or c == CAERLEON]
            
            for source_city in valid_cities:
                for dest_city in valid_cities:
                    for quality in [1, 2, 3, 4, 5]:
                        _diag["total"] += 1
                        
                        source_p = self._get_price(prices, item_id, source_city, quality)
                        dest_p = self._get_price(prices, item_id, dest_city, quality)
                        
                        if not source_p or not dest_p:
                            _diag["no_data"] += 1
                            continue

                        bm = source_p.get("buy_price_max", 0)
                        sp = dest_p.get("sell_price_min", 0)
                        
                        vol_source = source_p.get("volume_24h", 0)
                        vol_dest = dest_p.get("volume_24h", 0)
                        vol = min(vol_source, vol_dest) if source_city != dest_city else vol_source
                        
                        age_buy = source_p.get("data_age_seconds", 9999)
                        age_sell = dest_p.get("data_age_seconds", 9999)
                        
                        if sp <= 0 or bm <= 0 or age_buy > MAX_AGE_ROYAL_SECONDS or age_sell > MAX_AGE_ROYAL_SECONDS:
                            _diag["no_data"] += 1
                            continue
                            
                        # Spread capture logic
                        # We outbid the highest buy order by 1 silver
                        effective_buy_price = bm + 1
                        # We undercut the lowest sell order by 1 silver
                        effective_sell_price = sp - 1
                        
                        if effective_buy_price >= effective_sell_price:
                            _diag["no_data"] += 1
                            continue
                            
                        if effective_buy_price <= MIN_PRICE or effective_sell_price > ABSOLUTE_MAX_PRICE:
                            _diag["no_data"] += 1
                            continue

                        buy_setup_fee = effective_buy_price * self.setup_fee
                        sell_setup_fee = effective_sell_price * self.setup_fee
                        tax_paid = effective_sell_price * self.tax
                        
                        total_fees = buy_setup_fee + sell_setup_fee + tax_paid
                        gross_profit = effective_sell_price - effective_buy_price
                        net_profit = gross_profit - total_fees
                        
                        # Capital required is what you pay to buy it + listing fees
                        capital_required = effective_buy_price + buy_setup_fee + sell_setup_fee
                        pct = (net_profit / capital_required * 100) if capital_required > 0 else 0.0
                        roi = (net_profit / capital_required * 100) if capital_required > 0 else 0.0

                        if net_profit < 1000:
                            _diag["low_profit"] += 1
                            continue

                        if pct < 1.0 or roi < 1.0:
                            _diag["low_pct"] += 1
                            continue

                        is_dangerous = dest_city == CAERLEON and source_city != CAERLEON

                        _diag["passed"] += 1
                        opp = MarketMakingOpportunity(
                            item_id=item_id,
                            item_name=item_names.get(item_id, item_id),
                            source_city=source_city,
                            destination_city=dest_city,
                            buy_price=effective_buy_price,
                            sell_price=effective_sell_price,
                            gross_profit=gross_profit,
                            setup_fees=round(buy_setup_fee + sell_setup_fee, 0),
                            tax_paid=round(tax_paid, 0),
                            net_profit=round(net_profit, 0),
                            profit_pct=round(pct, 2),
                            daily_volume=vol,
                            data_age_buy=age_buy,
                            data_age_sell=age_sell,
                            is_dangerous_route=is_dangerous,
                            quality=quality,
                            safe_limit=1,
                        )
                        opp.roi = round(pct, 2)
                        
                        if item_weights:
                            weight = item_weights.get(item_id, 0.0)
                            if weight > 0:
                                opp.profit_per_kg = round(net_profit / weight, 2)
                        
                        opp.score = self._score_mm(opp)
                        results.append(opp)

        import logging
        _log = logging.getLogger("app.core.opportunity_engine")
        _log.info(f"[MM DIAG] Filter pipeline: {_diag}")

        results.sort(key=lambda x: x.score, reverse=True)
        return results

    # ── Private helpers ─────────────────────────────────────────────────────

    def _estimate_craft_cost(
        self,
        item_id: str,
        prices: dict,
        recipes: dict,
        item_categories: dict[str, str],
        quality: int = 1,
    ) -> tuple[float, str]:
        """
        Quick craft cost estimate for BM opportunity display.
        Returns (total_cost_after_rrr, best_craft_city).
        """
        recipe = recipes.get(item_id)
        if not recipe:
            return (0.0, "")

        category = item_categories.get(item_id, "")
        best_rrr = -1.0
        best_craft_city = "Caerleon"
        for city in ROYAL_CITIES:
            r = rrr(city, category, self.use_focus)
            if r > best_rrr:
                best_rrr = r
                best_craft_city = city

        gross_cost, ingredients, _ = self._calc_material_cost(
            item_id, recipe, prices, best_craft_city, quality=1
        )
        if gross_cost <= 0:
            return (0.0, "")

        # RRR only applies to returnable resources (Planks, Cloth, etc.)
        net_cost = 0.0
        for ing in ingredients:
            if ing.get("is_returnable"):
                net_cost += ing["line_cost"] * (1.0 - best_rrr)
            else:
                net_cost += ing["line_cost"]
        return (round(net_cost, 0), best_craft_city)

    def _calc_material_cost(
        self,
        item_id: str,
        recipe: dict,
        prices: dict,
        craft_city: str,
        quality: int = 1,
    ) -> tuple[float, list[dict], int]:
        """
        Sum up ingredient costs. Checks cheapest sell_price_min across royal cities
        for each ingredient. Returns (total_gross_cost, ingredient_list, max_age).
        """
        total = 0.0
        ingredients = []
        max_age = 0

        for ing in recipe.get("ingredients", []):
            ing_id = ing["item_id"]
            qty = ing["quantity"]

            best_price = 0
            best_city = ""
            best_age = 9999

            # Try to find price in craft_city first
            p_local = self._get_price(prices, ing_id, craft_city, 1)
            if (
                p_local
                and p_local.get("sell_price_min", 0) > 0
                and p_local.get("data_age_seconds", 9999) <= MAX_AGE_CRAFTING_SECONDS
            ):
                sp = p_local["sell_price_min"]
                bm = p_local.get("buy_price_max", 0)
                if is_price_valid(sp, bm):
                    best_price = sp
                    best_city = craft_city
                    best_age = p_local.get("data_age_seconds", 9999)

            # Fallback to cheapest place to buy this ingredient if not found locally
            if best_price <= 0:
                if craft_city != CAERLEON:
                    for city in ROYAL_CITIES + [CAERLEON]:
                        p = self._get_price(prices, ing_id, city, 1)
                        if not p:
                            continue
                        sp = p.get("sell_price_min", 0)
                        bm = p.get("buy_price_max", 0)
                        age = p.get("data_age_seconds", 9999)
                        if sp <= 0 or age > MAX_AGE_CRAFTING_SECONDS:
                            continue
                        if not is_price_valid(sp, bm):
                            continue
                        if best_price == 0 or sp < best_price:
                            best_price = sp
                            best_city = city
                            best_age = age

            if best_price <= 0:
                return (0.0, [], 0)  # Can't price this ingredient → skip

            line_cost = best_price * qty
            total += line_cost
            max_age = max(max_age, best_age)

            # Check if returnable (RRR applies)
            is_returnable = False
            if "ARTIFACT" not in ing_id:
                if any(r in ing_id for r in ["PLANKS", "CLOTH", "LEATHER", "BAR", "METALBAR", "WOOD", "ORE", "HIDE", "FIBER", "ROCK", "STONE", "BLOCK"]):
                    is_returnable = True

            ingredients.append(
                {
                    "item_id": ing_id,
                    "quantity": qty,
                    "unit_price": best_price,
                    "buy_city": best_city,
                    "line_cost": round(line_cost, 0),
                    "is_returnable": is_returnable,
                }
            )

        return (total, ingredients, max_age)

    def scan_quality_inversions(
        self,
        prices: dict,
        item_names: dict[str, str],
    ) -> list[QualityInversionOpportunity]:
        """
        Scans for quality mispricings within each city.
        Returns list of QualityInversionOpportunity objects.
        """
        from app.features.quality_arbitrage import detect_quality_inversion

        results = []
        for item_id, city_map in prices.items():
            item_name = item_names.get(item_id, item_id)
            for city, quality_map in city_map.items():
                if len(quality_map) < 2:
                    continue
                invs = detect_quality_inversion(
                    quality_map,
                    item_id=item_id,
                    city=city,
                    item_name=item_name,
                    min_profit=self.min_arb_profit,
                    min_margin=self.min_arb_profit_pct,
                )
                for inv in invs:
                    vol = inv["daily_volume"]
                    limit = calculate_safe_trade_limit(vol, default_limit=1)
                    opp = QualityInversionOpportunity(
                        item_id=inv["item_id"],
                        item_name=inv["item_name"],
                        city=inv["city"],
                        buy_quality=inv["buy_quality"],
                        buy_quality_name=inv["buy_quality_name"],
                        buy_price=inv["buy_price"],
                        reference_quality=inv["reference_quality"],
                        reference_quality_name=inv["reference_quality_name"],
                        reference_price=inv["reference_price"],
                        inversion_type=inv["inversion_type"],
                        net_profit=inv["net_profit"],
                        profit_pct=inv["profit_pct"],
                        data_age_seconds=inv["data_age_seconds"],
                        daily_volume=vol,
                        safe_limit=limit,
                        score=round(inv["net_profit"] * (vol / 50.0 + 0.1), 2),
                    )
                    results.append(opp)

        results.sort(key=lambda x: x.score, reverse=True)
        return results
