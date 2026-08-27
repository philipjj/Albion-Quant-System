"""
AQS Opportunity Engine — Redesigned from Player Perspective
============================================================

Three opportunity types, modeled exactly as a player would think:

1. BLACK MARKET (BM) FLIP
   Buy cheapest sell order in any royal city → instant-sell to BM buy order in Caerleon.
   BM charges standard marketplace tax (4%/8%), but NO setup fee.
   Net profit = bm_buy_price - cheapest_royal_sell_price
   Risk = travel through red/black zones to Caerleon.

2. CRAFTING → SELL (Royal market OR Black Market)
   Profit = revenue - material_cost_after_rrr - station_fee - market_tax
   Material cost is AFTER resource return rate (RRR).
   City crafting bonus: 33% RRR for matching category, 18% elsewhere.
   With Focus: +59% to production bonus → higher RRR.
   Revenue target is either BM buy order (tax, no setup fee) or best Royal market sell order (4% tax premium).

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
  4. data_age_seconds < tier-based age limit (per-item progressive ladder)
  5. If sell_price_min * daily_volume > 0 → prefer; lone single-item outliers
     are suppressed by requiring buy_price_max as sanity anchor.
  6. Cross-city sanity: if sell_price_min in city A > 3x sell_price_min in city B
     for same item, flag as potential manipulation and use median instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import settings
from app.core import state
from app.core.constants import (
    CITY_CRAFTING_BONUSES,
    calculate_station_fee,
    ROYAL_SAFE_CITIES,
    ALL_MARKET_CITIES,
    ROYAL_CITIES,
)

from app.execution.slippage import calculate_safe_trade_limit, calculate_effective_price

# ─── Market Constants ────────────────────────────────────────────────────────

import math

def calculate_time_decay(age_seconds: float, half_life_hours: float = 6.0) -> float:
    """
    Computes smooth exponential decay factor:
    age = 0s -> 1.0
    age = half_life -> 0.5
    age = 2 * half_life -> 0.25
    Never produces an artificial hard cliff.
    """
    if age_seconds <= 0:
        return 1.0
    half_life_seconds = max(1.0, half_life_hours * 3600.0)
    return math.exp(-0.693147 * (age_seconds / half_life_seconds))

PREMIUM_TAX = 0.04  # 4% market sales tax (premium player)
NON_PREMIUM_TAX = 0.08  # 8%
SETUP_FEE = 0.025  # 2.5% listing fee (only paid when YOU list, not when buying)

# Tier-based freshness & multi-leg synchronization
from app.core.freshness import (
    get_max_material_age_seconds,
    get_tier_based_half_life_hours,
    get_max_allowed_leg_desync_seconds,
    calculate_leg_sync_score,
    calculate_route_travel_buffer,
    _extract_tier_enchant,
)


def get_max_allowed_bm_age_seconds(item_id: str, bm_price: float) -> int:
    """
    Calculates realistic Black Market buy order lifespan based on capital barrier to entry and item tier.
    - Low-tier items (T4.0-T5.1, < 80k): 2.5 to 4 hours
    - Mid-tier items (T5.2-T6.2, 80k - 500k): 4 to 8 hours
    - High-tier items (T7.0-T8.2, 500k - 5M): 8 to 12 hours
    - Whale / Artifact items (> 5M - 35M+, T8.3-T8.4): 24 to 72 hours
    """
    upper = str(item_id).upper()

    # 1. Whale / Ultra-High Value (>15M - 35M+, T8.4, T8.3, T7.4) -> Up to 72 hours
    is_tier_8_4 = "@4" in upper or "LEVEL4" in upper or (upper.startswith("T8_") and ("@3" in upper or "@4" in upper))
    if bm_price >= 20_000_000 or (is_tier_8_4 and bm_price >= 10_000_000):
        return 259_200    # 72 hours (3 days)
    if bm_price >= 8_000_000 or is_tier_8_4:
        return 129_600    # 36 hours (1.5 days)
    if bm_price >= 4_000_000 or "@3" in upper:
        return 86_400     # 24 hours (1 day)

    # 2. High Capital Tiers (T8.0-T8.2, T7.2-T7.3, 1M - 4M silver)
    if bm_price >= 1_500_000 or upper.startswith("T8_"):
        return 43_200     # 12.0 hours
    elif bm_price >= 500_000 or (upper.startswith("T7_") and ("@1" in upper or "@2" in upper)):
        return 28_800     # 8.0 hours
    elif bm_price >= 150_000 or upper.startswith("T6_"):
        return 18_000     # 5.0 hours

    # 3. Low-Mid Capital Tiers (T4.0-T5.2, < 150k silver)
    if bm_price >= 60_000 or upper.startswith("T5_"):
        return 14_400     # 4.0 hours
    else:
        return 9_000      # 2.5 hours

RAW_REFINED_KEYWORDS = (
    "_ORE", "_HIDE", "_FIBER", "_WOOD", "_ROCK",
    "_BAR", "_LEATHER", "_CLOTH", "_PLANKS", "_STONEBLOCK", "_BLOCK"
)

ENCHANT_MATERIAL_BOUNDS = {
    "T4_RUNE": (5, 200),
    "T5_RUNE": (15, 500),
    "T6_RUNE": (50, 2000),
    "T7_RUNE": (200, 8000),
    "T8_RUNE": (800, 50000),
    "T4_SOUL": (10, 400),
    "T5_SOUL": (40, 1500),
    "T6_SOUL": (150, 6000),
    "T7_SOUL": (600, 25000),
    "T8_SOUL": (2500, 150000),
    "T4_RELIC": (50, 2000),
    "T5_RELIC": (200, 8000),
    "T6_RELIC": (800, 30000),
    "T7_RELIC": (3000, 150000),
    "T8_RELIC": (10000, 600000),
    "T4_SHARD_AVALONIAN": (200, 5000),
    "T5_SHARD_AVALONIAN": (500, 15000),
    "T6_SHARD_AVALONIAN": (1500, 40000),
    "T7_SHARD_AVALONIAN": (4000, 100000),
    "T8_SHARD_AVALONIAN": (10000, 450000),
    "QUESTITEM_TOKEN_AVALON": (100, 450000),
}

def is_raw_or_refined_material(item_id: str) -> bool:
    u = item_id.upper()
    return any(k in u for k in RAW_REFINED_KEYWORDS)


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
    city: {
        "refining": data["refining_bonus"],
        "crafting": data["bonus_categories"],
    }
    for city, data in CITY_CRAFTING_BONUSES.items()
}

BM_CITY = "Black Market"
CAERLEON = "Caerleon"
BRECILIEN = "Brecilien"
ALL_SELL_CITIES = ROYAL_CITIES + [CAERLEON, BRECILIEN]

# Routes that pass through dangerous zones (Caerleon ring roads / Mists)
DANGEROUS_DESTINATIONS = {CAERLEON, BM_CITY, BRECILIEN}

# ─── Outlier / Manipulation Detection ────────────────────────────────────────

MAX_SELL_TO_BUY_RATIO = 5.0  # If sell_min > buy_max * 5 → single-item manipulation
MIN_PRICE = 100  # Ignore anything below 100 silver (test orders)
ABSOLUTE_MAX_PRICE = 500_000_000  # 500M cap — anything higher is a troll order
MIN_ROYAL_VOLUME = 0  # Allow data with 0 or missing reported volume from community API
MIN_BM_VOLUME = 0      # BM orders are NPC generated


def get_min_realistic_price(item_id: str = "") -> int:
    """
    Returns minimum realistic market price based on item tier, enchantment, and category in Albion Online.
    Prevents corrupt 100-700 silver listings for high-tier equipment (T5-T8), refined resources, or artifacts
    from poisoning cost and profit calculations.
    """
    if not item_id or not item_id.startswith("T"):
        return MIN_PRICE

    item_upper = item_id.upper()

    # Extract tier (T4..T8)
    tier = 4
    try:
        tier = int(item_id[1])
    except (ValueError, IndexError):
        tier = 4

    # Extract enchantment level (@1, @2, @3, @4 or _LEVEL1, etc.)
    enchant = 0
    if "@" in item_id:
        try:
            enchant = int(item_id.split("@")[1])
        except ValueError:
            enchant = 0
    elif "_LEVEL" in item_upper:
        try:
            enchant = int(item_upper.split("_LEVEL")[1][0])
        except (ValueError, IndexError):
            enchant = 0

    # 1. Runes, Souls, Relics, Avalonian Shards
    if "_RUNE" in item_upper:
        return {4: 10, 5: 30, 6: 100, 7: 300, 8: 1000}.get(tier, 10)
    if "_SOUL" in item_upper:
        return {4: 30, 5: 100, 6: 300, 7: 1000, 8: 3500}.get(tier, 30)
    if "_RELIC" in item_upper:
        return {4: 100, 5: 300, 6: 1000, 7: 4000, 8: 15000}.get(tier, 100)
    if "_SHARD_AVALONIAN" in item_upper:
        return {4: 300, 5: 800, 6: 2500, 7: 6000, 8: 15000}.get(tier, 300)

    # 2. Artifacts (_ARTEFACT_)
    if "_ARTEFACT_" in item_upper:
        base_art_min = {4: 1000, 5: 3500, 6: 12000, 7: 35000, 8: 100000}.get(tier, 1000)
        if any(art in item_upper for art in ["_HELL", "_UNDEAD", "_KEEPER", "_MORGANA", "_AVALON", "_ROYAL", "_FEY", "_MISTS", "_CRYSTAL"]):
            base_art_min *= 2
        return base_art_min

    # 3. Check if this item is EQUIPMENT (Weapons, Armor, Head, Shoes, Off-hands, Capes, Bags)
    EQUIPMENT_KEYS = [
        "ARMOR", "ROBE", "JACKET", "GARB", "HEAD", "HELMET", "COWL", "CAP", "SHOES", "BOOTS",
        "MAIN_", "2H_", "1H_", "OFF_", "BAG", "CAPE", "MOUNT", "TOOL", "SPEAR", "SWORD", "AXE",
        "BOW", "CROSSBOW", "HAMMER", "MACE", "DAGGER", "STAFF", "FLAIL", "SCYTHE", "HALBERD",
        "CLAW", "KNUCKLES", "SHAPESHIFTER", "QUARTERSTAFF", "SHIELD", "TORCH", "BOOK", "TOME",
        "HORN", "ORB", "TOTEM", "TALISMAN", "LAMP", "SKULL", "CENSER", "MUISAK", "TAPROOT"
    ]
    is_equipment = any(eq in item_upper for eq in EQUIPMENT_KEYS)

    if is_equipment:
        tier_min_map = {
            4: 1_500,
            5: 4_000,
            6: 12_000,
            7: 35_000,
            8: 100_000,
        }
        min_p = tier_min_map.get(tier, 1_500)
        enchant_mult = {0: 1.0, 1: 1.8, 2: 3.5, 3: 8.0, 4: 20.0}.get(enchant, 1.0)
        min_p = int(min_p * enchant_mult)

        # Artifact / Faction / Avalonian / Fey / Mist equipment require rare expensive artifacts
        ARTIFACT_EQUIP_KEYS = [
            "_HELL", "_UNDEAD", "_KEEPER", "_MORGANA", "_AVALON", "_ROYAL",
            "_FEY", "_MISTS", "_CRYSTAL", "_SHADOW", "_DEMON", "_GATHERER"
        ]
        if any(art in item_upper for art in ARTIFACT_EQUIP_KEYS):
            min_p = max(min_p, min_p * 4)  # e.g. T6 Feyscale Robe -> min 48,000s

        return min_p

    # 4. Raw Resources (ORE, HIDE, FIBER, WOOD, ROCK)
    RAW_RESOURCE_KEYS = ["_ORE", "_HIDE", "_FIBER", "_WOOD", "_ROCK"]
    if any(r in item_upper for r in RAW_RESOURCE_KEYS):
        base_raw_min = {4: 8, 5: 25, 6: 80, 7: 250, 8: 800}.get(tier, 8)
        enchant_mult = {0: 1.0, 1: 2.5, 2: 7.0, 3: 20.0, 4: 60.0}.get(enchant, 1.0)
        return int(base_raw_min * enchant_mult)

    # 5. Refined Resources (PLANKS, CLOTH, LEATHER, METALBAR, BAR, STONEBLOCK, BLOCK)
    REFINED_RESOURCE_KEYS = ["_PLANKS", "_CLOTH", "_LEATHER", "_METALBAR", "_BAR", "_STONEBLOCK", "_BLOCK"]
    if any(r in item_upper for r in REFINED_RESOURCE_KEYS):
        base_ref_min = {4: 15, 5: 45, 6: 150, 7: 450, 8: 1500}.get(tier, 15)
        enchant_mult = {0: 1.0, 1: 2.5, 2: 7.0, 3: 20.0, 4: 60.0}.get(enchant, 1.0)
        return int(base_ref_min * enchant_mult)

    # 6. Fallback for consumables/crops/seeds
    return 10


def get_fallback_item_value(item_id: str = "") -> float:
    """
    Returns estimated minimum ItemValue based on item tier if missing from DB metadata.
    Prevents station fees from calculating as 0 silver for crafted equipment and resources.
    """
    if not item_id or not item_id.startswith("T"):
        return 32.0
    try:
        tier = int(item_id[1])
        tier_val_map = {
            4: 64.0,
            5: 128.0,
            6: 256.0,
            7: 512.0,
            8: 1024.0,
        }
        return tier_val_map.get(tier, 32.0)
    except (ValueError, IndexError):
        return 32.0



def is_price_valid(sell_min: int, buy_max: int, daily_volume: int = 0, item_id: str = "") -> bool:
    """
    Returns True if the price looks like a real market, not manipulation or corrupt test data.
    Rejects troll buy orders, corrupt test values, and extreme orderbook manipulation ratios (> 4x).
    """
    min_allowed = get_min_realistic_price(item_id) if item_id else MIN_PRICE
    if sell_min > 0:
        if sell_min < min_allowed or sell_min > ABSOLUTE_MAX_PRICE:
            return False
    if buy_max > 0:
        if buy_max < min_allowed or buy_max > ABSOLUTE_MAX_PRICE:
            return False
        if sell_min > 0:
            if (sell_min / buy_max) > 5.0:
                return False
            if (buy_max / sell_min) > 5.0:
                return False

    return True




def is_bm_price_valid(bm_buy_price: int, item_value: float = 0.0) -> bool:
    """
    Validates Black Market buy order price against sanity limits.
    """
    if bm_buy_price <= MIN_PRICE:
        return False
    if bm_buy_price > ABSOLUTE_MAX_PRICE:
        return False
    if item_value > 0 and (bm_buy_price / item_value) >= 5000:
        return False
    return True




def pool_price_sanity(
    scanned_price: int,
    history_avg_price: float = 0.0,
    daily_volume: int = 0,
    min_allowed_ratio: float = 0.75,
) -> int:
    """
    Validates scanned top-of-book price against the 24-hour pooled average price.
    If an item was listed at 100, bought instantly, and the remaining pool is 150+,
    a lone scanned price of 100 (stale or 1-unit flash fill) is anchored to the pool price.
    """
    if scanned_price <= 0:
        return 0
    if history_avg_price > 0:
        # If scanned price is significantly lower than 24h pool average with low daily volume,
        # it was either already bought out or an unrepresentative single-unit dump.
        if scanned_price < history_avg_price * min_allowed_ratio and (daily_volume == 0 or daily_volume < 50):
            # Anchor to the pool price to reflect true remaining market orderbook
            return int(history_avg_price)
    return scanned_price


def cross_city_outlier_check(prices_by_city: dict[str, int]) -> dict[str, int]:
    """
    Detects both extreme high manipulation (>3x median) and extreme low stale/exhausted traps (<0.55x median or >2x lower than other cities).
    """
    valid = [p for p in prices_by_city.values() if p > 0]
    if not valid:
        return prices_by_city

    if len(valid) == 2:
        p_min, p_max = min(valid), max(valid)
        if p_max > p_min * 2.0:
            # Low price is an extreme outlier / exhausted dump -> anchor to high price
            cleaned = {}
            for city, price in prices_by_city.items():
                cleaned[city] = p_max
            return cleaned
        return prices_by_city

    sorted_prices = sorted(valid)
    median = sorted_prices[len(sorted_prices) // 2]

    cleaned = {}
    for city, price in prices_by_city.items():
        if price <= 0:
            cleaned[city] = 0
        elif price > median * 3:
            # Overpriced outlier / player trap
            cleaned[city] = 0
        elif price < median * 0.55:
            # Underpriced single-unit dump / already bought out -> anchor to median pool
            cleaned[city] = int(median)
        else:
            cleaned[city] = price
    return cleaned


# ─── Opportunity Dataclasses ─────────────────────────────────────────────────


@dataclass
class BMOpportunity:
    """
    Black Market flip: buy in royal city, run to Caerleon, sell.
    3. BM selling check. Standard marketplace tax applies, no setup fee. Risk = travel to Caerleon.
    """

    item_id: str
    item_name: str
    buy_city: str  # Where to buy the item (cheapest royal city)
    buy_price: int  # sell_price_min in buy_city (what you pay)
    bm_buy_price: int  # Black Market buy order (what BM pays you)
    # 5. Output logic: After marketplace tax deduction.
    net_profit: int  # bm_buy_price - buy_price
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
        return float(self.net_profit)


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
    profit_margin: float = 0.0
    score: float = 0.0
    quality: int = 1
    base_quality: int = 1
    data_age_base: int = 9999
    data_age_material: int = 9999
    data_age_bm: int = 9999
    data_age_seconds: int = 0
    base_city: str = "Caerleon"
    sell_city: str = "Black Market"
    is_dangerous: bool = False

    @property
    def item_id(self) -> str:
        return self.target_item_id

    @property
    def item_name(self) -> str:
        return self.target_item_name

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
    focus_cost_per_craft: float = 0.0
    ingredients: list[dict] = field(default_factory=list)
    safe_limit: int = 1
    roi: float = 0.0
    profit_per_kg: float = 0.0
    score: float = 0.0
    is_dangerous: bool = False

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
class TransmutationOpportunity:
    """
    Transmutator station flip: upgrade raw/refined resources or sigils.
    Cost = Source Item Price + Silver Transmutation Fee.
    RRR = 0% (Transmutation receives NO resource return in Albion Online).
    """
    item_id: str
    item_name: str
    source_item_id: str
    source_item_name: str
    source_price: int
    transmutation_fee: int
    total_cost: int
    sell_price: int
    sell_city: str
    net_profit: int
    profit_pct: float
    roi: float
    daily_volume: int
    data_age_source: int
    data_age_sell: int
    quality: int = 1
    safe_limit: int = 1
    score: float = 0.0
    source_city: str = ""


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


def parse_transmutable_resource(item_id: str) -> tuple[int, str, int, bool] | None:
    """
    Parses a resource item ID into (tier, resource_type, enchant_level, is_raw).
    Returns None if not a valid transmutable raw or refined resource.

    Examples:
        T4_WOOD -> (4, 'WOOD', 0, True)
        T5_WOOD_LEVEL2@2 -> (5, 'WOOD', 2, True)
        T6_PLANKS_LEVEL1@1 -> (6, 'PLANKS', 1, False)
        T8_CLOTH -> (8, 'CLOTH', 0, False)
    """
    if not item_id or not item_id.startswith(("T4_", "T5_", "T6_", "T7_", "T8_")):
        return None

    # Exclude non-resources
    if any(bad in item_id for bad in [
        "ARMOR", "HEAD", "SHOES", "BOOTS", "HELMET", "COWL", "CAP", "ROBE", "JACKET", "GARB",
        "MAIN_", "2H_", "OFF_", "BAG", "CAPE", "MOUNT", "POTION", "FOOD", "MEAL", "SOUP",
        "STEW", "FISH", "MEAT", "JOURNAL", "BOOK", "SKILLBOOK", "TROPHY", "CONTRACT",
        "ARTEFACT", "TOKEN", "QUESTITEM", "FURNITURE", "GATHERER", "TOOL"
    ]):
        return None

    try:
        tier = int(item_id[1])
    except (ValueError, IndexError):
        return None

    enchant = 0
    clean = item_id
    if "@" in clean:
        clean, e_str = clean.rsplit("@", 1)
        try:
            enchant = int(e_str)
        except ValueError:
            enchant = 0
    if "_LEVEL" in clean:
        clean = clean.split("_LEVEL")[0]

    parts = clean.split("_")
    if len(parts) != 2:
        return None

    res_type = parts[1]
    VALID_RAW = {"ORE", "WOOD", "HIDE", "FIBER", "ROCK"}
    VALID_REFINED = {"METALBAR", "PLANKS", "LEATHER", "CLOTH", "STONEBLOCK"}

    if res_type in VALID_RAW:
        is_raw = True
    elif res_type in VALID_REFINED:
        is_raw = False
    else:
        return None

    if res_type in {"ROCK", "STONEBLOCK"} and enchant > 0:
        return None

    return tier, res_type, enchant, is_raw


def make_resource_id(tier: int, res_type: str, enchant: int = 0) -> str:
    """Constructs canonical database/API item ID for a given resource tier and enchantment."""
    if enchant == 0:
        return f"T{tier}_{res_type}"
    return f"T{tier}_{res_type}_LEVEL{enchant}@{enchant}"


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
        min_bm_profit: int = 3_000,
        min_bm_profit_pct: float = 3.0,
        min_craft_profit: int = 2_000,
        min_craft_profit_pct: float = 2.5,
        min_arb_profit: int = 2_000,
        min_arb_profit_pct: float = 2.5,
        min_mm_volume: int = 2,
        min_mm_profit: int = 2_000,
        min_mm_profit_pct: float = 2.5,
        min_roi: float = 2.5,
        use_focus: bool = False,
        premium: bool = None,
        default_trade_volume: int = 1,
        use_slippage: bool = True,
        allow_zero_volume: bool = True,

        crafting_local_sourcing_only: bool = None,
        refining_local_sourcing_only: bool = None,
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
        self.allow_enchant_transport = True
        self.allow_zero_volume = allow_zero_volume
        self.crafting_local_sourcing_only = (
            crafting_local_sourcing_only
            if crafting_local_sourcing_only is not None
            else getattr(settings, "crafting_local_sourcing_only", True)
        )
        self.refining_local_sourcing_only = (
            refining_local_sourcing_only
            if refining_local_sourcing_only is not None
            else getattr(settings, "refining_local_sourcing_only", False)
        )


    @property
    def is_premium(self) -> bool:
        if self._override_premium is not None:
            return self._override_premium
        from app.core.config import settings
        return getattr(settings, "is_premium", True)

    @is_premium.setter
    def is_premium(self, value: bool | None) -> None:
        self._override_premium = value

    @property
    def tax(self) -> float:
        return PREMIUM_TAX if self.is_premium else NON_PREMIUM_TAX

    @tax.setter
    def tax(self, value: float) -> None:
        pass  # Derived from is_premium, gracefully accept assignment

    # ── Internal helpers ────────────────────────────────────────────────────

    def _get_price(self, prices: dict, item_id: str, city: str, quality: int = 1) -> dict | None:
        """Safe price lookup with None if missing, with automatic key alias fallback for refined materials and enchantments."""
        p = prices.get(item_id, {}).get(city, {}).get(quality)
        if p and (p.get("sell_price_min", 0) > 0 or p.get("buy_price_max", 0) > 0):
            return p

        # Check alternative alias keys (e.g. T4_CLOTH_LEVEL1 <-> T4_CLOTH@1 <-> T4_CLOTH_LEVEL1@1, T4_PLANKS_LEVEL4@4 <-> T4_PLANKS@4, T4_BAR <-> T4_METALBAR)
        if "@" in item_id or "_LEVEL" in item_id:
            aliases = []
            import re
            m = re.search(r'_LEVEL(\d+)', item_id)
            if m:
                e = m.group(1)
                base = re.sub(r'_LEVEL\d+', '', item_id)
                if "@" in base:
                    base = base.split("@")[0]
                aliases.extend([
                    f"{base}@{e}",
                    f"{base}_LEVEL{e}@{e}",
                    f"{base}_LEVEL{e}",
                ])
            elif "@" in item_id:
                parts = item_id.split("@")
                if len(parts) == 2 and parts[1].isdigit():
                    e = parts[1]
                    base = parts[0]
                    aliases.extend([
                        f"{base}_LEVEL{e}@{e}",
                        f"{base}_LEVEL{e}",
                        f"{base}@{e}",
                    ])

            for alias in aliases:
                p_alias = prices.get(alias, {}).get(city, {}).get(quality)
                if p_alias and (p_alias.get("sell_price_min", 0) > 0 or p_alias.get("buy_price_max", 0) > 0):
                    return p_alias

        return p

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
            if not is_price_valid(price, buy_max, p.get("volume_24h", 0), item_id=item_id):
                continue
            age = p.get("data_age_seconds", 9999)
            if age > get_max_material_age_seconds(item_id):
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
        """
        Risk-Proportional Dynamic Minimum Margin Curve:
        Strictly enforces that profits justify the capital at risk, especially in Red Zone / dangerous routes.
        Low-cost items in Red Zones (< 150k) require >= 20% margin.
        Mid-cost items (150k - 1M) require 20% down to 12% margin.
        High-cost whale items (1M - 10M+) require 12% down to 8% margin, with massive absolute silver payouts.
        """
        if not is_dangerous:
            return default_min

        LOW_PRICE = 150_000
        HIGH_PRICE = 1_000_000
        WHALE_PRICE = 5_000_000

        if buy_price <= LOW_PRICE:
            return max(default_min, 20.0)
        elif buy_price <= HIGH_PRICE:
            t = (buy_price - LOW_PRICE) / (HIGH_PRICE - LOW_PRICE)
            return max(default_min, 20.0 - (t * 8.0))  # 20% down to 12%
        elif buy_price <= WHALE_PRICE:
            t = (buy_price - HIGH_PRICE) / (WHALE_PRICE - HIGH_PRICE)
            return max(default_min, 12.0 - (t * 4.0))  # 12% down to 8%
        else:
            return max(default_min, 8.0)

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
        Factors: profit, margin, volume, smooth time-decay data freshness.
        Whale / high-value items with massive absolute silver profit stay highly ranked.
        """
        freshness = max(0.05, calculate_time_decay(opp.data_age_bm, half_life_hours=get_tier_based_half_life_hours(opp.item_id)))
        vol_score = min(1.0, opp.daily_volume / 25.0) if opp.daily_volume > 0 else 0.6
        margin_bonus = min(2.0, max(0.6, opp.profit_pct / 15.0))
        
        raw_score = opp.effective_profit * freshness * vol_score * margin_bonus
        
        # Risk adjustment scaled by gank probability, capped to 25% of profit so whale profits remain positive
        risk_deduction = min(raw_score * 0.25, opp.buy_price * 0.02)
        score = max(50.0, raw_score - risk_deduction)
        score = self._apply_weight_penalty(score, getattr(opp, "profit_per_kg", 0.0))
        return round(max(0.0, score), 2)

    def _score_craft(self, opp: CraftingOpportunity) -> float:
        freshness = max(0.05, calculate_time_decay(opp.data_age_sell, half_life_hours=get_tier_based_half_life_hours(opp.item_id)))
        vol_score = min(1.0, opp.daily_volume / 30.0) if opp.daily_volume > 0 else 0.3
        
        # Multi-leg synchronization score (penalizes drift between materials & finished product)
        sync_score = calculate_leg_sync_score(opp.data_age_sell, opp.data_age_materials, tier=getattr(opp, "tier", 4))
        score = opp.profit * freshness * vol_score * sync_score
        
        # Only apply weight penalty if we are transporting it to a different city
        if opp.craft_city != opp.sell_city:
            score = self._apply_weight_penalty(score, getattr(opp, "profit_per_kg", 0.0))
            
        return round(max(0.0, score), 2)

    def _score_arb(self, opp: ArbitrageOpportunity) -> float:
        half_life = get_tier_based_half_life_hours(opp.item_id)
        freshness_buy = calculate_time_decay(opp.data_age_buy, half_life_hours=half_life)
        freshness_sell = calculate_time_decay(opp.data_age_sell, half_life_hours=half_life)
        freshness = max(0.05, min(freshness_buy, freshness_sell))
        vol_score = min(1.0, opp.daily_volume / 30.0) if opp.daily_volume > 0 else 0.3
        danger_penalty = 0.5 if opp.is_dangerous_route else 1.0
        
        sync_score = calculate_leg_sync_score(opp.data_age_sell, opp.data_age_buy, tier=4)
        capital_risk_premium = opp.buy_price * 0.05 if opp.is_dangerous_route else 0.0
        
        score = (opp.net_profit * freshness * vol_score * sync_score * danger_penalty) - capital_risk_premium
        score = self._apply_weight_penalty(score, getattr(opp, "profit_per_kg", 0.0))
        return round(max(0.0, score), 2)

    def _score_refining(self, opp: RefiningOpportunity) -> float:
        half_life = get_tier_based_half_life_hours(opp.item_id)
        freshness_mat = calculate_time_decay(opp.data_age_materials, half_life_hours=half_life)
        freshness_sell = calculate_time_decay(opp.data_age_sell, half_life_hours=half_life)
        freshness = max(0.05, min(freshness_mat, freshness_sell))
        vol_score = min(1.0, opp.daily_volume / 100.0) if opp.daily_volume > 0 else 0.3
        sync_score = calculate_leg_sync_score(opp.data_age_sell, opp.data_age_materials, tier=4)
        
        score = opp.profit * freshness * vol_score * sync_score
        score = self._apply_weight_penalty(score, getattr(opp, "profit_per_kg", 0.0))
        return round(max(0.0, score), 2)

    def _score_mm(self, opp: MarketMakingOpportunity) -> float:
        half_life = get_tier_based_half_life_hours(opp.item_id)
        freshness_buy = calculate_time_decay(opp.data_age_buy, half_life_hours=half_life)
        freshness_sell = calculate_time_decay(opp.data_age_sell, half_life_hours=half_life)
        freshness = max(0.05, min(freshness_buy, freshness_sell))
        
        vol_score = min(1.0, opp.daily_volume / 500.0) if opp.daily_volume > 0 else 0.3
        
        danger_penalty = 0.5 if opp.is_dangerous_route else 1.0
        capital_risk_premium = opp.buy_price * 0.05 if opp.is_dangerous_route else 0.0
        
        score = (opp.net_profit * freshness * vol_score * danger_penalty) - capital_risk_premium
        score = self._apply_weight_penalty(score, getattr(opp, "profit_per_kg", 0.0))
        return round(max(0.0, score), 2)

    # ── Public scan methods ─────────────────────────────────────────────────

    def _get_royal_median_sell(self, prices: dict, item_id: str, quality: int = 1) -> int:
        """Computes median sell price across Safe Royal Cities to detect local price manipulation."""
        royal_sells = []
        for city in ROYAL_SAFE_CITIES:
            for q in range(quality, 6):
                p = self._get_price(prices, item_id, city, q)
                if p and p.get("sell_price_min", 0) > 0:
                    sp = p["sell_price_min"]
                    bm = p.get("buy_price_max", 0)
                    if is_price_valid(sp, bm, item_id=item_id):
                        royal_sells.append(sp)
                        break
        if not royal_sells:
            return 0
        royal_sells.sort()
        return royal_sells[len(royal_sells) // 2]

    def _get_enchant_material_price(
        self, prices: dict, material_id: str, city: str, required_qty: int = 1
    ) -> tuple[int, int, int]:
        """
        Returns verified (unit_price, data_age_seconds, daily_volume) for Runes/Souls/Relics/Shards/Energy.
        Depth-Aware Pricing (Anti-Bait):
        1. Queries NATS live Level 2 orderbook VWAP for `required_qty` units if live stream is active.
        2. In AODP snapshot data, detects single-unit top bait orders (sell_price_min << avg_price_24h)
           and scales bulk unit costs for 96 / 192 / 288 / 384 units to represent true market depth.
        3. Validates local city price with strict freshness and realistic bounds.
        4. If city is Caerleon: Strictly requires fresh local Caerleon price; rejects falling back to Royal median.
        5. If city is a Royal city: Resolves to cross-city median royal price if local is missing.
        """
        cand_ids = [material_id]
        if "SHARD_AVALONIAN" in material_id:
            cand_ids.append("QUESTITEM_TOKEN_AVALON")

        def _calculate_depth_adjusted_unit_price(p_data: dict, bounds: tuple[int, int]) -> int:
            sp = p_data.get("sell_price_min", 0)
            avg_p = p_data.get("avg_price_24h", 0.0)
            sell_depth = p_data.get("sell_depth", 0)

            if sp <= 0:
                return 0

            # If live LOB depth indicates insufficient quantity at top price:
            if sell_depth > 0 and sell_depth < required_qty:
                ref_price = avg_p if avg_p > sp else (sp * 1.20)
                blended = (sell_depth * sp + (required_qty - sell_depth) * ref_price) / float(required_qty)
                return max(bounds[0], min(bounds[1], int(round(blended))))

            # In historical snapshot without exact orderbook list:
            # If sell_price_min is suspiciously below the 24h pool average price (>10% gap):
            if avg_p > 0 and sp < (avg_p * 0.90):
                blend_factor = min(0.85, (required_qty / 384.0) * 0.85)
                blended = (sp * (1.0 - blend_factor)) + (avg_p * blend_factor)
                return max(bounds[0], min(bounds[1], int(round(blended))))

            # Depth scale for standard bulk batches (96, 192, 288, 384 units)
            if required_qty >= 96:
                depth_multiplier = 1.0 + (0.04 * (required_qty / 96.0))  # +4% for 96, +8% for 192, +16% for 384
                scaled_sp = sp * depth_multiplier
                return max(bounds[0], min(bounds[1], int(round(scaled_sp))))

            return max(bounds[0], min(bounds[1], sp))

        for m_id in cand_ids:
            bounds = ENCHANT_MATERIAL_BOUNDS.get(m_id, (5, 600_000))

            # 0. Try live NATS LOB VWAP
            try:
                from app.ingestion.nats_client import nats_client
                vwap_val, depth_avail = nats_client.get_vwap_for_quantity(m_id, city, 1, required_qty, is_buy=True)
                if vwap_val is not None and vwap_val > 0:
                    vwap_int = int(round(vwap_val))
                    if bounds[0] <= vwap_int <= bounds[1]:
                        return (vwap_int, 0, depth_avail or required_qty)
            except Exception:
                pass

            # 1. Try local city price
            p = self._get_price(prices, m_id, city, 1)
            if p and p.get("sell_price_min", 0) > 0:
                sp = p["sell_price_min"]
                bm = p.get("buy_price_max", 0)
                age = p.get("data_age_seconds", 99999)
                vol = p.get("volume_24h", 0)
                if age <= get_max_material_age_seconds(m_id, volume_24h=vol) and bounds[0] <= sp <= bounds[1] and is_price_valid(sp, bm, item_id=m_id):
                    unit_cost = _calculate_depth_adjusted_unit_price(p, bounds)
                    return (unit_cost, age, vol)

        # 2. For Caerleon / Black Market enchanting, do NOT fall back to cheap Royal prices!
        if city == "Caerleon":
            return (0, 99999, 0)

        # 3. Cross-city Royal median fallback (only for Royal continent cities)
        royal_candidates = []
        for m_id in cand_ids:
            bounds = ENCHANT_MATERIAL_BOUNDS.get(m_id, (5, 600_000))
            for r_city in ROYAL_SAFE_CITIES:
                rp = self._get_price(prices, m_id, r_city, 1)
                if rp and rp.get("sell_price_min", 0) > 0:
                    rsp = rp["sell_price_min"]
                    rbm = rp.get("buy_price_max", 0)
                    rage = rp.get("data_age_seconds", 99999)
                    rvol = rp.get("volume_24h", 0)
                    if rage <= get_max_material_age_seconds(m_id, volume_24h=rvol) and bounds[0] <= rsp <= bounds[1] and is_price_valid(rsp, rbm, item_id=m_id):
                        adjusted_rsp = _calculate_depth_adjusted_unit_price(rp, bounds)
                        royal_candidates.append((adjusted_rsp, rage, rvol))

        if royal_candidates:
            royal_candidates.sort(key=lambda x: x[0])
            mid = len(royal_candidates) // 2
            return royal_candidates[mid]

        return (0, 99999, 0)

    def scan_b_enchanting(
        self,
        prices: dict,
        item_names: dict[str, str],
        item_categories: dict[str, str] = None,
        item_values: dict[str, float] = None,
    ) -> list[EnchantingOpportunity]:
        """
        Scan Black Market equipment enchantment:
        Buy base item (Q1-Q5) in Caerleon + enchantment material (Runes/Souls/Relics) in Caerleon
        -> Enchant at Caerleon Foundry -> Sell directly into Black Market Buy Order.
        0 transport risk: inside Caerleon.
        """
        results = []

        for item_id in prices.keys():
            reqs = self._get_enchant_requirements(item_id)
            if not reqs:
                continue
            base_item_id, material_id, material_qty = reqs

            for quality in [1, 2, 3, 4, 5]:
                # BM target buy order
                bm_data = self._get_price(prices, item_id, BM_CITY, quality)
                if not bm_data:
                    continue
                bm_price = bm_data.get("buy_price_max", 0)
                bm_volume = bm_data.get("volume_24h", 0)
                bm_age = bm_data.get("data_age_seconds", 9999)

                item_val = item_values.get(item_id, 0.0) if item_values else 0.0
                max_bm_age = get_max_allowed_bm_age_seconds(item_id, bm_price)
                if not is_bm_price_valid(bm_price, item_val) or bm_age > max_bm_age:
                    continue

                # Base item MUST be sourced locally in Caerleon (zero Red Zone transport risk)
                base_price, base_age, base_vol, best_base_quality = 0, 9999, 0, quality
                for q in range(quality, 6):
                    base_data = self._get_price(prices, base_item_id, CAERLEON, q)
                    if base_data and base_data.get("sell_price_min", 0) > 0 and base_data.get("data_age_seconds", 9999) <= get_max_material_age_seconds(base_item_id):
                        cand_sp = base_data["sell_price_min"]
                        cand_bm = base_data.get("buy_price_max", 0)
                        cand_age = base_data.get("data_age_seconds", 9999)
                        if is_price_valid(cand_sp, cand_bm, item_id=base_item_id):
                            if base_price == 0 or cand_sp < base_price:
                                base_price = cand_sp
                                base_age = cand_age
                                base_vol = base_data.get("volume_24h", 0)
                                best_base_quality = q

                if base_price <= 0 or base_age > get_max_material_age_seconds(base_item_id):
                    continue

                # Verified Enchantment Material Price in Caerleon ONLY (zero Red Zone transport risk)
                mat_price, mat_age, mat_vol = self._get_enchant_material_price(prices, material_id, CAERLEON, required_qty=material_qty)
                if mat_price <= 0 or mat_age > get_max_material_age_seconds(material_id, volume_24h=mat_vol):
                    continue

                # Multi-Leg Desynchronization Guard: Base item, enchanting mat, and BM buy order must be aligned in time
                item_tier, item_enchant = _extract_tier_enchant(item_id)
                max_allowed_desync = get_max_allowed_leg_desync_seconds(item_tier, item_enchant)
                if max(abs(bm_age - base_age), abs(bm_age - mat_age)) > max_allowed_desync:
                    continue

                # Apply slippage model
                effective_mat_unit = calculate_effective_price(mat_price, material_qty, mat_vol, is_buy=True)
                total_mat_cost = effective_mat_unit * material_qty
                
                trade_vol = self.default_trade_volume if self.use_slippage else 1
                effective_base = calculate_effective_price(base_price, trade_vol, base_vol, is_buy=True)
                effective_bm = calculate_effective_price(bm_price, trade_vol, bm_volume, is_buy=False)
                
                # Selling to Black Market incurs standard marketplace tax (4% premium, 8% non-premium), but NO setup fee
                revenue_net = effective_bm * (1.0 - self.tax)
                total_cost = effective_base + total_mat_cost
                net_profit = revenue_net - total_cost

                min_profit_silver = max(self.min_bm_profit, 2000) if self.min_bm_profit > 0 else 2000
                if net_profit < min_profit_silver:
                    continue

                profit_pct = (net_profit / total_cost) * 100
                roi_val = profit_pct
                dynamic_min_pct = self._dynamic_min_margin(total_cost, is_dangerous=False, default_min=self.min_bm_profit_pct)
                if profit_pct < dynamic_min_pct or roi_val < self.min_roi:
                    continue

                # High profit (>60% ROI) items get filled faster in-game; require fresh data <= 2 hours (7200s)
                if profit_pct > 60.0 and (bm_age > 7200 or base_age > get_max_material_age_seconds(base_item_id)):
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
                    profit_margin=round((net_profit / effective_bm) * 100, 2) if effective_bm > 0 else 0.0,
                    quality=quality,
                    base_quality=best_base_quality,
                    data_age_base=base_age,
                    data_age_material=mat_age,
                    data_age_bm=bm_age,
                    data_age_seconds=bm_age,
                    base_city=CAERLEON,
                    sell_city=BM_CITY,
                    is_dangerous=False,
                )
                
                freshness = max(0.1, 1.0 - (bm_age + base_age) / (get_max_material_age_seconds(item_id) + get_max_material_age_seconds(base_item_id)))
                vol_score = min(1.0, bm_volume / 50.0) if bm_volume > 0 else 0.2
                opp.score = round(net_profit * freshness * vol_score, 2)
                results.append(opp)

        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def scan_enchanting(
        self,
        prices: dict,
        item_names: dict[str, str],
        item_categories: dict[str, str] = None,
    ) -> list[EnchantingOpportunity]:
        """
        Find safe equipment enchantment flips within Safe Royal Cities.
        Buys base item + materials in Royal City -> Enchants at Foundry -> Sells on Royal marketplace.
        100% Safe Blue/Yellow Continent: Standard marketplace sales tax applies.
        """
        results = []

        for item_id in prices.keys():
            reqs = self._get_enchant_requirements(item_id)
            if not reqs:
                continue
            base_item_id, material_id, material_qty = reqs

            for city in ROYAL_SAFE_CITIES:
                best_opp_for_city = None

                for quality in [1, 2, 3, 4, 5]:
                    sell_data = self._get_price(prices, item_id, city, quality)
                    if not sell_data:
                        continue
                    sell_price = sell_data.get("sell_price_min", 0)
                    buy_max = sell_data.get("buy_price_max", 0)
                    sell_vol = sell_data.get("volume_24h", 0)
                    sell_age = sell_data.get("data_age_seconds", 9999)

                    if sell_price <= 0 or not is_price_valid(sell_price, buy_max, item_id=item_id) or sell_age > get_max_material_age_seconds(item_id):
                        continue

                    # Anti-Troll Anchor: Real players do not sell enchanted gear below un-enchanted base price
                    base_price, base_age, base_vol, best_base_quality = 0, 9999, 0, quality
                    for q in range(quality, 6):
                        b_data = self._get_price(prices, base_item_id, city, q)
                        if b_data and b_data.get("sell_price_min", 0) > 0 and b_data.get("data_age_seconds", 9999) <= get_max_material_age_seconds(base_item_id):
                            cand_sp = b_data["sell_price_min"]
                            cand_bm = b_data.get("buy_price_max", 0)
                            if is_price_valid(cand_sp, cand_bm, item_id=base_item_id):
                                if base_price == 0 or cand_sp < base_price:
                                    base_price = cand_sp
                                    base_age = b_data.get("data_age_seconds", 9999)
                                    base_vol = b_data.get("volume_24h", 0)
                                    best_base_quality = q

                    if base_price <= 0 or base_age > get_max_material_age_seconds(base_item_id):
                        continue

                    # Cross-City Base Sanity Anchor: If base item is suspiciously cheap (< 40% of Royal median),
                    # use Royal median base cost to prevent troll listings from showing fake enchanting profits
                    royal_base_median = self._get_royal_median_sell(prices, base_item_id, quality)
                    if royal_base_median > 0:
                        if base_price < royal_base_median * 0.40:
                            base_price = royal_base_median

                    # Verified Enchantment Material Price
                    mat_price, mat_age, mat_vol = self._get_enchant_material_price(prices, material_id, city, required_qty=material_qty)
                    if mat_price <= 0 or mat_age > get_max_material_age_seconds(material_id, volume_24h=mat_vol):
                        continue

                    # Multi-Leg Desynchronization Guard: Base item, enchanting mat, and sell listing must be aligned
                    item_tier, item_enchant = _extract_tier_enchant(item_id)
                    max_allowed_desync = get_max_allowed_leg_desync_seconds(item_tier, item_enchant)
                    if max(abs(sell_age - base_age), abs(sell_age - mat_age)) > max_allowed_desync:
                        continue

                    effective_mat_unit = calculate_effective_price(mat_price, material_qty, mat_vol, is_buy=True)
                    total_mat_cost = effective_mat_unit * material_qty

                    trade_vol = self.default_trade_volume if self.use_slippage else 1
                    effective_base = calculate_effective_price(base_price, trade_vol, base_vol, is_buy=True)
                    effective_sell = calculate_effective_price(sell_price, trade_vol, sell_vol, is_buy=False)

                    # Revenue = sell * (1 - tax - setup_fee)
                    revenue_net = effective_sell * (1.0 - self.tax - self.setup_fee)
                    total_cost = effective_base + total_mat_cost
                    net_profit = revenue_net - total_cost

                    if net_profit < self.min_craft_profit:
                        continue

                    profit_pct = (net_profit / total_cost) * 100
                    # Realistic safe Royal City artifact enchanting margin ceiling (0 loss risk)
                    max_royal_enchant_pct = getattr(settings, "max_royal_enchant_margin_pct", 50.0)
                    if profit_pct > max_royal_enchant_pct or profit_pct < self.min_craft_profit_pct or profit_pct < self.min_roi:
                        continue

                    # Anchor check: ask price cannot be detached from buyer bids
                    if buy_max > 0 and sell_price > (buy_max * 2.5):
                        continue

                    safe_limit = calculate_safe_trade_limit(sell_vol, max_slippage_pct=0.03)

                    opp = EnchantingOpportunity(
                        target_item_id=item_id,
                        target_item_name=item_names.get(item_id, item_id),
                        base_item_id=base_item_id,
                        base_price=effective_base,
                        material_id=material_id,
                        material_qty=material_qty,
                        material_price=effective_mat_unit,
                        bm_buy_price=effective_sell,
                        net_profit=round(net_profit, 0),
                        profit_pct=round(profit_pct, 2),
                        total_cost=total_cost,
                        safe_limit=safe_limit,
                        roi=round((net_profit / total_cost) * 100, 2),
                        profit_margin=round((net_profit / effective_sell) * 100, 2) if effective_sell > 0 else 0.0,
                        quality=quality,
                        base_quality=best_base_quality,
                        data_age_base=base_age,
                        data_age_material=mat_age,
                        data_age_bm=sell_age,
                        data_age_seconds=max(sell_age, base_age, mat_age),
                        base_city=city,
                        sell_city=city,
                    )
                    freshness = max(0.1, 1.0 - (sell_age + base_age) / (get_max_material_age_seconds(item_id) + get_max_material_age_seconds(base_item_id)))
                    vol_score = min(1.0, sell_vol / 50.0) if sell_vol > 0 else 0.2
                    opp.score = round(net_profit * freshness * vol_score, 2)

                    if best_opp_for_city is None or opp.score > best_opp_for_city.score:
                        best_opp_for_city = opp

                if best_opp_for_city:
                    results.append(best_opp_for_city)

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

        # Non-enchantable at Artifact Foundry in Albion Online: Faction & Avalonian Capes (CAPEITEM_), Bag of Insight (_INSIGHT), Royal items, Gathering gear/tools, Consumables, Mounts, Tokens
        base_upper = base_item_id.upper()
        if "CAPEITEM_" in base_upper or any(x in base_upper for x in [
            "_FW_", "CAPE_FW", "_INSIGHT", "BAG_INSIGHT", "ROYAL", "POTION", "FOOD", "MEAL", "SOUP", "STEW", "MOUNT",
            "QUESTITEM", "ARENA_TOKEN", "REWARD_TOKEN", "UNIQUE_SKIN", "TRASH", "STARTER_", "GATHERER", "_TOOL_"
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
        - 2H Weapons & Dual Weapons: 384 per level (16 primary resources * 24)
        - 1H Mainhand Weapons: 288 per level (12 primary resources * 24)
        - Chest Armors & Standard Bags: 192 per level (8 primary resources * 24)
        - Headgear, Footwear, Off-hands & Standard Capes: 96 per level (4 primary resources * 24)
        """
        item_id_upper = item_id.upper()

        # 1. 1-Handed Mainhand Weapons -> 288 (e.g. MAIN_FIRESTAFF, MAIN_HOLYSTAFF, MAIN_SWORD)
        if any(x in item_id_upper for x in ["MAIN_", "MAINHAND", "1H_"]):
            return 288

        # 2. 2-Handed Weapons / Dual Weapons -> 384
        if any(x in item_id_upper for x in [
            "2H_", "_2H", "BOW", "WARBOW", "LONGBOW", "CROSSBOW", "STAFF", "DOUBLE",
            "CLAYMORE", "DUAL", "HALBERD", "SCYTHE", "POLEHAMMER", "FLAIL", "GLAIVE",
            "TRIDENT", "HARPOON", "KATAR", "CLAW", "KNUCKLES", "SHAPESHIFTER", "QUARTERSTAFF"
        ]):
            return 384

        # 3. Chest Armors & Standard Bags -> 192
        if any(x in item_id_upper for x in ["ARMOR", "ROBE", "JACKET", "GARB", "BAG"]):
            return 192

        # 4. Headgear, Footwear, Off-hands & Standard Capes -> 96
        return 96

    def scan_b_arbitrage(
        self,
        prices: dict,
        item_names: dict[str, str],
        recipes: dict = None,
        item_categories: dict[str, str] = None,
        item_values: dict[str, float] = None,
        item_weights: dict[str, float] = None,
    ) -> list[BMOpportunity]:
        """
        Black Market Arbitrage (BM Flip):
        Buy equipment in a Safe Royal City -> Transport through Red Zones to Caerleon -> Sell to Black Market Buy Orders.
        Official Albion Fact: Black Market direct buy order fill has 0% sales tax.
        """
        results = []
        min_vol = max(1, getattr(settings, "anti_bait_min_volume", 1))

        # Black Market ONLY buys equipment (Weapons, Armor, Headgear, Footwear, Off-hands, Capes, Bags, Tools, Mounts)
        for item_id in prices:
            item_upper = item_id.upper()
            is_equipment = any(eq in item_upper for eq in [
                "ARMOR", "ROBE", "JACKET", "GARB", "HEAD", "HELMET", "COWL", "CAP", "SHOES", "BOOTS",
                "MAIN_", "2H_", "1H_", "OFF_", "BAG", "CAPE", "MOUNT", "TOOL", "SPEAR", "SWORD", "AXE",
                "BOW", "CROSSBOW", "HAMMER", "MACE", "DAGGER", "STAFF", "FLAIL", "SCYTHE", "HALBERD",
                "CLAW", "KNUCKLES", "SHAPESHIFTER", "QUARTERSTAFF", "SHIELD", "TORCH", "BOOK", "TOME",
                "HORN", "ORB", "TOTEM", "TALISMAN", "LAMP", "SKULL", "CENSER", "MUISAK", "TAPROOT"
            ])
            if not is_equipment:
                continue

            for quality in [1, 2, 3, 4, 5]:
                # Get BM buy order
                bm_data = self._get_price(prices, item_id, BM_CITY, quality)
                if not bm_data:
                    continue

                bm_price = bm_data.get("buy_price_max", 0)
                bm_age = bm_data.get("data_age_seconds", 9999)

                item_val = item_values.get(item_id, 0.0) if item_values else 0.0
                if not is_bm_price_valid(bm_price, item_val):
                    continue
                max_bm_age = get_max_allowed_bm_age_seconds(item_id, bm_price)
                if bm_age > max_bm_age:
                    continue

                # Find cheapest sell order across the 5 SAFE ROYAL CITIES
                best_buy_city, best_buy_price, best_volume, best_buy_age, best_buy_quality = "", 0, 0, 9999, quality
                
                for q in range(quality, 6):
                    city, price, vol, age = self._cheapest_royal_sell(prices, item_id, q)
                    if price > 0 and age <= get_max_material_age_seconds(item_id):
                        if best_buy_price == 0 or price < best_buy_price:
                            best_buy_city = city
                            best_buy_price = price
                            best_volume = vol
                            best_buy_age = age
                            best_buy_quality = q

                buy_city, buy_price, volume, buy_age = best_buy_city, best_buy_price, best_volume, best_buy_age
                
                if buy_price <= 0 or buy_age > get_max_material_age_seconds(item_id, volume_24h=volume) or (volume > 0 and volume < min_vol):
                    continue

                # Route Travel-Time Expiration Buffer: Target BM buy order must remain alive through player transport run
                travel_buffer = calculate_route_travel_buffer(buy_city, BM_CITY)
                if (max_bm_age - bm_age) < travel_buffer:
                    continue

                # Multi-Leg Desynchronization Guard: Sourced item and target BM buy order must be within aligned time window
                item_tier = int(item_id[1]) if item_id.startswith("T") and len(item_id) > 1 and item_id[1].isdigit() else 4
                if abs(bm_age - buy_age) > get_max_allowed_leg_desync_seconds(item_tier):
                    continue

                # Apply slippage model
                trade_vol = self.default_trade_volume if self.use_slippage else 1
                effective_buy_price = calculate_effective_price(buy_price, trade_vol, volume, is_buy=True)
                effective_bm_price = calculate_effective_price(bm_price, trade_vol, volume, is_buy=False)
                safe_limit = calculate_safe_trade_limit(volume, max_slippage_pct=0.03)

                # Spread check: Do not allow BM prices > 8x royal buy price (unrealistic manipulation)
                if effective_bm_price > effective_buy_price * 8.0:
                    continue

                # Selling to Black Market incurs standard marketplace tax (4% premium, 8% non-premium), but NO setup fee
                revenue_net = effective_bm_price * (1.0 - self.tax)
                net_profit = revenue_net - effective_buy_price
                if net_profit <= 0:
                    continue

                profit_pct = (net_profit / effective_buy_price) * 100
                # Risk-Proportional Absolute Silver Floor for Dangerous Red Zone Routes:
                # E.g. for a 100k item, require at least 20k profit; for 500k, at least 60k profit; for 1M+, at least 120k profit.
                min_profit_silver = max(self.min_bm_profit, int(buy_price * 0.12), 2000)
                if net_profit < min_profit_silver:
                    continue

                dynamic_min_pct = self._dynamic_min_margin(buy_price, is_dangerous=True, default_min=self.min_bm_profit_pct)
                if profit_pct < dynamic_min_pct:
                    continue

                # High profit (>60% ROI) items get filled faster in-game; require fresh data <= 2 hours (7200s)
                if profit_pct > 60.0 and (bm_age > 7200 or buy_age > get_max_material_age_seconds(item_id)):
                    continue

                # Black Market NPC buy order profits are uncapped (authentic NPC payout)

                # Check if item can be crafted cheaper
                can_craft = recipes and (item_id in recipes)
                craft_cost = 0.0
                craft_city = ""
                if can_craft:
                    craft_cost, craft_city = self._estimate_craft_cost(
                        item_id, prices, recipes, item_categories or {}, quality
                    )

                base_id = item_id.split("@")[0]
                weight = 0.0
                if item_weights:
                    weight = item_weights.get(item_id, item_weights.get(base_id, 0.0))
                if weight <= 0.0:
                    from app.core.constants import item_weight
                    weight = item_weight(base_id)

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
                if opp.roi < self.min_roi:
                    continue
                opp.profit_per_kg = round(opp.effective_profit / weight, 2) if weight > 0 else 0.0
                opp.score = self._score_bm(opp)
                results.append(opp)

        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def scan_black_market(self, *args, **kwargs) -> list[BMOpportunity]:
        """Backwards-compatible alias for scan_b_arbitrage."""
        return self.scan_b_arbitrage(*args, **kwargs)

    def scan_b_crafting(
        self,
        prices: dict,
        item_names: dict[str, str],
        recipes: dict,
        item_categories: dict[str, str],
        item_values: dict[str, float],
        item_weights: dict[str, float] = None,
    ) -> list[CraftingOpportunity]:
        """
        Caerleon Crafting -> Black Market:
        Craft equipment in Caerleon from materials bought locally in Caerleon -> Sell to Black Market.
        Zero transport risk, 0% Black Market sales tax.
        """
        results = []
        min_vol = max(1, getattr(settings, "anti_bait_min_volume", 1))

        from app.core.market_utils import get_item_crafting_subcategory

        FARM_KEYWORDS = (
            "_SEED", "_CROP", "_HERB", "_MILK", "_BUTTER", "_EGG", "_FLOUR",
            "_FOAL", "_CALF", "_PIG", "_SHEEP", "_GOAT", "_CHICKEN", "_GOOSE",
            "_CARROT", "_BEAN", "_WHEAT", "_TURNIP", "_CABBAGE", "_POTATO", "_CORN", "_PUMPKIN",
            "_FARM_", "_MEAT", "_STEW", "_SOUP", "_PIE", "_OMELETTE", "_ROAST", "_SANDWICH",
            "_POTION_"
        )

        for item_id, recipe in recipes.items():
            item_id_upper = item_id.upper()
            if any(k in item_id_upper for k in FARM_KEYWORDS):
                continue
            if any(v in item_id_upper for v in ["_ARTEFACT_", "UNIQUE_", "SKIN_", "FURNITURE", "TOKEN", "QUESTITEM", "_NON_TRADABLE", "NONTRADABLE"]):
                continue
            cat = (item_categories.get(item_id, "") or "").lower()
            if cat in ("farming", "crops", "herbs", "livestock", "animals", "consumables", "cooking", "alchemy", "food", "potions"):
                continue

            subcat = get_item_crafting_subcategory(item_id, item_categories.get(item_id, ""))
            category = subcat or item_categories.get(item_id, "")
            caerleon_rrr = rrr(CAERLEON, category, self.use_focus)

            # Sourced in Caerleon only (zero Red Zone transport risk)
            material_cost_gross, ingredient_details, mat_age = self._calc_material_cost(
                item_id, recipe, prices, CAERLEON, quality=1, local_only=True
            )
            if material_cost_gross <= 0:
                continue

            material_cost_net = 0.0
            for ing in ingredient_details:
                if ing.get("is_returnable"):
                    material_cost_net += ing["line_cost"] * (1.0 - caerleon_rrr)
                else:
                    material_cost_net += ing["line_cost"]

            item_val = item_values.get(item_id, 0.0) if item_values else 0.0
            if item_val <= 0:
                item_val = get_fallback_item_value(item_id)
            station_tax = getattr(settings, "station_tax_per_100_nutrition", 500.0)
            station_fee = calculate_station_fee(item_val, station_tax)
            total_cost = material_cost_net + station_fee

            # Sell to Black Market
            bm_data = self._get_price(prices, item_id, BM_CITY, 1)
            if not bm_data:
                continue

            bm_price = bm_data.get("buy_price_max", 0)
            bm_age = bm_data.get("data_age_seconds", 9999)
            bm_vol = bm_data.get("volume_24h", 0)

            max_bm_age = get_max_allowed_bm_age_seconds(item_id, bm_price)
            if bm_price <= 0 or bm_age > max_bm_age or not is_bm_price_valid(bm_price, item_val):
                continue

            trade_vol = self.default_trade_volume if self.use_slippage else 1
            effective_bm_price = calculate_effective_price(bm_price, trade_vol, bm_vol, is_buy=False)
            safe_limit = calculate_safe_trade_limit(bm_vol, max_slippage_pct=0.03)

            # Selling to Black Market incurs standard marketplace tax (4% premium, 8% non-premium), but NO setup fee
            revenue_net = float(effective_bm_price) * (1.0 - self.tax)
            profit = revenue_net - total_cost
            pct = (profit / material_cost_gross * 100) if material_cost_gross > 0 else 0
            roi = (profit / total_cost * 100) if total_cost > 0 else 0

            # Black Market NPC buy order profits are uncapped (authentic NPC payout)

            if profit >= self.min_craft_profit and pct >= 1.0 and roi >= self.min_roi:
                opp = CraftingOpportunity(
                    item_id=item_id,
                    item_name=item_names.get(item_id, item_id),
                    craft_city=CAERLEON,
                    sell_city=BM_CITY,
                    sell_mode="BM",
                    material_cost_gross=round(material_cost_gross, 0),
                    rrr_used=caerleon_rrr,
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
                    is_dangerous=False,
                )
                opp.roi = roi
                weight = item_weights.get(item_id, 0.0) if item_weights else 0.0
                opp.profit_per_kg = round(profit / weight, 2) if weight > 0 else profit
                opp.score = self._score_craft(opp)
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
        Royal City Crafting:
        Craft equipment in Safe Royal Cities (using +15% LPB city bonus) -> Sell on Safe Royal City marketplaces.
        100% Safe Blue/Yellow Continent: Standard marketplace sales tax applies.
        """
        results = []
        min_vol = max(1, getattr(settings, "anti_bait_min_volume", 1))

        from app.core.market_utils import get_item_crafting_subcategory

        FARM_KEYWORDS = (
            "_SEED", "_CROP", "_HERB", "_MILK", "_BUTTER", "_EGG", "_FLOUR",
            "_FOAL", "_CALF", "_PIG", "_SHEEP", "_GOAT", "_CHICKEN", "_GOOSE",
            "_CARROT", "_BEAN", "_WHEAT", "_TURNIP", "_CABBAGE", "_POTATO", "_CORN", "_PUMPKIN",
            "_FARM_", "_MEAT", "_STEW", "_SOUP", "_PIE", "_OMELETTE", "_ROAST", "_SANDWICH",
            "_POTION_"
        )

        for item_id, recipe in recipes.items():
            item_id_upper = item_id.upper()
            if any(k in item_id_upper for k in FARM_KEYWORDS):
                continue
            if any(v in item_id_upper for v in ["_ARTEFACT_", "UNIQUE_", "SKIN_", "FURNITURE", "TOKEN", "QUESTITEM", "_NON_TRADABLE", "NONTRADABLE"]):
                continue
            cat = (item_categories.get(item_id, "") or "").lower()
            if cat in ("farming", "crops", "herbs", "livestock", "animals", "consumables", "cooking", "alchemy", "food", "potions"):
                continue

            subcat = get_item_crafting_subcategory(item_id, item_categories.get(item_id, ""))
            category = subcat or item_categories.get(item_id, "")

            # Sort Royal cities by RRR for this item's category (highest bonus city first)
            candidate_cities = sorted(
                ROYAL_SAFE_CITIES,
                key=lambda c: rrr(c, category, self.use_focus),
                reverse=True
            )

            best_craft_city = candidate_cities[0]
            best_rrr = rrr(best_craft_city, category, self.use_focus)
            material_cost_gross = 0.0
            ingredient_details = []
            mat_age = 0

            for craft_c in candidate_cities:
                c_rrr = rrr(craft_c, category, self.use_focus)
                m_gross, ings, m_age = self._calc_material_cost(
                    item_id, recipe, prices, craft_c, quality=1
                )
                if m_gross > 0:
                    best_craft_city = craft_c
                    best_rrr = c_rrr
                    material_cost_gross = m_gross
                    ingredient_details = ings
                    mat_age = m_age
                    break

            if material_cost_gross <= 0:
                continue

            material_cost_net = 0.0
            for ing in ingredient_details:
                if ing.get("is_returnable"):
                    material_cost_net += ing["line_cost"] * (1.0 - best_rrr)
                else:
                    material_cost_net += ing["line_cost"]

            item_val = item_values.get(item_id, 0.0) if item_values else 0.0
            if item_val <= 0:
                item_val = get_fallback_item_value(item_id)
            station_tax = getattr(settings, "station_tax_per_100_nutrition", 500.0)
            station_fee = calculate_station_fee(item_val, station_tax)
            total_cost = material_cost_net + station_fee

            # Anti-irrational crafting check: is the finished item available cheaper on any Royal market than our total_cost?
            cheaper_pre_crafted = False
            for check_city in ROYAL_SAFE_CITIES:
                p_check = self._get_price(prices, item_id, check_city, 1)
                if p_check:
                    p_sell = p_check.get("sell_price_min", 0)
                    p_buy = p_check.get("buy_price_max", 0)
                    p_vol = p_check.get("volume_24h", 0)
                    p_age = p_check.get("data_age_seconds", 999999)
                    if (
                        p_sell > 0
                        and (p_vol > 0 or self.allow_zero_volume)
                        and is_price_valid(p_sell, p_buy, item_id=item_id)
                        and p_age <= get_max_material_age_seconds(item_id, volume_24h=p_vol)
                    ):
                        if p_sell <= total_cost:
                            cheaper_pre_crafted = True
                            break
            if cheaper_pre_crafted:
                continue

            # Sell in Safe Royal Cities only
            craft_sell_map = {}
            for sell_city in ROYAL_SAFE_CITIES:
                p = self._get_price(prices, item_id, sell_city, 1)
                if p and p.get("sell_price_min", 0) > 0:
                    craft_sell_map[sell_city] = p["sell_price_min"]

            cleaned_craft_sell = cross_city_outlier_check(craft_sell_map)

            best_opp = None
            for sell_city in ROYAL_SAFE_CITIES:
                if cleaned_craft_sell.get(sell_city, 0) == 0:
                    continue

                sell_data = self._get_price(prices, item_id, sell_city, 1)
                if not sell_data:
                    continue
                sell_price = sell_data.get("sell_price_min", 0)
                sell_age = sell_data.get("data_age_seconds", 9999)
                sell_vol = sell_data.get("volume_24h", 0)
                buy_max = sell_data.get("buy_price_max", 0)

                if sell_price <= 0 or sell_age > get_max_material_age_seconds(item_id, volume_24h=sell_vol) or ((not self.allow_zero_volume and sell_vol == 0) or (sell_vol > 0 and sell_vol < min_vol)):
                    continue
                if not is_price_valid(sell_price, buy_max, item_id=item_id):
                    continue

                # Multi-Leg Desynchronization Guard: Finished product sell listing & raw ingredients must be synchronized
                item_tier = int(item_id[1]) if item_id.startswith("T") and len(item_id) > 1 and item_id[1].isdigit() else 4
                if abs(sell_age - mat_age) > get_max_allowed_leg_desync_seconds(item_tier):
                    continue

                # Local sanity: if finished item is already selling cheaper than craft cost in this specific destination city, skip
                if sell_price <= total_cost:
                    continue

                trade_vol = self.default_trade_volume if self.use_slippage else 1
                effective_sell_price = calculate_effective_price(sell_price, trade_vol, sell_vol, is_buy=False)
                safe_limit = calculate_safe_trade_limit(sell_vol, max_slippage_pct=0.03)

                revenue_net = effective_sell_price * (1.0 - self.tax - self.setup_fee)
                profit = revenue_net - total_cost
                pct = (profit / material_cost_gross * 100) if material_cost_gross > 0 else 0
                roi = (profit / total_cost * 100) if total_cost > 0 else 0

                # Realistic safe Royal City crafting margins (0 transport risk) cannot exceed 65%
                max_royal_pct = getattr(settings, "max_royal_craft_margin_pct", 65.0)
                if pct > max_royal_pct or roi > max_royal_pct:
                    continue

                if profit < self.min_craft_profit or pct < self.min_craft_profit_pct or roi < self.min_roi:
                    continue

                # Dead inventory protection: High cost items (>1M silver) require confirmed daily volume
                if total_cost > 1_000_000 and sell_vol < 1 and not self.allow_zero_volume:
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
                weight = item_weights.get(item_id, 0.0) if item_weights else 0.0
                opp.profit_per_kg = round(profit / weight, 2) if weight > 0 else profit
                opp.score = self._score_craft(opp)

                if best_opp is None or opp.score > best_opp.score:
                    best_opp = opp

            if best_opp:
                results.append(best_opp)

        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def scan_island(
        self,
        prices: dict,
        item_names: dict[str, str],
        recipes: dict,
        item_categories: dict[str, str],
        item_values: dict[str, float],
        item_weights: dict[str, float] = None,
    ) -> list[CraftingOpportunity]:
        """
        Scans Island farming, herb gardens, pasture livestock, butcher, meals, and potions.
        Supports official +10% Island Biome Local Production Bonuses per host city.
        Only buy seeds/animals/produce and sell outputs in Safe Royal Cities.
        """
        from app.core.market_utils import get_island_farming_bonus
        results = []
        min_vol = max(1, getattr(settings, "anti_bait_min_volume", 1))

        FARM_KEYWORDS = (
            "_SEED", "_CROP", "_HERB", "_MILK", "_BUTTER", "_EGG", "_FLOUR",
            "_FOAL", "_CALF", "_PIG", "_SHEEP", "_GOAT", "_CHICKEN", "_GOOSE",
            "_CARROT", "_BEAN", "_WHEAT", "_TURNIP", "_CABBAGE", "_POTATO", "_CORN", "_PUMPKIN",
            "_FARM_", "_MEAT", "_STEW", "_SOUP", "_PIE", "_OMELETTE", "_ROAST", "_SANDWICH",
            "_SALAD", "_FISH", "_ALCOHOL", "_EXTRACT", "_BREAD", "_POTION_", "_MEAL_",
            "_MOUNT", "MOUNT_", "_BABY", "_GROWN", "_PUP", "_CUB", "_FAWN", "_CHICK",
            "_GOSLING", "_LAMB", "_PIGLET", "_KID", "_AGARIC", "_COMFREY", "_BURDOCK",
            "_TEASEL", "_FOXGLOVE", "_YARROW", "_MULLEIN"
        )

        island_rrr = 0.37107 if self.use_focus else 0.0  # 0% base, 37.11% with focus

        # Determine island host cities to scan: user configured home city or all Royal Cities
        user_island_city = getattr(settings, "island_home_city", None)
        if user_island_city and user_island_city in ROYAL_SAFE_CITIES:
            target_host_cities = [user_island_city]
        else:
            target_host_cities = ROYAL_SAFE_CITIES

        local_sourcing = getattr(settings, "island_local_sourcing_only", True)

        for item_id, recipe in recipes.items():
            item_id_upper = item_id.upper()
            cat = (item_categories.get(item_id, "") or "").lower()
            is_island = any(k in item_id_upper for k in FARM_KEYWORDS) or cat in (
                "farming", "crops", "herbs", "livestock", "animals", "consumables", "cooking", "alchemy", "food", "potions", "mounts", "mount"
            )
            if not is_island:
                continue

            for island_host_city in target_host_cities:
                # 1. Calculate material cost
                mat_cost, ing_details, mat_age = self._calc_material_cost(
                    item_id, recipe, prices, island_host_city, quality=1, local_only=local_sourcing
                )
                if mat_cost <= 0:
                    continue

                material_cost_gross = mat_cost
                ingredient_details = ing_details

                material_cost_net = 0.0
                for ing in ingredient_details:
                    if ing.get("is_returnable"):
                        material_cost_net += ing["line_cost"] * (1.0 - island_rrr)
                    else:
                        material_cost_net += ing["line_cost"]

                item_val = item_values.get(item_id, 0.0) if item_values else 0.0
                if item_val <= 0:
                    item_val = get_fallback_item_value(item_id)
                station_tax = getattr(settings, "station_tax_per_100_nutrition", 500.0)
                station_fee = calculate_station_fee(item_val, station_tax) if ("_MEAL_" in item_id_upper or "_POTION_" in item_id_upper or "_MEAT" in item_id_upper) else 0.0
                total_cost = material_cost_net + station_fee

                # Biome +10% Yield multiplier (e.g. +10% bonus yield)
                biome_bonus = get_island_farming_bonus(island_host_city, item_id)
                yield_multiplier = 1.0 + biome_bonus

                # Sell in Safe Royal Cities (local island host market or transport to best market)
                island_sell_map = {}
                for sell_city in ROYAL_SAFE_CITIES:
                    p = self._get_price(prices, item_id, sell_city, 1)
                    if p and p.get("sell_price_min", 0) > 0:
                        island_sell_map[sell_city] = p["sell_price_min"]

                cleaned_island_sell = cross_city_outlier_check(island_sell_map)

                best_opp = None
                for sell_city in ROYAL_SAFE_CITIES:
                    if cleaned_island_sell.get(sell_city, 0) == 0:
                        continue

                    sell_data = self._get_price(prices, item_id, sell_city, 1)
                    if not sell_data:
                        continue

                    sell_price = sell_data.get("sell_price_min", 0)
                    sell_age = sell_data.get("data_age_seconds", 9999)
                    sell_vol = sell_data.get("volume_24h", 0)
                    buy_max = sell_data.get("buy_price_max", 0)

                    if sell_price <= 0 or sell_age > get_max_material_age_seconds(item_id, volume_24h=sell_vol) or ((not self.allow_zero_volume and sell_vol == 0) or (sell_vol > 0 and sell_vol < min_vol)):
                        continue
                    if not is_price_valid(sell_price, buy_max, item_id=item_id):
                        continue

                    # Anti-troll bid anchor check: ask price cannot be detached from buyer bids
                    if buy_max > 0 and sell_price > (buy_max * 3.5):
                        continue

                    # High cost liquidity check
                    if total_cost > 50_000 and sell_vol < 1 and not self.allow_zero_volume:
                        continue

                    trade_vol = self.default_trade_volume if self.use_slippage else 1
                    effective_price = calculate_effective_price(sell_price, trade_vol, sell_vol, is_buy=False)
                    safe_limit = calculate_safe_trade_limit(sell_vol, max_slippage_pct=0.03)

                    # Revenue with Biome Bonus Yield: output * (1 + biome_bonus) * (1 - tax - setup)
                    revenue_net = (effective_price * yield_multiplier) * (1.0 - self.tax - self.setup_fee)
                    profit = revenue_net - total_cost
                    pct = (profit / material_cost_gross * 100) if material_cost_gross > 0 else 0
                    roi = (profit / total_cost * 100) if total_cost > 0 else 0

                    # Realistic safe Royal City island farming/potion margins ceiling
                    max_island_roi = getattr(settings, "max_island_roi_pct", 150.0)
                    if pct > max_island_roi or roi > max_island_roi:
                        continue

                    # Allow batch profit scaling (e.g. 100x potion/food batch)
                    if (profit >= self.min_craft_profit or profit * 100 >= self.min_craft_profit) and pct >= 5.0 and roi >= self.min_roi:
                        opp = CraftingOpportunity(
                            item_id=item_id,
                            item_name=item_names.get(item_id, item_id),
                            craft_city=f"Personal Island ({island_host_city})",
                            sell_city=sell_city,
                            sell_mode="MARKET",
                            material_cost_gross=round(material_cost_gross, 0),
                            rrr_used=island_rrr,
                            material_cost_net=round(material_cost_net, 0),
                            station_fee=round(station_fee, 0),
                            sell_price=effective_price,
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
                        weight = item_weights.get(item_id, 0.0) if item_weights else 0.0
                        opp.profit_per_kg = round(profit / weight, 2) if weight > 0 else profit
                        opp.score = self._score_craft(opp)

                        if best_opp is None or opp.score > best_opp.score:
                            best_opp = opp

                if best_opp:
                    results.append(best_opp)

        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def scan_b_refining(
        self,
        prices: dict,
        item_names: dict,
        recipes: dict,
        categories: dict,
        values: dict,
        weights: dict,
    ) -> list[RefiningOpportunity]:
        """
        Caerleon Refining:
        Sourced in Caerleon -> Refined in Caerleon -> Sold on Caerleon marketplace.
        Zero transport risk.
        """
        from app.core.market_utils import calculate_rrr, get_refining_category

        results = []
        min_vol = getattr(settings, "anti_bait_min_volume_materials", 20)

        for item_id, recipe in recipes.items():
            refine_cat = get_refining_category(item_id)
            if not refine_cat:
                continue

            ingredients = recipe.get("ingredients", [])
            if not ingredients:
                continue

            total_material_gross = 0.0
            mat_age = 0
            mat_data_found = True
            ingredients_detail = []

            for ing in ingredients:
                ing_id = ing["item_id"]
                ing_qty = ing["quantity"]

                p = self._get_price(prices, ing_id, CAERLEON, 1)
                if not p:
                    mat_data_found = False
                    break
                sp = p.get("sell_price_min", 0)
                bm = p.get("buy_price_max", 0)
                age = p.get("data_age_seconds", 9999)
                vol = p.get("volume_24h", 0)
                if sp <= 0 or age > get_max_material_age_seconds(ing_id, volume_24h=vol) or (vol > 0 and vol < min_vol) or not is_price_valid(sp, bm, item_id=ing_id):
                    mat_data_found = False
                    break

                total_material_gross += sp * ing_qty
                mat_age = max(mat_age, age)
                ingredients_detail.append({
                    "item_id": ing_id,
                    "name": item_names.get(ing_id, ing_id),
                    "quantity": ing_qty,
                    "unit_price": sp,
                    "buy_city": CAERLEON,
                    "is_returnable": True,
                })

            if not mat_data_found:
                continue

            cae_rrr = calculate_rrr(CAERLEON, refine_cat, 1, self.use_focus)
            material_cost_net = total_material_gross * (1.0 - cae_rrr)
            item_value = values.get(item_id, 0.0)
            station_tax = getattr(settings, "station_tax_per_100_nutrition", 500.0)
            station_fee = calculate_station_fee(item_value, station_tax)
            total_cost = material_cost_net + station_fee

            # Sell in Caerleon
            p_cae = self._get_price(prices, item_id, CAERLEON, 1)
            if not p_cae:
                continue
            c_sp = p_cae.get("sell_price_min", 0)
            c_age = p_cae.get("data_age_seconds", 9999)
            c_vol = p_cae.get("volume_24h", 0)

            if c_sp <= 0 or c_age > get_max_material_age_seconds(item_id, volume_24h=c_vol) or (c_vol > 0 and c_vol < min_vol):
                continue

            # Multi-Leg Desynchronization Guard
            item_tier = int(item_id[1]) if item_id.startswith("T") and len(item_id) > 1 and item_id[1].isdigit() else 4
            if abs(c_age - mat_age) > get_max_allowed_leg_desync_seconds(item_tier):
                continue

            trade_vol = self.default_trade_volume if self.use_slippage else 1
            c_eff = calculate_effective_price(c_sp, trade_vol, c_vol, is_buy=False)
            c_rev = c_eff * (1.0 - self.tax - self.setup_fee)
            c_profit = c_rev - total_cost
            c_profit_pct = (c_profit / total_material_gross * 100) if total_material_gross > 0 else 0
            c_roi = (c_profit / total_cost * 100) if total_cost > 0 else 0

            # Refining batch profit scaling (100x bars)
            if (c_profit >= self.min_craft_profit or c_profit * 100 >= self.min_craft_profit) and c_profit_pct >= 1.0 and c_roi >= self.min_roi:
                weight = weights.get(item_id, 0.0) if weights else 0.0
                profit_per_kg = c_profit / weight if weight > 0 else 0.0
                opp = RefiningOpportunity(
                    item_id=item_id,
                    item_name=item_names.get(item_id, item_id),
                    refine_city=CAERLEON,
                    sell_city=CAERLEON,
                    material_cost_gross=round(total_material_gross, 0),
                    rrr_used=cae_rrr,
                    material_cost_net=round(material_cost_net, 0),
                    station_fee=round(station_fee, 0),
                    sell_price=c_eff,
                    revenue_net=round(c_rev, 0),
                    profit=round(c_profit, 0),
                    profit_pct=round(c_profit_pct, 2),
                    daily_volume=c_vol,
                    data_age_materials=mat_age,
                    data_age_sell=c_age,
                    quality=1,
                    use_focus=self.use_focus,
                    focus_cost=0.0,
                    silver_per_focus=0.0,
                    roi=round(c_roi, 4),
                    profit_per_kg=round(profit_per_kg, 2),
                    safe_limit=calculate_safe_trade_limit(c_vol, max_slippage_pct=0.03),
                    buy_city=CAERLEON,
                    ingredients=ingredients_detail,
                )
                opp.score = self._score_refining(opp)
                results.append(opp)

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
        Royal City Refining:
        Sourced in a single Safe Royal City -> Refined in +40% Refining Bonus City -> Sold on Safe Royal City marketplaces.
        Enforces single-city ingredient sourcing and maximum 2 total cities per refining workflow.
        """
        from app.core.market_utils import calculate_rrr, get_refining_category

        results = []
        min_vol = getattr(settings, "anti_bait_min_volume_materials", 20)
        local_only = getattr(state, "refining_local_sourcing_only", getattr(self, "refining_local_sourcing_only", False))

        for item_id, recipe in recipes.items():
            refine_cat = get_refining_category(item_id)
            if not refine_cat:
                continue

            quality = 1
            ingredients = recipe.get("ingredients", [])
            if not ingredients:
                continue

            # 1. Find best Safe Royal City to refine in (max +40% RRR)
            best_refine_city = ""
            best_rrr = 0.0
            for city in ROYAL_SAFE_CITIES:
                city_rrr = calculate_rrr(city, refine_cat, 1, self.use_focus)
                if city_rrr > best_rrr:
                    best_rrr = city_rrr
                    best_refine_city = city

            if not best_refine_city:
                continue

            item_value = values.get(item_id, 0.0)
            station_tax = getattr(settings, "station_tax_per_100_nutrition", 500.0)
            station_fee = calculate_station_fee(item_value, station_tax)

            # Build sourcing configurations: single-city in each candidate city, plus multi-city optimal sourcing
            candidate_buy_cities = [best_refine_city] if local_only else ROYAL_SAFE_CITIES
            sourcing_configs = []
            for src_city in candidate_buy_cities:
                sourcing_configs.append({"mode": "single", "default_city": src_city})
            if not local_only:
                sourcing_configs.append({"mode": "multi", "default_city": best_refine_city})

            best_opp_for_item: RefiningOpportunity | None = None

            for cfg in sourcing_configs:
                total_material_gross = 0.0
                mat_age = 0
                mat_data_found = True
                ingredients_detail = []
                primary_buy_city = cfg["default_city"]

                for ing in ingredients:
                    ing_id = ing["item_id"]
                    ing_qty = ing["quantity"]

                    if cfg["mode"] == "single":
                        target_cities = [cfg["default_city"]]
                    else:
                        # Multi-city: check best_refine_city first, then cheapest Royal city
                        target_cities = [best_refine_city] + [c for c in ROYAL_SAFE_CITIES if c != best_refine_city]

                    best_sp = 0
                    best_bm = 0
                    best_age = 9999
                    best_vol = 0
                    best_ing_city = ""

                    for c in target_cities:
                        p = self._get_price(prices, ing_id, c, 1)
                        if not p:
                            continue
                        sp = p.get("sell_price_min", 0)
                        bm = p.get("buy_price_max", 0)
                        age = p.get("data_age_seconds", 9999)
                        vol = p.get("volume_24h", 0)

                        if sp > 0 and age <= get_max_material_age_seconds(ing_id, volume_24h=vol) and is_price_valid(sp, bm, item_id=ing_id):
                            if best_sp == 0 or sp < best_sp:
                                best_sp = sp
                                best_bm = bm
                                best_age = age
                                best_vol = vol
                                best_ing_city = c
                                if cfg["mode"] == "single":
                                    break

                    if best_sp <= 0:
                        mat_data_found = False
                        break

                    total_material_gross += best_sp * ing_qty
                    mat_age = max(mat_age, best_age)
                    if cfg["mode"] == "multi" and is_raw_or_refined_material(ing_id) and ("_ORE" in ing_id or "_HIDE" in ing_id or "_WOOD" in ing_id or "_FIBER" in ing_id or "_ROCK" in ing_id):
                        primary_buy_city = best_ing_city
                    ingredients_detail.append({
                        "item_id": ing_id,
                        "name": item_names.get(ing_id, ing_id),
                        "quantity": ing_qty,
                        "unit_price": best_sp,
                        "buy_city": best_ing_city or primary_buy_city,
                        "is_returnable": True,
                    })

                if not mat_data_found or total_material_gross <= 0:
                    continue

                material_cost_net = total_material_gross * (1.0 - best_rrr)
                total_cost = material_cost_net + station_fee

                # Determine allowed destination cities to keep route at <= 2 total cities:
                if primary_buy_city == best_refine_city:
                    candidate_sell_cities = ROYAL_SAFE_CITIES
                else:
                    candidate_sell_cities = [best_refine_city, primary_buy_city]

                sell_price_map = {}
                for sell_city in candidate_sell_cities:
                    p = self._get_price(prices, item_id, sell_city, quality)
                    if p and p.get("sell_price_min", 0) > 0:
                        sell_price_map[sell_city] = p["sell_price_min"]

                cleaned_sell = cross_city_outlier_check(sell_price_map)

                for sell_city in candidate_sell_cities:
                    if cleaned_sell.get(sell_city, 0) == 0:
                        continue

                    p = self._get_price(prices, item_id, sell_city, quality)
                    if not p:
                        continue

                    sell_sp = p.get("sell_price_min", 0)
                    sell_bm = p.get("buy_price_max", 0)
                    sell_age = p.get("data_age_seconds", 9999)
                    sell_vol = p.get("volume_24h", 0)

                    if sell_sp <= 0 or sell_age > get_max_material_age_seconds(item_id, volume_24h=sell_vol) or (sell_vol > 0 and sell_vol < min_vol) or not is_price_valid(sell_sp, sell_bm, item_id=item_id):
                        continue

                    # Multi-Leg Desynchronization Guard
                    item_tier = int(item_id[1]) if item_id.startswith("T") and len(item_id) > 1 and item_id[1].isdigit() else 4
                    if abs(sell_age - mat_age) > get_max_allowed_leg_desync_seconds(item_tier):
                        continue

                    trade_vol = self.default_trade_volume if self.use_slippage else 1
                    effective_sell_price = calculate_effective_price(sell_sp, trade_vol, sell_vol, is_buy=False)
                    safe_limit = calculate_safe_trade_limit(sell_vol, max_slippage_pct=0.03)

                    revenue_net = effective_sell_price * (1.0 - self.tax - self.setup_fee)
                    profit = revenue_net - total_cost
                    profit_pct = (profit / total_material_gross * 100) if total_material_gross > 0 else 0
                    roi = (profit / total_cost * 100) if total_cost > 0 else 0

                    if profit_pct > 100.0:
                        continue

                    # Refining batch profit scaling (100x bars, 3% margin minimum)
                    min_refine_margin = min(self.min_craft_profit_pct, 3.0)
                    if (profit >= self.min_craft_profit or profit * 100 >= self.min_craft_profit) and profit_pct >= min_refine_margin and roi >= self.min_roi:
                        weight = weights.get(item_id, 0.0) if weights else 0.0
                        profit_per_kg = profit / weight if weight > 0 else 0.0

                        opp = RefiningOpportunity(
                            item_id=item_id,
                            item_name=item_names.get(item_id, item_id),
                            refine_city=best_refine_city,
                            sell_city=sell_city,
                            material_cost_gross=round(total_material_gross, 0),
                            rrr_used=best_rrr,
                            material_cost_net=round(material_cost_net, 0),
                            station_fee=round(station_fee, 0),
                            sell_price=effective_sell_price,
                            revenue_net=round(revenue_net, 0),
                            profit=round(profit, 0),
                            profit_pct=round(profit_pct, 2),
                            daily_volume=sell_vol,
                            data_age_materials=mat_age,
                            data_age_sell=sell_age,
                            quality=quality,
                            use_focus=self.use_focus,
                            focus_cost=0.0,
                            silver_per_focus=0.0,
                            roi=round(roi, 4),
                            profit_per_kg=round(profit_per_kg, 2),
                            safe_limit=safe_limit,
                            buy_city=primary_buy_city,
                            ingredients=ingredients_detail,
                        )
                        opp.score = self._score_refining(opp)

                        if best_opp_for_item is None or opp.score > best_opp_for_item.score:
                            best_opp_for_item = opp

            if best_opp_for_item is not None:
                results.append(best_opp_for_item)

        results.sort(key=lambda x: x.score, reverse=True)
        return results

        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def scan_arbitrage(
        self,
        prices: dict,
        item_names: dict[str, str],
        item_weights: dict[str, float] = None,
    ) -> list[ArbitrageOpportunity]:
        """
        Royal City Arbitrage:
        Buy at sell_price_min in Safe Royal City A -> Sell at buy_price_max in Safe Royal City B.
        100% Safe Blue/Yellow routes. Standard marketplace sales tax applies.
        """
        results = []
        seen = set()
        min_vol = max(1, getattr(settings, "anti_bait_min_volume", 1))

        for item_id in prices:
            for quality in [1, 2, 3, 4, 5]:
                sources = []
                for city in ROYAL_SAFE_CITIES:
                    p = self._get_price(prices, item_id, city, quality)
                    if not p:
                        continue
                    sell_min = p.get("sell_price_min", 0)
                    buy_max = p.get("buy_price_max", 0)
                    age = p.get("data_age_seconds", 9999)
                    if sell_min <= 0 or age > get_max_material_age_seconds(item_id):
                        continue
                    if not is_price_valid(sell_min, buy_max, item_id=item_id):
                        continue
                    sources.append((city, sell_min, p.get("volume_24h", 0), age))

                if not sources:
                    continue

                src_price_map = {c: p for c, p, _, _ in sources}
                cleaned_src = cross_city_outlier_check(src_price_map)

                dest_price_map = {}
                for city in ROYAL_SAFE_CITIES:
                    d = self._get_price(prices, item_id, city, quality)
                    if d and d.get("buy_price_max", 0) > 0:
                        dest_price_map[city] = d["buy_price_max"]
                cleaned_dest = cross_city_outlier_check(dest_price_map)

                for src_city, src_sell, src_vol, src_age in sources:
                    if cleaned_src.get(src_city, 0) == 0:
                        continue

                    for dest_city in ROYAL_SAFE_CITIES:
                        if dest_city == src_city:
                            continue
                        if cleaned_dest.get(dest_city, 0) == 0:
                            continue

                        dest_data = self._get_price(prices, item_id, dest_city, quality)
                        if not dest_data:
                            continue

                        dest_buy_max = dest_data.get("buy_price_max", 0)
                        dest_age = dest_data.get("data_age_seconds", 9999)
                        dest_vol = dest_data.get("volume_24h", 0)

                        if dest_buy_max <= 0 or (dest_vol > 0 and dest_vol < min_vol) or dest_age > get_max_material_age_seconds(item_id, volume_24h=dest_vol):
                            continue

                        # Route Travel-Time Expiration Buffer & Leg Synchronization
                        travel_buffer = calculate_route_travel_buffer(src_city, dest_city)
                        dest_max_age = get_max_material_age_seconds(item_id, volume_24h=dest_vol)
                        if (dest_max_age - dest_age) < travel_buffer:
                            continue

                        item_tier = int(item_id[1]) if item_id.startswith("T") and len(item_id) > 1 and item_id[1].isdigit() else 4
                        if abs(dest_age - src_age) > get_max_allowed_leg_desync_seconds(item_tier):
                            continue

                        daily_vol = min(src_vol, dest_vol) if dest_vol > 0 else src_vol
                        trade_vol = self.default_trade_volume if self.use_slippage else 1
                        effective_src_sell = calculate_effective_price(src_sell, trade_vol, daily_vol, is_buy=True)
                        effective_dest_buy_max = calculate_effective_price(dest_buy_max, trade_vol, daily_vol, is_buy=False)
                        safe_limit = calculate_safe_trade_limit(daily_vol, max_slippage_pct=0.03)

                        revenue = effective_dest_buy_max * (1.0 - self.tax)
                        net_profit = revenue - effective_src_sell
                        pct = (net_profit / effective_src_sell * 100) if effective_src_sell > 0 else 0
                        roi = (net_profit / effective_src_sell * 100) if effective_src_sell > 0 else 0

                        is_danger = (src_city == CAERLEON or dest_city == CAERLEON)
                        min_profit_floor = max(self.min_arb_profit, int(src_sell * 0.12), 2000) if is_danger else self.min_arb_profit
                        if net_profit < min_profit_floor or pct > 60.0:
                            continue

                        dynamic_min_pct = self._dynamic_min_margin(src_sell, is_dangerous=is_danger, default_min=self.min_arb_profit_pct)
                        if pct < dynamic_min_pct or roi < self.min_roi:
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
                            gross_profit=effective_dest_buy_max - effective_src_sell,
                            tax_paid=round(effective_dest_buy_max * self.tax, 0),
                            net_profit=round(net_profit, 0),
                            profit_pct=round(pct, 2),
                            daily_volume=daily_vol,
                            data_age_buy=src_age,
                            data_age_sell=dest_age,
                            is_dangerous_route=False,
                            quality=quality,
                            safe_limit=safe_limit,
                        )
                        opp.roi = round(roi, 2)
                        weight = item_weights.get(item_id, 0.0) if item_weights else 0.0
                        opp.profit_per_kg = round(net_profit / weight, 2) if weight > 0 else net_profit
                        opp.score = self._score_arb(opp)
                        results.append(opp)

        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def scan_b_market_making(
        self, prices: dict, item_names: dict, item_categories: dict, item_weights: dict = None
    ) -> list[MarketMakingOpportunity]:
        """
        Caerleon Market Making (Intra-Caerleon Spread Capture):
        Place Buy Orders and undercut Sell Orders exclusively in Caerleon with confirmed liquidity.
        """
        results = []
        min_volume = max(1, getattr(settings, "anti_bait_min_volume", 1))

        for item_id, city_data in prices.items():
            if CAERLEON not in city_data:
                continue

            for quality in [1, 2, 3, 4, 5]:
                p = self._get_price(prices, item_id, CAERLEON, quality)
                if not p:
                    continue

                bm = p.get("buy_price_max", 0)
                sp = p.get("sell_price_min", 0)
                vol = p.get("volume_24h", 0)
                age = p.get("data_age_seconds", 9999)

                if sp <= 0 or bm <= 0 or age > get_max_material_age_seconds(item_id, context="market_making"):
                    continue
                if not is_price_valid(sp, bm, daily_volume=vol, item_id=item_id):
                    continue

                effective_buy_price = bm + 1
                effective_sell_price = sp - 1
                if effective_buy_price >= effective_sell_price:
                    continue

                # Strict High-Confidence Volume Filter (guaranteed to fill & sell)
                if not self.allow_zero_volume:
                    req_vol = 20 if effective_buy_price < 50_000 else (10 if effective_buy_price < 300_000 else 5)
                    if vol < req_vol:
                        continue
                elif vol > 0 and vol < min_volume:
                    continue

                buy_setup_fee = effective_buy_price * self.setup_fee
                sell_setup_fee = effective_sell_price * self.setup_fee
                tax_paid = effective_sell_price * self.tax
                total_fees = buy_setup_fee + sell_setup_fee + tax_paid
                gross_profit = effective_sell_price - effective_buy_price
                net_profit = gross_profit - total_fees
                capital_required = effective_buy_price + buy_setup_fee + sell_setup_fee
                pct = (net_profit / capital_required * 100) if capital_required > 0 else 0.0

                spread_ratio = effective_sell_price / effective_buy_price if effective_buy_price > 0 else 99.0
                if spread_ratio > 1.60 or pct > 45.0 or net_profit < 2000 or pct < 3.0:
                    continue

                opp = MarketMakingOpportunity(
                    item_id=item_id,
                    item_name=item_names.get(item_id, item_id),
                    source_city=CAERLEON,
                    destination_city=CAERLEON,
                    buy_price=effective_buy_price,
                    sell_price=effective_sell_price,
                    gross_profit=gross_profit,
                    setup_fees=round(buy_setup_fee + sell_setup_fee, 0),
                    tax_paid=round(tax_paid, 0),
                    net_profit=round(net_profit, 0),
                    profit_pct=round(pct, 2),
                    daily_volume=vol,
                    data_age_buy=age,
                    data_age_sell=age,
                    is_dangerous_route=False,
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

        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def scan_market_making(
        self, prices: dict, item_names: dict, item_categories: dict, item_weights: dict = None
    ) -> list[MarketMakingOpportunity]:
        """
        Royal City Station Market Making:
        Intra-Station spread capture inside Safe Royal Cities (same city buy order + sell order).
        Zero transport risk, pure local orderbook execution with verified daily liquidity.
        """
        results = []
        min_volume = max(1, getattr(settings, "anti_bait_min_volume", 1))

        for item_id, city_data in prices.items():
            valid_cities = [c for c in city_data.keys() if c in ROYAL_SAFE_CITIES]

            for city in valid_cities:
                for quality in [1, 2, 3, 4, 5]:
                    p = self._get_price(prices, item_id, city, quality)
                    if not p:
                        continue

                    bm = p.get("buy_price_max", 0)
                    sp = p.get("sell_price_min", 0)
                    vol = p.get("volume_24h", 0)
                    age = p.get("data_age_seconds", 9999)

                    if sp <= 0 or bm <= 0 or age > get_max_material_age_seconds(item_id, context="market_making"):
                        continue
                    if not is_price_valid(sp, bm, daily_volume=vol, item_id=item_id):
                        continue

                    effective_buy_price = bm + 1
                    effective_sell_price = sp - 1
                    if effective_buy_price >= effective_sell_price:
                        continue

                    # Strict High-Confidence Volume Filter (guaranteed to fill & sell)
                    if not self.allow_zero_volume:
                        req_vol = 20 if effective_buy_price < 50_000 else (10 if effective_buy_price < 300_000 else 5)
                        if vol < req_vol:
                            continue
                    elif vol > 0 and vol < min_volume:
                        continue

                    buy_setup_fee = effective_buy_price * self.setup_fee
                    sell_setup_fee = effective_sell_price * self.setup_fee
                    tax_paid = effective_sell_price * self.tax
                    total_fees = buy_setup_fee + sell_setup_fee + tax_paid
                    gross_profit = effective_sell_price - effective_buy_price
                    net_profit = gross_profit - total_fees
                    capital_required = effective_buy_price + buy_setup_fee + sell_setup_fee
                    pct = (net_profit / capital_required * 100) if capital_required > 0 else 0.0

                    spread_ratio = effective_sell_price / effective_buy_price if effective_buy_price > 0 else 99.0
                    if spread_ratio > 1.60 or pct > 45.0 or net_profit < 2000 or pct < 3.0:
                        continue

                    opp = MarketMakingOpportunity(
                        item_id=item_id,
                        item_name=item_names.get(item_id, item_id),
                        source_city=city,
                        destination_city=city,
                        buy_price=effective_buy_price,
                        sell_price=effective_sell_price,
                        gross_profit=gross_profit,
                        setup_fees=round(buy_setup_fee + sell_setup_fee, 0),
                        tax_paid=round(tax_paid, 0),
                        net_profit=round(net_profit, 0),
                        profit_pct=round(pct, 2),
                        daily_volume=vol,
                        data_age_buy=age,
                        data_age_sell=age,
                        is_dangerous_route=False,
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
        Quick craft cost estimate for opportunity display.
        Returns (total_cost_after_rrr, best_craft_city).
        """
        recipe = recipes.get(item_id)
        if not recipe:
            return (0.0, "")

        category = item_categories.get(item_id, "")
        best_rrr = -1.0
        best_craft_city = "Martlock"
        for city in ROYAL_SAFE_CITIES:
            r = rrr(city, category, self.use_focus)
            if r > best_rrr:
                best_rrr = r
                best_craft_city = city

        gross_cost, ingredients, _ = self._calc_material_cost(
            item_id, recipe, prices, best_craft_city, quality=1
        )
        if gross_cost <= 0:
            return (0.0, "")

        net_cost = 0.0
        for ing in ingredients:
            if ing.get("is_returnable"):
                net_cost += ing["line_cost"] * (1.0 - best_rrr)
            else:
                net_cost += ing["line_cost"]

        item_val = get_fallback_item_value(item_id)
        station_tax = getattr(settings, "station_tax_per_100_nutrition", 500.0)
        station_fee = calculate_station_fee(item_val, station_tax)

        return (round(net_cost + station_fee, 0), best_craft_city)

    def _calc_material_cost(
        self,
        item_id: str,
        recipe: dict,
        prices: dict,
        craft_city: str,
        quality: int = 1,
        local_only: bool | None = None,
    ) -> tuple[float, list[dict], int]:
        """
        Sum up ingredient costs realistically:
        1. Sourced locally in `craft_city`.
        2. For refined materials (Planks, Bars, Leather, Cloth, Stone), if not in `craft_city`,
           source from its dedicated +40% Refining Bonus City.
        3. For Caerleon crafting, all ingredients MUST be sourced locally in Caerleon.
        """
        total = 0.0
        ingredients = []
        max_age = 0

        # Check dynamic override from state if available
        if local_only is None:
            local_only = self.crafting_local_sourcing_only
            if local_only is None:
                from app.core import state
                local_only = getattr(state, "crafting_local_sourcing_only", True)

        # Refining bonus city map for single-ingredient fallback
        REFINING_BONUS_CITIES = {
            "PLANKS": "Fort Sterling",
            "WOOD": "Fort Sterling",
            "METALBAR": "Thetford",
            "BAR": "Thetford",
            "ORE": "Thetford",
            "LEATHER": "Martlock",
            "HIDE": "Martlock",
            "CLOTH": "Lymhurst",
            "FIBER": "Lymhurst",
            "STONEBLOCK": "Bridgewatch",
            "BLOCK": "Bridgewatch",
            "ROCK": "Bridgewatch",
        }

        for ing in recipe.get("ingredients", []):
            ing_id = ing["item_id"]
            qty = ing["quantity"]

            best_price = 0
            best_city = ""
            best_age = 9999

            # Strict 3-Hour Freshness Limit for Ores/Hides/Bars/Planks/Raw/Refined materials
            is_mat = is_raw_or_refined_material(ing_id)
            max_allowed_ing_age = get_max_material_age_seconds(ing_id)

            # 1. Try craft_city local market
            p_local = self._get_price(prices, ing_id, craft_city, 1)
            min_p = get_min_realistic_price(ing_id)
            if p_local and p_local.get("sell_price_min", 0) > 0 and p_local.get("data_age_seconds", 9999) <= max_allowed_ing_age:
                sp = p_local["sell_price_min"]
                bm = p_local.get("buy_price_max", 0)
                if is_price_valid(sp, bm, item_id=ing_id):
                    best_price = sp
                    best_city = craft_city
                    best_age = p_local.get("data_age_seconds", 9999)
                elif sp < min_p and craft_city == CAERLEON:
                    royal_med = self._get_royal_median_sell(prices, ing_id, 1)
                    if royal_med >= min_p:
                        best_price = royal_med
                        best_city = craft_city
                        best_age = p_local.get("data_age_seconds", 9999)

            # 2. Dedicated Refining Bonus City fallback (for refined materials if not in local market, Safe Royal only)
            if best_price <= 0 and craft_city != CAERLEON:
                ing_upper = ing_id.upper()
                target_refine_city = None
                for ref_key, target_city in REFINING_BONUS_CITIES.items():
                    if ref_key in ing_upper:
                        target_refine_city = target_city
                        break

                if target_refine_city and target_refine_city != craft_city:
                    p_ref = self._get_price(prices, ing_id, target_refine_city, 1)
                    if p_ref and p_ref.get("sell_price_min", 0) > 0 and p_ref.get("data_age_seconds", 9999) <= max_allowed_ing_age:
                        sp = p_ref["sell_price_min"]
                        bm = p_ref.get("buy_price_max", 0)
                        if is_price_valid(sp, bm, item_id=ing_id):
                            best_price = sp
                            best_city = target_refine_city
                            best_age = p_ref.get("data_age_seconds", 9999)

            # 3. If still missing and local_only is False, check cheapest across other Safe Royal Cities
            if best_price <= 0 and craft_city != CAERLEON and not local_only:
                r_city, r_price, _, r_age = self._cheapest_royal_sell(prices, ing_id, 1)
                if r_price > 0 and r_age <= max_allowed_ing_age:
                    best_price = r_price
                    best_city = r_city
                    best_age = r_age

            if best_price <= 0:
                return (0.0, [], 0)

            line_cost = best_price * qty
            total += line_cost
            max_age = max(max_age, best_age)

            is_returnable = False
            if "ARTIFACT" not in ing_id:
                if any(r in ing_id for r in ["PLANKS", "CLOTH", "LEATHER", "BAR", "METALBAR", "WOOD", "ORE", "HIDE", "FIBER", "ROCK", "STONE", "BLOCK"]):
                    is_returnable = True

            ingredients.append({
                "item_id": ing_id,
                "quantity": qty,
                "unit_price": best_price,
                "buy_city": best_city,
                "line_cost": round(line_cost, 0),
                "is_returnable": is_returnable,
            })

        return (total, ingredients, max_age)

    def scan_quality_inversions(
        self,
        prices: dict,
        item_names: dict[str, str],
    ) -> list[QualityInversionOpportunity]:
        """
        Scans for quality mispricings within each city.
        """
        from app.features.quality_arbitrage import detect_quality_inversion

        results = []
        min_vol = getattr(settings, "anti_bait_min_volume", 1)
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
                    tax_rate=self.tax,
                    setup_fee_rate=self.setup_fee,
                    min_volume=min_vol,
                    allow_zero_volume=self.allow_zero_volume,
                )
                for inv in invs:
                    vol = inv["daily_volume"]
                    limit = calculate_safe_trade_limit(vol, default_limit=1)
                    score = round(inv["net_profit"] * (vol / 50.0 + 0.1), 2) if vol > 0 else 0.0
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
                        score=score,
                    )
                    results.append(opp)

        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def scan_transmutation(
        self,
        prices: dict,
        item_names: dict[str, str],
    ) -> list[TransmutationOpportunity]:
        """
        Scans for profitable Transmutator station flips in Safe Royal Cities.
        Supports both Raw Materials and Refined Materials for:
        1. Tier Transmutation (T(N-1) -> T(N) at same enchantment)
        2. Enchantment Transmutation (.(E-1) -> .(E) at same tier)
        Only in Safe Royal Cities, sell in same Safe Royal City.
        Cost = Source Price + Official Silver Transmutation Fee.
        """
        results = []
        tier_fees = {
            (4, 5): 781, (5, 6): 1250, (6, 7): 2500, (7, 8): 5000,
        }
        enchant_fees = {
            (4, 1): 1500, (4, 2): 3000, (4, 3): 6000, (4, 4): 24012,
            (5, 1): 2000, (5, 2): 4000, (5, 3): 8000, (5, 4): 32014,
            (6, 1): 3000, (6, 2): 6000, (6, 3): 19800, (6, 4): 79234,
            (7, 1): 4800, (7, 2): 15126, (7, 3): 49916, (7, 4): 199673,
            (8, 1): 14401, (8, 2): 45378, (8, 3): 149748, (8, 4): 748755,
        }

        min_vol = getattr(settings, "anti_bait_min_volume_materials", 20)

        for item_id, city_map in prices.items():
            parsed = parse_transmutable_resource(item_id)
            if not parsed:
                continue

            tier, res_type, enchant, is_raw = parsed
            item_name = item_names.get(item_id, item_id)

            candidate_paths = []

            # 1. Tier Upgrades (e.g. T4 -> T5, T4.1 -> T5.1)
            if tier > 4:
                prev_tier = tier - 1
                source_id = make_resource_id(prev_tier, res_type, enchant)
                base_fee = tier_fees.get((prev_tier, tier), 2500)
                fee = base_fee * (2 ** enchant) if enchant > 0 else base_fee
                candidate_paths.append((source_id, fee, "tier"))

            # 2. Enchantment Upgrades (e.g. .0 -> .1, .1 -> .2)
            if enchant > 0 and res_type not in {"ROCK", "STONEBLOCK"}:
                prev_enchant = enchant - 1
                source_id = make_resource_id(tier, res_type, prev_enchant)
                fee = enchant_fees.get((tier, enchant), 5000)
                candidate_paths.append((source_id, fee, "enchant"))

            for source_id, fee, path_type in candidate_paths:
                source_name = item_names.get(source_id, source_id)

                # Safe Royal Cities only
                for city in ROYAL_SAFE_CITIES:
                    src_data = self._get_price(prices, source_id, city, 1)
                    dest_data = self._get_price(prices, item_id, city, 1)
                    if not src_data or not dest_data:
                        continue

                    src_sp = src_data.get("sell_price_min", 0)
                    src_age = src_data.get("data_age_seconds", 9999)
                    dest_sp = dest_data.get("sell_price_min", 0)
                    dest_age = dest_data.get("data_age_seconds", 9999)
                    vol = dest_data.get("volume_24h", 0)

                    if src_sp <= 0 or dest_sp <= 0 or src_age > get_max_material_age_seconds(source_id) or dest_age > get_max_material_age_seconds(item_id):
                        continue

                    if not self.allow_zero_volume and vol < min_vol:
                        continue

                    dest_bm = dest_data.get("buy_price_max", 0)
                    if not is_price_valid(dest_sp, dest_bm, vol, item_id=item_id):
                        continue
                    if not is_price_valid(src_sp, src_data.get("buy_price_max", 0), src_data.get("volume_24h", 0), item_id=source_id):
                        continue

                    total_cost = src_sp + fee
                    net_revenue = dest_sp * (1.0 - self.tax - self.setup_fee)
                    net_profit = net_revenue - total_cost

                    if net_profit <= 0:
                        continue

                    safe_limit = calculate_safe_trade_limit(vol, default_limit=10)
                    batch_profit = net_profit * safe_limit

                    # Material flips trade in batches; check both unit profit and batch profit
                    if net_profit < self.min_arb_profit and batch_profit < self.min_arb_profit:
                        continue

                    profit_margin = (net_profit / dest_sp * 100.0) if dest_sp > 0 else 0.0
                    roi = (net_profit / total_cost * 100.0) if total_cost > 0 else 0.0

                    min_transmute_roi = max(self.min_roi, 5.0)
                    if roi < min_transmute_roi or profit_margin < 3.5 or net_profit < 30.0:
                        continue
                    if roi > 60.0 or profit_margin > 45.0:
                        continue

                    # Bid anchor check: dest sell price cannot be detached from buy order
                    if dest_bm > 0 and dest_sp > (dest_bm * 2.5):
                        continue

                    roi_factor = min(2.5, max(0.1, roi / 10.0))
                    score = round(net_profit * roi_factor * (vol / 50.0 + 0.1), 2) if vol > 0 else net_profit

                    opp = TransmutationOpportunity(
                        item_id=item_id,
                        item_name=item_name,
                        source_item_id=source_id,
                        source_item_name=source_name,
                        source_price=src_sp,
                        transmutation_fee=fee,
                        total_cost=int(total_cost),
                        sell_price=dest_sp,
                        sell_city=city,
                        net_profit=int(net_profit),
                        profit_pct=round(profit_margin, 2),
                        roi=round(roi, 2),
                        daily_volume=vol,
                        data_age_source=src_age,
                        data_age_sell=dest_age,
                        safe_limit=safe_limit,
                        score=score,
                        source_city=city,
                    )
                    results.append(opp)

        results.sort(key=lambda x: x.score, reverse=True)
        return results
