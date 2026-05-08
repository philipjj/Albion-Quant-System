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

# ─── Market Constants ────────────────────────────────────────────────────────

PREMIUM_TAX = 0.04          # 4% market sales tax (premium player)
NON_PREMIUM_TAX = 0.08      # 8%
SETUP_FEE = 0.025           # 2.5% listing fee (only paid when YOU list, not when buying)
BM_TAX = 0.0                # Black Market: zero fees to seller

# Station fee varies 1–15% of item value. Use conservative default.
DEFAULT_STATION_FEE_PCT = 0.03   # 3% of item_value from DB, not sell price

# RRR (Resource Return Rate) — how much material comes back after crafting
# RRR = LPB / (1 + LPB)  where LPB = Local Production Bonus
BASE_LPB = 0.18             # 18% base — all cities, all items
CITY_BONUS_LPB = 0.33       # +33% for matching city+category (refining speciality)
CRAFT_BONUS_LPB = 0.15      # +15% for matching city+category (crafting speciality)
FOCUS_BONUS_LPB = 0.59      # +59% when using Focus

def rrr(city: str, category: str, use_focus: bool = False) -> float:
    """
    Returns Resource Return Rate as a fraction (0.0 – 0.99).
    A return of 0.33 means 33% of materials come back after crafting.
    """
    lpb = BASE_LPB

    city_data = CITY_CRAFT_BONUSES.get(city, {})
    if category.lower() in [c.lower() for c in city_data.get("refining", [])]:
        lpb += CITY_BONUS_LPB
    elif category.lower() in [c.lower() for c in city_data.get("crafting", [])]:
        lpb += CRAFT_BONUS_LPB

    if use_focus:
        lpb += FOCUS_BONUS_LPB

    rate = lpb / (1.0 + lpb)
    return round(min(0.99, rate), 4)


# Each royal city has crafting specialities — items crafted here get better RRR
CITY_CRAFT_BONUSES: Dict[str, Dict[str, List[str]]] = {
    "Martlock": {
        "refining": ["hide"],
        "crafting": ["axe", "quarterstaff", "frost_staff", "plate_shoes", "offhand"],
    },
    "Bridgewatch": {
        "refining": ["rock"],
        "crafting": ["crossbow", "dagger", "cursed_staff", "plate_helmet", "leather_shoes"],
    },
    "Thetford": {
        "refining": ["ore"],
        "crafting": ["mace", "nature_staff", "fire_staff", "leather_armor", "cloth_headgear"],
    },
    "Lymhurst": {
        "refining": ["fiber"],
        "crafting": ["sword", "bow", "arcane_staff", "leather_helmet", "cloth_armor"],
    },
    "Fort Sterling": {
        "refining": ["wood"],
        "crafting": ["spear", "holy_staff", "plate_armor", "cloth_shoes", "offhand"],
    },
    "Caerleon": {},   # No crafting bonus; used for BM only
}

ROYAL_CITIES = ["Bridgewatch", "Martlock", "Lymhurst", "Fort Sterling", "Thetford"]
BM_CITY = "Black Market"
CAERLEON = "Caerleon"
ALL_SELL_CITIES = ROYAL_CITIES + [CAERLEON]

# Routes that pass through dangerous zones (Caerleon ring roads)
DANGEROUS_DESTINATIONS = {CAERLEON, BM_CITY}

# ─── Data Age Limits ─────────────────────────────────────────────────────────

MAX_AGE_BM_SECONDS = 3_600       # 1 hour — BM orders fill fast
MAX_AGE_ROYAL_SECONDS = 7_200    # 2 hours — royal city orders last longer
MAX_AGE_CRAFTING_SECONDS = 14_400  # 4 hours — acceptable for material cost calc

# ─── Outlier / Manipulation Detection ────────────────────────────────────────

MAX_SELL_TO_BUY_RATIO = 8.0    # If sell_min > buy_max * 8 → single-item manipulation
MIN_PRICE = 100                 # Ignore anything below 100 silver (test orders)
ABSOLUTE_MAX_PRICE = 500_000_000  # 500M cap — anything higher is a troll order

def is_price_valid(sell_min: int, buy_max: int, daily_volume: int = 0) -> bool:
    """
    Returns True if the price pair looks like a real market, not manipulation.
    A player would mentally sanity-check: does this price make sense?
    """
    if sell_min <= MIN_PRICE:
        return False
    if sell_min > ABSOLUTE_MAX_PRICE:
        return False
    if buy_max > 0:
        # Spread check: sell can't be more than 8x buy — that's a troll listing
        if sell_min > buy_max * MAX_SELL_TO_BUY_RATIO:
            return False
    return True

def is_bm_price_valid(bm_buy_price: int, royal_sell_price: int) -> bool:
    """BM price should always be ABOVE royal sell price (otherwise why run?)"""
    if bm_buy_price <= MIN_PRICE:
        return False
    if bm_buy_price > ABSOLUTE_MAX_PRICE:
        return False
    # BM pays more than market — otherwise no one would bother transporting
    # We don't reject if BM < royal sell (we just won't have profit), scanner handles that
    return True

def cross_city_outlier_check(prices_by_city: Dict[str, int]) -> Dict[str, int]:
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
            cleaned[city] = 0   # Zeroed out = skipped by scanner
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
    buy_city: str               # Where to buy the item (cheapest royal city)
    buy_price: int              # sell_price_min in buy_city (what you pay)
    bm_buy_price: int           # Black Market buy order (what BM pays you)
    net_profit: int             # bm_buy_price - buy_price (no fees on BM side)
    profit_pct: float           # net_profit / buy_price * 100
    daily_volume: int           # Volume in buy city (how many units trade daily)
    data_age_buy: int           # Age of buy city price in seconds
    data_age_bm: int            # Age of BM price in seconds
    quality: int = 1
    can_be_crafted: bool = False  # If True, crafting route also shown
    craft_cost: float = 0.0     # If can_be_crafted, what it costs to craft
    craft_city: str = ""        # Best city to craft in
    score: float = 0.0          # Ranking score

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
class CraftingOpportunity:
    """
    Craft item using materials, sell on market or to BM.
    Profit = revenue - material_cost_after_rrr - station_fee - market_tax
    """
    item_id: str
    item_name: str
    craft_city: str             # Where to craft (best RRR bonus city)
    sell_city: str              # Where to sell (may differ from craft city)
    sell_mode: str              # "BM" or "MARKET"
    material_cost_gross: float  # Total ingredient cost (before RRR)
    rrr_used: float             # Resource return rate applied (e.g. 0.33)
    material_cost_net: float    # Cost after RRR = gross * (1 - rrr)
    station_fee: float          # Crafting station fee in silver
    sell_price: int             # Price you sell at (BM buy order or market sell_min)
    revenue_net: float          # After tax: sell_price * (1 - tax) or sell_price if BM
    profit: float               # revenue_net - material_cost_net - station_fee
    profit_pct: float           # profit / material_cost_gross * 100
    daily_volume: int
    data_age_materials: int     # Age of material prices
    data_age_sell: int          # Age of sell price
    quality: int = 1
    use_focus: bool = False
    ingredients: List[Dict] = field(default_factory=list)
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
    buy_price: int              # sell_price_min at source
    sell_price: int             # buy_price_max at destination (instant fill)
    gross_profit: int           # sell - buy
    tax_paid: float             # 4% of sell_price
    net_profit: float           # gross - tax
    profit_pct: float           # net / buy * 100
    daily_volume: int
    data_age_buy: int
    data_age_sell: int
    is_dangerous_route: bool    # Caerleon destination = dangerous
    quality: int = 1
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
        min_bm_profit: int = 10_000,        # Minimum raw profit for BM flip (silver)
        min_bm_profit_pct: float = 5.0,     # Minimum margin % for BM flip
        min_craft_profit: int = 5_000,       # Minimum craft profit
        min_craft_profit_pct: float = 3.0,  # Minimum craft margin %
        min_arb_profit: int = 5_000,         # Minimum arbitrage profit
        min_arb_profit_pct: float = 5.0,    # Minimum arbitrage margin %
        use_focus: bool = False,             # Whether player uses focus when crafting
        premium: bool = True,               # Premium player (4% tax vs 8%)
    ):
        self.min_bm_profit = min_bm_profit
        self.min_bm_profit_pct = min_bm_profit_pct
        self.min_craft_profit = min_craft_profit
        self.min_craft_profit_pct = min_craft_profit_pct
        self.min_arb_profit = min_arb_profit
        self.min_arb_profit_pct = min_arb_profit_pct
        self.use_focus = use_focus
        self.tax = PREMIUM_TAX if premium else NON_PREMIUM_TAX

    # ── Internal helpers ────────────────────────────────────────────────────

    def _get_price(
        self, prices: Dict, item_id: str, city: str, quality: int = 1
    ) -> Optional[Dict]:
        """Safe price lookup with None if missing."""
        return prices.get(item_id, {}).get(city, {}).get(quality)

    def _cheapest_royal_sell(
        self, prices: Dict, item_id: str, quality: int = 1
    ) -> Tuple[str, int, int, int]:
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

    def _score_bm(self, opp: BMOpportunity) -> float:
        """
        Rank BM opportunities.
        Factors: profit, margin, volume, data freshness.
        A player cares most about: absolute profit × how fast it sells × how confident the price is.
        """
        freshness = max(0.1, 1.0 - opp.data_age_bm / MAX_AGE_BM_SECONDS)
        vol_score = min(1.0, opp.daily_volume / 50.0) if opp.daily_volume > 0 else 0.2
        margin_bonus = min(2.0, opp.profit_pct / 20.0)  # 20% margin = 1.0 multiplier
        return round(opp.effective_profit * freshness * vol_score * margin_bonus, 2)

    def _score_craft(self, opp: CraftingOpportunity) -> float:
        freshness = max(0.1, 1.0 - opp.data_age_sell / MAX_AGE_CRAFTING_SECONDS)
        vol_score = min(1.0, opp.daily_volume / 30.0) if opp.daily_volume > 0 else 0.2
        return round(opp.profit * freshness * vol_score, 2)

    def _score_arb(self, opp: ArbitrageOpportunity) -> float:
        freshness_buy = max(0.1, 1.0 - opp.data_age_buy / MAX_AGE_ROYAL_SECONDS)
        freshness_sell = max(0.1, 1.0 - opp.data_age_sell / MAX_AGE_ROYAL_SECONDS)
        freshness = min(freshness_buy, freshness_sell)
        vol_score = min(1.0, opp.daily_volume / 30.0) if opp.daily_volume > 0 else 0.2
        danger_penalty = 0.5 if opp.is_dangerous_route else 1.0
        return round(opp.net_profit * freshness * vol_score * danger_penalty, 2)

    # ── Public scan methods ─────────────────────────────────────────────────

    def scan_black_market(
        self,
        prices: Dict,
        item_names: Dict[str, str],
        recipes: Dict,
        item_categories: Dict[str, str],
    ) -> List[BMOpportunity]:
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

                if not is_bm_price_valid(bm_price, 0):
                    continue
                if bm_age > MAX_AGE_BM_SECONDS:
                    continue

                # Get cheapest royal city to buy from
                buy_city, buy_price, volume, buy_age = self._cheapest_royal_sell(
                    prices, item_id, quality
                )
                if not buy_city or buy_price <= 0:
                    continue

                net_profit = bm_price - buy_price
                if net_profit <= 0:
                    continue

                profit_pct = (net_profit / buy_price) * 100
                if net_profit < self.min_bm_profit:
                    continue
                if profit_pct < self.min_bm_profit_pct:
                    continue

                # Check if item can be crafted cheaper
                can_craft = item_id in recipes
                craft_cost = 0.0
                craft_city = ""
                if can_craft:
                    craft_cost, craft_city = self._estimate_craft_cost(
                        item_id, prices, recipes, item_categories, quality
                    )

                opp = BMOpportunity(
                    item_id=item_id,
                    item_name=item_names.get(item_id, item_id),
                    buy_city=buy_city,
                    buy_price=buy_price,
                    bm_buy_price=bm_price,
                    net_profit=net_profit,
                    profit_pct=round(profit_pct, 2),
                    daily_volume=volume,
                    data_age_buy=buy_age,
                    data_age_bm=bm_age,
                    quality=quality,
                    can_be_crafted=can_craft and craft_cost > 0,
                    craft_cost=craft_cost,
                    craft_city=craft_city,
                )
                opp.score = self._score_bm(opp)
                results.append(opp)

        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def scan_crafting(
        self,
        prices: Dict,
        item_names: Dict[str, str],
        recipes: Dict,
        item_categories: Dict[str, str],
        item_values: Dict[str, float],
    ) -> List[CraftingOpportunity]:
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

                material_cost_net = material_cost_gross * (1.0 - best_rrr)

                # Station fee: based on item_value from DB
                item_val = item_values.get(item_id, 0.0)
                station_fee = item_val * DEFAULT_STATION_FEE_PCT if item_val > 0 else 0.0

                total_cost = material_cost_net + station_fee

                # Evaluate all sell destinations
                best_opp = None

                # — Sell to Black Market (0 tax, no setup fee)
                bm_data = self._get_price(prices, item_id, BM_CITY, 1)
                if bm_data:
                    bm_price = bm_data.get("buy_price_max", 0)
                    bm_age = bm_data.get("data_age_seconds", 9999)
                    if bm_price > 0 and bm_age <= MAX_AGE_BM_SECONDS:
                        profit = bm_price - total_cost
                        pct = (profit / material_cost_gross * 100) if material_cost_gross > 0 else 0
                        if profit >= self.min_craft_profit and pct >= self.min_craft_profit_pct:
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
                                sell_price=bm_price,
                                revenue_net=float(bm_price),   # no tax
                                profit=round(profit, 0),
                                profit_pct=round(pct, 2),
                                daily_volume=bm_data.get("volume_24h", 1),
                                data_age_materials=mat_age,
                                data_age_sell=bm_age,
                                use_focus=self.use_focus,
                                ingredients=ingredient_details,
                            )
                            opp.score = self._score_craft(opp)
                            best_opp = opp

                # — Sell on royal market (best price across all cities)
                for sell_city in ALL_SELL_CITIES:
                    sell_data = self._get_price(prices, item_id, sell_city, quality)
                    if not sell_data:
                        continue
                    sell_price = sell_data.get("sell_price_min", 0)
                    sell_age = sell_data.get("data_age_seconds", 9999)
                    sell_vol = sell_data.get("volume_24h", 0)
                    buy_max = sell_data.get("buy_price_max", 0)

                    if sell_price <= 0:
                        continue
                    if sell_age > MAX_AGE_ROYAL_SECONDS:
                        continue
                    if not is_price_valid(sell_price, buy_max):
                        continue

                    # Revenue = sell_price - setup_fee - tax
                    # We list at sell_price_min (undercutting existing orders)
                    revenue_net = sell_price * (1.0 - self.tax - SETUP_FEE)
                    profit = revenue_net - total_cost
                    pct = (profit / material_cost_gross * 100) if material_cost_gross > 0 else 0

                    if profit < self.min_craft_profit:
                        continue
                    if pct < self.min_craft_profit_pct:
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
                        sell_price=sell_price,
                        revenue_net=round(revenue_net, 0),
                        profit=round(profit, 0),
                        profit_pct=round(pct, 2),
                        daily_volume=sell_vol,
                        data_age_materials=mat_age,
                        data_age_sell=sell_age,
                        use_focus=self.use_focus,
                        ingredients=ingredient_details,
                    )
                    opp.score = self._score_craft(opp)

                    if best_opp is None or opp.score > best_opp.score:
                        best_opp = opp

                if best_opp:
                    results.append(best_opp)

        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def scan_arbitrage(
        self,
        prices: Dict,
        item_names: Dict[str, str],
    ) -> List[ArbitrageOpportunity]:
        """
        Find items where buy_price_max at destination > sell_price_min at source.
        Only uses EXISTING BUY ORDERS (buy_price_max) as the destination price —
        this means instant fill, no waiting. A player would NEVER count on
        listing at sell_price_min in another city and waiting days for a fill.
        """
        results = []
        seen = set()   # Dedup: same item+route

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
                        continue
                    if not is_price_valid(sell_min, buy_max):
                        continue
                    sources.append((city, sell_min, p.get("volume_24h", 0), age))

                if not sources:
                    continue

                # Outlier check on sources
                src_price_map = {c: p for c, p, _, _ in sources}
                cleaned_src = cross_city_outlier_check(src_price_map)

                # For each valid source, look for a destination with a buy order
                for src_city, src_sell, src_vol, src_age in sources:
                    if cleaned_src.get(src_city, 0) == 0:
                        continue  # Outlier filtered

                    for dest_city in ROYAL_CITIES + [CAERLEON]:
                        if dest_city == src_city:
                            continue

                        dest_data = self._get_price(prices, item_id, dest_city, quality)
                        if not dest_data:
                            continue

                        dest_buy_max = dest_data.get("buy_price_max", 0)
                        dest_age = dest_data.get("data_age_seconds", 9999)
                        dest_vol = dest_data.get("volume_24h", 0)

                        if dest_buy_max <= 0:
                            continue
                        if dest_age > MAX_AGE_ROYAL_SECONDS:
                            continue

                        # Net profit: you pay src_sell, you receive dest_buy_max - 4% tax
                        # (No setup fee because you're filling an existing buy order)
                        revenue = dest_buy_max * (1.0 - self.tax)
                        net_profit = revenue - src_sell
                        pct = (net_profit / src_sell * 100) if src_sell > 0 else 0

                        if net_profit < self.min_arb_profit:
                            continue
                        if pct < self.min_arb_profit_pct:
                            continue

                        key = f"{item_id}:{quality}:{src_city}:{dest_city}"
                        if key in seen:
                            continue
                        seen.add(key)

                        opp = ArbitrageOpportunity(
                            item_id=item_id,
                            item_name=item_names.get(item_id, item_id),
                            buy_city=src_city,
                            sell_city=dest_city,
                            buy_price=src_sell,
                            sell_price=dest_buy_max,
                            gross_profit=dest_buy_max - src_sell,
                            tax_paid=round(dest_buy_max * self.tax, 0),
                            net_profit=round(net_profit, 0),
                            profit_pct=round(pct, 2),
                            daily_volume=min(src_vol, dest_vol) if dest_vol > 0 else src_vol,
                            data_age_buy=src_age,
                            data_age_sell=dest_age,
                            is_dangerous_route=dest_city in DANGEROUS_DESTINATIONS,
                            quality=quality,
                        )
                        opp.score = self._score_arb(opp)
                        results.append(opp)

        results.sort(key=lambda x: x.score, reverse=True)
        return results

    # ── Private helpers ─────────────────────────────────────────────────────

    def _estimate_craft_cost(
        self,
        item_id: str,
        prices: Dict,
        recipes: Dict,
        item_categories: Dict[str, str],
        quality: int = 1,
    ) -> Tuple[float, str]:
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

        gross_cost, _, _ = self._calc_material_cost(
            item_id, recipe, prices, best_craft_city, quality=1
        )
        if gross_cost <= 0:
            return (0.0, "")

        net_cost = gross_cost * (1.0 - best_rrr)
        return (round(net_cost, 0), best_craft_city)

    def _calc_material_cost(
        self,
        item_id: str,
        recipe: Dict,
        prices: Dict,
        craft_city: str,
        quality: int = 1,
    ) -> Tuple[float, List[Dict], int]:
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

            # Try to find cheapest place to buy this ingredient
            best_price = 0
            best_city = ""
            best_age = 9999

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
                return (0.0, [], 0)   # Can't price this ingredient → skip

            line_cost = best_price * qty
            total += line_cost
            max_age = max(max_age, best_age)
            ingredients.append({
                "item_id": ing_id,
                "quantity": qty,
                "unit_price": best_price,
                "buy_city": best_city,
                "line_cost": round(line_cost, 0),
            })

        return (total, ingredients, max_age)
