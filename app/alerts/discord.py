"""
Discord Alert System for Albion Quant v3.0.
Sends formatted alerts via Discord webhooks with regional server context.
"""

import asyncio
from datetime import datetime

import httpx

from app.core.config import settings
from app.core.icons import item_icon_url
from app.core.logging import log
from app.core.scoring import scorer

RISK_LABELS = {
    (0.0, 0.15): "🟢 LOW",
    (0.15, 0.30): "🟡 MEDIUM",
    (0.30, 0.50): "🟠 HIGH",
    (0.50, 1.01): "🔴 EXTREME",
}

SERVER_BADGES = {
    "west": "🇺🇸 [WEST]",
    "east": "🇸🇬 [ASIA]",
    "europe": "🇪🇺 [EUROPE]",
}


def _risk_label(score: float) -> str:
    for (lo, hi), label in RISK_LABELS.items():
        if lo <= score < hi:
            return label
    return "⚪ UNKNOWN"


def fmt_k(n: float) -> str:
    if n is None:
        return "0"
    if n >= 1000000:
        return f"{n/1000000:.2f}M"
    if n >= 1000:
        return f"{n/1000:.1f}k".replace(".0k", "k")
    return f"{n:,.0f}"


def _get_category_group(item_id: str) -> str:
    id_upper = item_id.upper()
    if any(k in id_upper for k in ["TREASURE", "JOURNAL", "DUNGEON", "HELLGATE", "CORRUPTED", "MAP"]):
        return "Treasures & Journals"
    if any(k in id_upper for k in ["POTION", "FOOD", "MEAL", "SOUP", "STEW", "PIE", "OMELETTE", "ROAST"]):
        return "Consumables"

    # Prioritize Equipment check so leather/cloth armors are categorized as Equipment
    if any(eq in id_upper for eq in [
        "ARMOR", "ROBE", "JACKET", "GARB", "HEAD", "HELMET", "COWL", "CAP", "SHOES", "BOOTS",
        "MAIN_", "2H_", "OFF_", "BAG", "CAPE", "MOUNT", "KNUCKLES", "SHAPESHIFTER"
    ]):
        return "Equipment"

    if any(
        k in id_upper
        for k in [
            "WOOD",
            "ORE",
            "FIBER",
            "HIDE",
            "ROCK",
            "BAR",
            "PLANK",
            "CLOTH",
            "LEATHER",
            "STONE",
            "RUNE",
            "SOUL",
            "RELIC",
        ]
    ):
        return "Resources"
    return "Equipment"

def _fmt_age(seconds: int) -> str:
    if not seconds or seconds <= 0:
        return "<1m ago"
    if seconds < 60:
        return f"{int(seconds)}s ago"
    minutes = int(seconds) // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    rem_m = minutes % 60
    return f"{hours}h {rem_m}m ago"


def _premium_badge(opp: dict) -> str:
    is_prem = opp.get("is_premium", getattr(settings, "is_premium", False))
    fallback_tax = settings.market_tax_premium_pct if is_prem else settings.market_tax_non_premium_pct
    tax_pct = (opp.get("tax_rate", fallback_tax)) * 100.0
    if is_prem:
        return f"👑 Premium ({tax_pct:.1f}% Tax)"
    return f"🛡️ Non-Premium ({tax_pct:.1f}% Tax)"



def _get_true_margin(opp: dict) -> float:
    raw_margin = opp.get("profit_margin")
    roi = opp.get("roi", opp.get("profit_pct"))
    if raw_margin is not None and raw_margin != roi and raw_margin > 0:
        return float(raw_margin)
    sell_price = opp.get("sell_price", opp.get("bm_buy_price", 0))
    profit = opp.get("estimated_profit", opp.get("net_profit", opp.get("profit", 0)))
    if sell_price > 0 and profit != 0:
        return round((profit / sell_price) * 100.0, 2)
    return float(raw_margin or roi or 0.0)


ISLAND_CATEGORIES = {
    "farming", "crops", "herbs", "livestock", "animals", "mounts", "mount",
    "animal", "consumables", "cooking", "alchemy", "food", "potions", "journals", "farm",
    "pasture", "kennel", "kennels"
}

ISLAND_ITEM_KEYWORDS = [
    # Food, Alchemy & Farming Crops
    "_MEAL_", "_POTION_", "_SEED", "_CROP", "_HERB", "_MILK", "_BUTTER",
    "_EGG", "_FLOUR", "_BREAD", "_STEW", "_OMELETTE", "_PIE", "_SOUP",
    "_ROAST", "_SANDWICH", "_JOURNAL_", "_CARROT", "_BEAN", "_WHEAT",
    "_TURNIP", "_CABBAGE", "_POTATO", "_CORN", "_PUMPKIN", "_CHAMOMILE",
    "_FOXGLOVE", "_FIRETEAR", "_GRENTHISTLE", "_MULLEIN", "_CREEPING_CANDLE",
    "_GHOUL_YARROW", "_FARM_", "_MEAT", "FARM_CHICKEN", "FARM_PIG", "FARM_COW",
    "FARM_SHEEP", "FARM_GOOSE", "FARM_GOAT",

    # Baby Animals & Growth (Breeding / Pasture / Kennel)
    "_BABY", "_GROWN", "_FOAL", "_CALF", "_PUP", "_CUB", "_FAWN", "_CHICK",
    "_GOSLING", "_LAMB", "_PIGLET", "_KID",

    # Mounts & Livestock (Saddled / Farm-Raised / Bred)
    "_HORSE", "_OX", "_SWIFTCLAW", "_DIREWOLF", "_DIREBEAR", "_DIREBOAR",
    "_GIANTSTAG", "_STAG", "_MAMMOTH", "_SWAMPDRAGON", "_MOABIRD", "_COUGAR",
    "_TERRORBIRD", "_RAVEN", "_ARMORED_HORSE", "_MOUNT_", "MOUNT_", "_MOUNT",
    "_MULE", "_DONKEY", "COTTONTAIL", "RABBIT", "BUNNY", "PANTHER", "WILD_BOAR",
    "BOAR", "FROSTRAM", "OWL", "SALAMANDER", "SWAMP_DRAGON"
]


def _is_island_opportunity(opp: dict) -> bool:
    cat = (opp.get("category") or "").lower()
    subcat = (opp.get("subcategory") or "").lower()
    if cat in ISLAND_CATEGORIES or subcat in ISLAND_CATEGORIES:
        return True
    item_id = (opp.get("item_id") or "").upper()
    item_name = (opp.get("item_name") or "").upper()
    if any(kw in item_id for kw in ISLAND_ITEM_KEYWORDS):
        return True
    if any(kw.replace("_", " ").strip() in item_name for kw in ISLAND_ITEM_KEYWORDS if len(kw) > 3):
        return True
    return False



class DiscordAlerter:
    def __init__(self):
        import os
        self.webhook_url = settings.discord_webhook_url or os.getenv("DISCORD_WEBHOOK_URL", "")
        self.arb_webhook_url = settings.discord_arb_webhook_url or os.getenv("DISCORD_ARB_WEBHOOK_URL", "") or os.getenv("DISCORD_ARBITRAGE_WEBHOOK_URL", "")
        self.bm_webhook_url = settings.discord_bm_webhook_url or os.getenv("DISCORD_BM_WEBHOOK_URL", "")
        self.bm_arb_webhook_url = settings.discord_bm_arb_webhook_url or os.getenv("DISCORD_BM_ARB_WEBHOOK_URL", "") or os.getenv("DISCORD_BM_ARBITRAGE_WEBHOOK_URL", "") or os.getenv("DISCORD_B_ARB_WEBHOOK_URL", "")
        self.crafting_webhook_url = settings.discord_crafting_webhook_url or os.getenv("DISCORD_CRAFTING_WEBHOOK_URL", "")
        self.bm_crafting_webhook_url = settings.discord_bm_crafting_webhook_url or os.getenv("DISCORD_BM_CRAFTING_WEBHOOK_URL", "") or os.getenv("DISCORD_B_CRAFTING_WEBHOOK_URL", "")
        self.refining_webhook_url = settings.discord_refining_webhook_url or os.getenv("DISCORD_REFINING_WEBHOOK_URL", "")
        self.bm_refining_webhook_url = settings.discord_bm_refining_webhook_url or os.getenv("DISCORD_BM_REFINING_WEBHOOK_URL", "") or os.getenv("DISCORD_B_REFINING_WEBHOOK_URL", "")
        self.enchanting_webhook_url = settings.discord_enchanting_webhook_url or os.getenv("DISCORD_ENCHANTING_WEBHOOK_URL", "")
        self.bm_enchanting_webhook_url = settings.discord_bm_enchanting_webhook_url or os.getenv("DISCORD_BM_ENCHANTING_WEBHOOK_URL", "") or os.getenv("DISCORD_B_ENCHANTING_WEBHOOK_URL", "")
        self.mm_webhook_url = settings.discord_mm_webhook_url or os.getenv("DISCORD_MM_WEBHOOK_URL", "")
        self.bm_mm_webhook_url = settings.discord_bm_mm_webhook_url or os.getenv("DISCORD_BM_MM_WEBHOOK_URL", "") or os.getenv("DISCORD_B_MM_WEBHOOK_URL", "")
        self.island_webhook_url = settings.discord_island_webhook_url or os.getenv("DISCORD_ISLAND_WEBHOOK_URL", "") or os.getenv("DISCORD_ISLAND_URL", "")
        self.quality_webhook_url = settings.discord_quality_webhook_url or os.getenv("DISCORD_QUALITY_WEBHOOK_URL", "")
        self.transmute_webhook_url = settings.discord_transmute_webhook_url or os.getenv("DISCORD_TRANSMUTE_WEBHOOK_URL", "") or os.getenv("DISCORD_TRANSMUTATION_WEBHOOK_URL", "")
        self.bm_transmute_webhook_url = settings.discord_bm_transmute_webhook_url or os.getenv("DISCORD_BM_TRANSMUTE_WEBHOOK_URL", "") or os.getenv("DISCORD_BM_TRANSMUTATION_WEBHOOK_URL", "")

        all_urls = [
            self.webhook_url, self.arb_webhook_url, self.bm_webhook_url, self.bm_arb_webhook_url,
            self.crafting_webhook_url, self.bm_crafting_webhook_url, self.refining_webhook_url,
            self.bm_refining_webhook_url, self.enchanting_webhook_url, self.bm_enchanting_webhook_url,
            self.mm_webhook_url, self.bm_mm_webhook_url, self.island_webhook_url, self.quality_webhook_url,
            self.transmute_webhook_url, self.bm_transmute_webhook_url
        ]
        self.enabled = any(u and "YOUR_WEBHOOK" not in u for u in all_urls)
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            limits = httpx.Limits(max_keepalive_connections=20, max_connections=50, keepalive_expiry=30.0)
            timeout = httpx.Timeout(connect=15.0, read=25.0, write=15.0, pool=15.0)
            headers = {
                "User-Agent": "DiscordBot (https://github.com/philipjj/Albion-Quant-System, 3.2)",
                "Content-Type": "application/json",
            }
            self._client = httpx.AsyncClient(limits=limits, timeout=timeout, headers=headers)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _send_webhook(self, payload: dict, webhook_url: str = None) -> bool:
        if not self.enabled:
            return False

        from app.core import state
        if not getattr(state, "discord_alerts_enabled", True) or not getattr(settings, "discord_alerts_enabled", True):
            log.debug("[DISCORD ALERTS] Alert suppressed: Discord alerts are currently disabled via setting.")
            return False

        url = webhook_url or self.webhook_url
        if not url or "YOUR_WEBHOOK" in url:
            return False

        client = self._get_client()
        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code in (200, 204):
                    # Proactive rate-limit respect if bucket is exhausted
                    rem = resp.headers.get("X-RateLimit-Remaining")
                    if rem == "0":
                        reset_after = float(resp.headers.get("X-RateLimit-Reset-After", 1.0))
                        log.debug(f"Discord rate limit remaining 0, sleeping {reset_after:.2f}s")
                        await asyncio.sleep(reset_after)
                    return True

                if resp.status_code == 429:
                    retry_after = 1.5
                    try:
                        data = resp.json()
                        retry_after = float(data.get("retry_after", resp.headers.get("Retry-After", 1.5)))
                    except Exception:
                        retry_after = float(resp.headers.get("Retry-After", 1.5))
                    log.warning(f"Discord rate limited (429). Retrying after {retry_after:.2f}s...")
                    await asyncio.sleep(retry_after + 0.1)
                    continue

                log.error(
                    f"Discord webhook failed ({resp.status_code}): {resp.text}"
                )
                if attempt == max_retries - 1:
                    return False
            except Exception as e:
                log.error(
                    f"Discord webhook failed: {repr(e)} (Attempt {attempt + 1}/{max_retries})"
                )
                if attempt == max_retries - 1:
                    return False

            await asyncio.sleep(1.0 * (2 ** attempt))
        return False

    def _format_arbitrage_embed(self, opp: dict) -> dict:
        confidence = scorer.calculate_data_confidence(opp)
        badge = SERVER_BADGES.get(settings.active_server.value, "[UNKNOWN]")
        margin = _get_true_margin(opp)

        dest_city = opp.get("destination_city", opp.get("sell_city", "Unknown"))
        src_city = opp.get("source_city", opp.get("crafting_city", "Unknown"))
        is_bm = (dest_city in ["Black Market", "Caerleon"] or src_city == "Caerleon")

        # Visual Theme Color
        if is_bm:
            color = 0x8E44AD  # Royal Velvet Purple for BM
        elif margin > 30:
            color = 0x2ECC71  # Vibrant Emerald Green
        elif margin > 15:
            color = 0xF1C40F  # Cyber Yellow
        else:
            color = 0xE67E22  # Amber

        prem_info = _premium_badge(opp)
        age_buy = _fmt_age(opp.get("data_age_buy", 0))
        age_sell = _fmt_age(opp.get("data_age_sell", 0))
        risk_tag = _risk_label(opp.get("risk_score", 0))

        # Build visual description header
        route_header = f"💀 **BLACK MARKET**" if is_bm else f"⚖️ **ROYAL ARBITRAGE**"
        desc = f"-# {route_header} • {prem_info} • Risk: {risk_tag}\n"
        desc += f"-# ⏳ Data Age: Buy {age_buy} | Sell {age_sell}\n"
        
        b_qual = opp.get("buy_quality", opp.get("quality", 1))
        o_qual = opp.get("order_quality", opp.get("quality", 1))
        if is_bm and b_qual != o_qual:
            q_names = {1: "Normal", 2: "Good", 3: "Outstanding", 4: "Excellent", 5: "Masterpiece"}
            desc += f"-# 💎 **CROSS-QUALITY FILL**: Bought **{q_names.get(b_qual, f'Q{b_qual}')}** in `{src_city}` ➔ Fulfills **{q_names.get(o_qual, f'Q{o_qual}')}** BM Order\n"
            
        if opp.get("can_be_crafted"):
            desc += f"-# 🔨 Craftable at {opp.get('craft_city')} (Cost: {fmt_k(opp.get('craft_cost', 0))})\n"
        if opp.get("coverage_suspect"):
            desc += "-# ⚠️ Low volume / Thin Liquidity\n"
        desc += f"# {src_city} ➔ {dest_city}"

        item_id = opp.get("item_id") or opp.get("target_item_id") or "T4_BAG"
        item_name = opp.get("item_name", item_id)
        quality = opp.get("quality", 1)
        safe_qty = opp.get("safe_limit", 1)
        if safe_qty < 1:
            safe_qty = 1

        # Embed title with explicit target quantity for BM
        if is_bm:
            embed_title = f"{badge} 📦 {safe_qty}x {item_name} (BM Demand)"
        else:
            embed_title = f"{badge} {item_name}"

        if is_bm:
            bp = opp.get('buy_price', 0)
            sp = opp.get('sell_price', 0)
            tax_r = opp.get('tax_rate', 0.04 if opp.get('is_premium', True) else 0.08)
            net_rev = sp * (1.0 - tax_r)
            net_profit_per_item = opp.get('estimated_profit', 0)
            trade_math_val = (
                f"Target Quantity Needed: **{safe_qty}x items**\n"
                f"Buy Price: **{fmt_k(bp)}** (`{src_city}`)\n"
                f"BM Order: **{fmt_k(sp)}** (Net: `{fmt_k(net_rev)}` after {tax_r*100:.1f}% tax)\n"
                f"Net Profit / Item: **+{fmt_k(net_profit_per_item)}**\n"
                f"Total Batch Profit ({safe_qty}x): **+{fmt_k(net_profit_per_item * safe_qty)}**"
            )
        else:
            trade_math_val = (
                f"Buy: **{fmt_k(opp.get('buy_price', 0))}** (`{src_city}`)\n"
                f"Sell: **{fmt_k(opp.get('sell_price', 0))}** (`{dest_city}`)\n"
                f"Net Profit: **+{fmt_k(opp.get('estimated_profit', 0))}**"
            )

        embed = {
            "title": embed_title,
            "description": desc,
            "color": color,
            "thumbnail": {
                "url": item_icon_url(item_id, quality=quality, size=128)
            },
            "fields": [
                {
                    "name": "💰 Trade Execution Math",
                    "value": trade_math_val,
                    "inline": False,
                },
                {
                    "name": "📊 Metrics & Yield",
                    "value": f"• Margin: **{margin:.1f}%**\n• ROI: **{opp.get('roi', 0):.1f}%**\n• EV/hr: **{fmt_k(opp.get('ev_score', 0))}**",
                    "inline": True,
                },
                {
                    "name": "📦 Target Batch & Volume",
                    "value": f"• Target Batch: **{safe_qty} units needed**\n• 24h Volume: **{opp.get('daily_volume', 0):,} vol**\n• Yield/kg: **{fmt_k(opp.get('profit_per_kg', 0))}**",
                    "inline": True,
                },
            ],
            "footer": {"text": f"AQS Quantitative Engine v3.2 • {settings.active_server.value.upper()}"},
            "timestamp": datetime.utcnow().isoformat(),
        }

        return embed

    def _format_crafting_embed(self, opp: dict) -> dict:
        confidence = scorer.calculate_data_confidence(opp)
        badge = SERVER_BADGES.get(settings.active_server.value, "[UNKNOWN]")
        margin = _get_true_margin(opp)
        sell_city = opp.get("sell_city", "Any")
        craft_city = opp.get("crafting_city", opp.get("craft_city", "Unknown"))
        is_bm = (sell_city in ["Black Market", "Caerleon"])

        # Visual Theme Color
        if is_bm:
            color = 0x8E44AD  # Purple for BM
        elif margin > 25:
            color = 0x2ECC71  # Vibrant Green
        elif margin > 10:
            color = 0xF1C40F  # Cyber Yellow
        else:
            color = 0xE67E22  # Amber

        # Build Ingredients Breakdown List
        details = opp.get("details", opp.get("ingredients", []))
        path_lines = []
        rrr = opp.get("rrr_used", 0.0)

        for d in details:
            mode = d.get("mode")
            if not mode:
                mode = "BUY" if d.get("buy_city") else "CRAFT"

            mode_icon = "🛒 Buy" if mode == "BUY" else "🔨 Craft"
            raw_qty = d.get("quantity", 1)
            qty = int(raw_qty) if raw_qty == int(raw_qty) else raw_qty

            name = d.get("name")
            if not name or name == d.get("id") or name == d.get("item_id"):
                raw_id = d.get("item_id", d.get("id", "Unknown"))
                name = raw_id.replace("_", " ").title()

            price = d.get("unit_price", 0)
            is_returnable = d.get("is_returnable", False)

            if is_returnable and rrr > 0:
                net_price = price * (1.0 - rrr)
                path_lines.append(f"• {qty}x **{name}** ({mode_icon} @ {fmt_k(price)} ➔ Net: `{fmt_k(net_price)}`)")
            else:
                path_lines.append(f"• {qty}x **{name}** ({mode_icon} @ {fmt_k(price)})")

        path_str = "\n".join(path_lines)

        prem_info = _premium_badge(opp)
        age_mat = _fmt_age(opp.get("data_age_materials", 0))
        age_sell = _fmt_age(opp.get("data_age_sell", 0))
        focus_str = " • 🔥 Focus: On" if opp.get("use_focus") else ""

        desc = f"-# 🔨 **CRAFTING OPPORTUNITY** • {prem_info}{focus_str}\n"
        desc += f"-# ⏳ Data Age: Materials {age_mat} | Sell {age_sell}\n"
        if opp.get("coverage_suspect"):
            desc += "-# ⚠️ Thin Market Liquidity\n"
        desc += f"# Craft @ {craft_city} ➔ Sell @ {sell_city}"

        item_id = opp.get("item_id") or opp.get("target_item_id") or opp.get("crafted_item_id") or "T4_BAG"
        item_name = opp.get("item_name", item_id)
        quality = opp.get("quality", 1)
        safe_qty = opp.get("safe_limit", 1)
        if safe_qty < 1:
            safe_qty = 1

        if is_bm:
            tax_r = opp.get('tax_rate', 0.04 if opp.get('is_premium', True) else 0.08)
            net_sell_val = opp.get('sell_price', 0) * (1.0 - tax_r)
            embed_title = f"{badge} 📦 {safe_qty}x {item_name} (BM Crafting Demand)"
            craft_math_val = (
                f"Target Quantity Needed: **{safe_qty}x items**\n"
                f"Craft Cost / Item: **{fmt_k(opp.get('craft_cost', 0))}** (`{craft_city}`)\n"
                f"BM Sell Value / Item: **{fmt_k(opp.get('sell_price', 0))}** (Net: `{fmt_k(net_sell_val)}` after {tax_r*100:.1f}% tax)\n"
                f"Net Profit / Item: **+{fmt_k(opp.get('profit', 0))}**\n"
                f"Total Batch Profit ({safe_qty}x): **+{fmt_k(opp.get('profit', 0) * safe_qty)}**"
            )
        else:
            embed_title = f"{badge} {item_name}"
            craft_math_val = (
                f"Craft Cost: **{fmt_k(opp.get('craft_cost', 0))}** (`{craft_city}`)\n"
                f"Sell Value: **{fmt_k(opp.get('sell_price', 0))}** (`{sell_city}`)\n"
                f"Net Profit: **+{fmt_k(opp.get('profit', 0))}**"
            )

        embed = {
            "title": embed_title,
            "description": desc,
            "color": color,
            "thumbnail": {
                "url": item_icon_url(item_id, quality=quality, size=128)
            },
            "fields": [
                {
                    "name": "💰 Crafting Financial Math",
                    "value": craft_math_val,
                    "inline": False,
                },
                {
                    "name": "📊 Yield & Efficiency",
                    "value": f"• Margin: **{margin:.1f}%**\n• ROI: **{opp.get('roi', 0):.1f}%**\n• EV/hr: **{fmt_k(opp.get('ev_score', 0))}**\n• RRR Used: **{rrr * 100:.1f}%**",
                    "inline": True,
                },
                {
                    "name": "📦 Target Batch & Density",
                    "value": f"• Target Batch: **{safe_qty} units needed**\n• 24h Volume: **{opp.get('daily_volume', 0):,} vol**\n• Yield/kg: **{fmt_k(opp.get('profit_per_kg', 0))}**",
                    "inline": True,
                },
                {
                    "name": "🧱 Material Requirements",
                    "value": f"{path_str[:1024]}" if path_str else "No material details",
                    "inline": False,
                },
            ],
            "footer": {"text": f"AQS Quantitative Engine v3.2 • {settings.active_server.value.upper()}"},
            "timestamp": datetime.utcnow().isoformat(),
        }

        return embed

    def _format_refining_embed(self, opp: dict) -> dict:
        badge = SERVER_BADGES.get(settings.active_server.value, "[UNKNOWN]")
        margin = _get_true_margin(opp)
        sell_city = opp.get("sell_city", "Any")
        buy_city = opp.get("buy_city") or opp.get("crafting_city") or "Royal Market"
        refine_city = opp.get("refine_city") or opp.get("crafting_city") or "Bonus City"
        is_bm = (sell_city in ["Black Market", "Caerleon"])

        # Visual Theme Color
        color = 0x1ABC9C if not is_bm else 0x8E44AD  # Cyan/Teal for Refining, Purple for BM

        details = opp.get("ingredients", [])
        path_lines = []
        rrr = opp.get("rrr_used", 0.0)

        for d in details:
            qty = d.get("quantity", 1)
            name = d.get("name", d.get("item_id", "Unknown"))
            ing_buy_city = d.get("buy_city", "")
            price = d.get("unit_price", 0)
            is_returnable = d.get("is_returnable", True)

            city_str = f" @ `{ing_buy_city}`" if ing_buy_city else ""
            if is_returnable and rrr > 0:
                net_price = price * (1.0 - rrr)
                path_lines.append(f"• {qty}x **{name}** (Buy{city_str} @ {fmt_k(price)} ➔ Net: `{fmt_k(net_price)}`)")
            else:
                path_lines.append(f"• {qty}x **{name}** (Buy{city_str} @ {fmt_k(price)})")

        path_str = "\n".join(path_lines)

        prem_info = _premium_badge(opp)
        age_mat = _fmt_age(opp.get("data_age_materials", 0))
        age_sell = _fmt_age(opp.get("data_age_sell", 0))

        desc = f"-# ⚗️ **RESOURCE REFINING** • {prem_info} • Bonus RRR: **{rrr * 100:.1f}%**\n"
        desc += f"-# ⏳ Data Age: Materials {age_mat} | Sell {age_sell}\n"
        if opp.get("coverage_suspect"):
            desc += "-# ⚠️ Thin Volume\n"

        if buy_city == refine_city == sell_city:
            desc += f"# {refine_city} (Buy, Refine & Sell)"
        elif buy_city == refine_city:
            desc += f"# {refine_city} (Buy & Refine) ➔ {sell_city} (Sell)"
        elif sell_city == refine_city:
            desc += f"# {buy_city} (Buy) ➔ {refine_city} (Refine & Sell)"
        elif buy_city == sell_city:
            desc += f"# {buy_city} (Buy) ➔ {refine_city} (Refine) ➔ {buy_city} (Sell)"
        else:
            desc += f"# {buy_city} ➔ Refine @ {refine_city} ➔ Sell @ {sell_city}"

        item_id = opp.get("item_id") or "T4_PLANKS"
        quality = opp.get("quality", 1)

        embed = {
            "title": f"{badge} {opp.get('item_name', item_id)}",
            "description": desc,
            "color": color,
            "thumbnail": {
                "url": item_icon_url(item_id, quality=quality, size=128)
            },
            "fields": [
                {
                    "name": "💰 Refining Financial Math",
                    "value": f"Raw Mat Cost: **{fmt_k(opp.get('craft_cost', 0))}**\nRefined Value: **{fmt_k(opp.get('sell_price', 0))}** (`{sell_city}`)\nNet Profit: **+{fmt_k(opp.get('profit', 0))}**",
                    "inline": False,
                },
                {
                    "name": "📊 Yield & RRR Efficiency",
                    "value": f"• Margin: **{margin:.1f}%**\n• ROI: **{opp.get('roi', 0):.1f}%**\n• EV/hr: **{fmt_k(opp.get('ev_score', 0))}**\n• RRR Specialty: **{rrr * 100:.1f}%** (`{refine_city}`)",
                    "inline": True,
                },
                {
                    "name": "📦 Batch & Weight",
                    "value": f"• Safe Batch: **{opp.get('safe_limit', 0):,} units**\n• 24h Volume: **{opp.get('daily_volume', 0):,} vol**\n• Profit/kg: **{fmt_k(opp.get('profit_per_kg', 0))}**",
                    "inline": True,
                },
                {
                    "name": "🧪 Material Inputs",
                    "value": f"{path_str[:1024]}" if path_str else "No material details",
                    "inline": False,
                },
            ],
            "footer": {"text": f"AQS Quantitative Engine v3.2 • {settings.active_server.value.upper()}"},
            "timestamp": datetime.utcnow().isoformat(),
        }

        return embed

    def _format_island_embed(self, opp: dict) -> dict:
        badge = SERVER_BADGES.get(settings.active_server.value, "[UNKNOWN]")
        margin = _get_true_margin(opp)
        craft_city = opp.get("craft_city") or opp.get("crafting_city") or "Personal Island"
        sell_city = opp.get("sell_city") or opp.get("destination_city") or "Market"
        source_city = opp.get("source_city") or craft_city
        dest_city = opp.get("destination_city") or f"{sell_city} Market"
        buy_city = opp.get("buy_city") or craft_city.replace("Personal Island (", "").replace(")", "").strip()

        # Theme color: Emerald Green / Gold for island agriculture
        color = 0x27AE60 if margin >= 20 else 0xF39C12

        prem_info = _premium_badge(opp)
        age_mat = _fmt_age(opp.get("data_age_materials", 0))
        age_sell = _fmt_age(opp.get("data_age_sell", 0))
        focus_str = " • 🔥 Focus: On" if opp.get("use_focus") else ""
        rrr = opp.get("rrr_used", 0.0)

        # Check if item gets island biome bonus
        from app.core.market_utils import get_island_farming_bonus
        item_id = opp.get("item_id") or opp.get("target_item_id") or "T4_CARROT"
        item_name = opp.get("item_name", item_id)
        quality = opp.get("quality", 1)

        island_host = buy_city
        biome_bonus = get_island_farming_bonus(island_host, item_id)
        biome_tag = f"-# 🌾 **Biome Specialty: +{biome_bonus*100:.0f}% Yield** ({island_host} Specialization)\n" if biome_bonus > 0 else ""

        desc = f"-# 🌴 **ISLAND AGRICULTURE & PRODUCTION** • {prem_info}{focus_str}\n"
        desc += f"-# ⏳ Data Age: Seeds/Inputs {age_mat} | Market Sell {age_sell}\n"
        desc += biome_tag
        if opp.get("coverage_suspect"):
            desc += "-# ⚠️ Thin Market Liquidity\n"
        desc += f"# 🏡 {source_city} ➔ 🛒 {dest_city}"

        safe_qty = opp.get("safe_limit", 1)
        if safe_qty < 1:
            safe_qty = 1

        details = opp.get("details", opp.get("ingredients", []))
        path_lines = []
        for d in details:
            raw_qty = d.get("quantity", 1)
            qty = int(raw_qty) if raw_qty == int(raw_qty) else raw_qty
            name = d.get("name") or d.get("item_id", "Unknown").replace("_", " ").title()
            price = d.get("unit_price", 0)
            city_str = f" @ `{d.get('buy_city', buy_city)}`"
            path_lines.append(f"• {qty}x **{name}** (Buy{city_str} @ {fmt_k(price)})")

        path_str = "\n".join(path_lines)

        harvest_str = f"Harvest Value (+{biome_bonus*100:.0f}% Yield)" if biome_bonus > 0 else "Harvest Market Value"

        embed = {
            "title": f"{badge} 🌾 {item_name}",
            "description": desc,
            "color": color,
            "thumbnail": {
                "url": item_icon_url(item_id, quality=quality, size=128)
            },
            "fields": [
                {
                    "name": "💰 Island Production Math",
                    "value": (
                        f"Seed/Input Cost: **{fmt_k(opp.get('craft_cost', opp.get('total_cost', 0)))}** (`{buy_city}`)\n"
                        f"{harvest_str}: **{fmt_k(opp.get('sell_price', 0))}** (`{sell_city}`)\n"
                        f"Net Profit: **+{fmt_k(opp.get('profit', 0))}**"
                    ),
                    "inline": False,
                },
                {
                    "name": "📊 Yield & Efficiency",
                    "value": f"• Margin: **{margin:.1f}%**\n• ROI: **{opp.get('roi', 0):.1f}%**\n• EV/hr: **{fmt_k(opp.get('ev_score', 0))}**\n• Focus RRR: **{rrr * 100:.1f}%**",
                    "inline": True,
                },
                {
                    "name": "📦 Target Batch & Density",
                    "value": f"• Target Batch: **{safe_qty} units**\n• 24h Volume: **{opp.get('daily_volume', 0):,} vol**\n• Yield/kg: **{fmt_k(opp.get('profit_per_kg', 0))}**",
                    "inline": True,
                },
                {
                    "name": "🌱 Inputs & Seeds Required",
                    "value": f"{path_str[:1024]}" if path_str else "No material details",
                    "inline": False,
                },
            ],
            "footer": {"text": f"AQS Quantitative Engine v3.2 • {settings.active_server.value.upper()}"},
            "timestamp": datetime.utcnow().isoformat(),
        }

        return embed

    def _format_mm_embed(self, opp: dict) -> dict:
        badge = SERVER_BADGES.get(settings.active_server.value, "[UNKNOWN]")
        margin = opp.get("estimated_margin", opp.get("profit_margin", opp.get("profit_pct", 0.0)))
        src_city = opp.get("source_city", opp.get("destination_city", "Unknown"))
        is_bm = (src_city in ["Black Market", "Caerleon"])

        # Visual Theme Color
        color = 0x3498DB if not is_bm else 0x8E44AD  # Azure Blue for MM, Purple for BM

        prem_info = _premium_badge(opp)
        age_buy = _fmt_age(opp.get("data_age_buy", 0))
        age_sell = _fmt_age(opp.get("data_age_sell", 0))
        est_profit = opp.get("estimated_profit", opp.get("profit", opp.get("net_profit", 0)))

        desc = f"-# 📈 **MARKET MAKING SPREAD** • {prem_info}\n"
        desc += f"-# ⏳ Data Age: Ask {age_sell} | Bid {age_buy}\n"
        if opp.get("coverage_suspect"):
            desc += "-# ⚠️ Thin Liquidity\n"
        desc += f"# Market Making: {src_city}"

        item_id = opp.get("item_id") or opp.get("target_item_id") or opp.get("base_item_id") or "T4_BAG"
        quality = opp.get("quality", 1)

        embed = {
            "title": f"{badge} {opp.get('item_name', item_id)}",
            "description": desc,
            "color": color,
            "thumbnail": {
                "url": item_icon_url(item_id, quality=quality, size=128)
            },
            "fields": [
                {
                    "name": "💰 Bid/Ask Spread Math",
                    "value": f"Buy Order (Bid): **{fmt_k(opp.get('buy_price', 0))}**\nSell Order (Ask): **{fmt_k(opp.get('sell_price', 0))}**\nSpread Profit: **+{fmt_k(est_profit)}**",
                    "inline": False,
                },
                {
                    "name": "📊 Metrics & Yield",
                    "value": f"• Spread Margin: **{margin:.1f}%**\n• ROI: **{opp.get('roi', 0):.1f}%**\n• EV/hr: **{fmt_k(opp.get('ev_score', 0))}**",
                    "inline": True,
                },
                {
                    "name": "🏛️ Tax & Fees Paid",
                    "value": f"• Tax Paid: **{fmt_k(opp.get('tax_paid', 0))}**\n• Setup Fees: **{fmt_k(opp.get('setup_fees', 0))}**\n• Safe Batch: **{opp.get('safe_limit', 0):,} units**",
                    "inline": True,
                },
            ],
            "footer": {"text": f"AQS Quantitative Engine v3.2 • {settings.active_server.value.upper()}"},
            "timestamp": datetime.utcnow().isoformat(),
        }

        return embed

    def _format_enchanting_embed(self, opp: dict) -> dict:
        badge = SERVER_BADGES.get(settings.active_server.value, "[UNKNOWN]")
        sell_p = opp.get("bm_buy_price", opp.get("sell_price", 0))
        profit = opp.get("estimated_profit", opp.get("net_profit", 0))
        raw_margin = opp.get("profit_margin")
        if raw_margin is not None and raw_margin != opp.get("roi") and raw_margin != opp.get("profit_pct"):
            margin = raw_margin
        else:
            margin = (profit / sell_p * 100.0) if sell_p > 0 else 0.0

        base_name = opp.get("base_item_id", "").replace("_", " ").title()
        mat_name = opp.get("material_id", "").replace("_", " ").title()
        base_city = opp.get("base_city", opp.get("source_city", "Caerleon"))
        dest_city = opp.get("destination_city", opp.get("sell_city", "Black Market" if base_city == "Caerleon" else base_city))
        is_bm = (dest_city in ["Black Market", "Caerleon"] or base_city == "Caerleon")

        color = 0xE91E63 if not is_bm else 0x8E44AD  # Neon Pink for Enchanting, Purple for BM

        prem_info = _premium_badge(opp)
        age_base = _fmt_age(opp.get("data_age_base", 0))
        age_mat = _fmt_age(opp.get("data_age_material", 0))
        age_sell = _fmt_age(opp.get("data_age_sell", opp.get("data_age_bm", 0)))

        if is_bm:
            if base_city == "Caerleon":
                header_tag = "🔮 **CAERLEON BM ENCHANTING (0% RISK)**"
            else:
                header_tag = "💀 **BLACK MARKET TRANSPORT ENCHANTING**"
        else:
            header_tag = "✨ **ROYAL ENCHANTING**"

        desc = f"-# {header_tag} • {prem_info}\n"
        desc += f"-# ⏳ Data Age: Base Item {age_base} | Mat {age_mat} | Sell Market {age_sell}\n"
        if is_bm:
            if base_city != "Caerleon":
                desc += f"# {base_city} (Buy Base) ➔ Caerleon (Enchant) ➔ {dest_city} (Sell)"
            else:
                desc += f"# 🛡️ Caerleon (Buy & Enchant) ➔ {dest_city} (Sell - 0% Risk)"
        else:
            if base_city == dest_city:
                desc += f"# {base_city} (Buy Base, Enchant & Sell)"
            else:
                desc += f"# {base_city} (Buy Base) ➔ {dest_city} (Enchant & Sell)"

        item_id = opp.get("target_item_id") or opp.get("item_id") or "T7_MAIN_SWORD@1"
        quality = opp.get("quality", 1)

        quality_names = {1: "Normal", 2: "Good", 3: "Outstanding", 4: "Excellent", 5: "Masterpiece"}
        base_q = opp.get("base_quality", opp.get("quality", 1))
        base_q_str = f" ({quality_names.get(base_q, 'Normal')})" if base_q > 1 else ""

        mat_unit = opp.get('material_price', 0)
        mat_unit_str = f"{mat_unit:,.0f}" if (1000 <= mat_unit < 10000) else fmt_k(mat_unit)

        tax_r = opp.get('tax_rate', 0.04 if opp.get('is_premium', True) else 0.08)
        if is_bm:
            net_sell_val = sell_p * (1.0 - tax_r)
            sell_field_str = f"Target Sell Price: **{fmt_k(sell_p)}** (`{dest_city}` - Net: `{fmt_k(net_sell_val)}` after {tax_r*100:.1f}% tax)"
        else:
            sell_field_str = f"Target Sell Price: **{fmt_k(sell_p)}** (`{dest_city}`)"

        embed = {
            "title": f"{badge} {opp.get('item_name', item_id)}",
            "description": desc,
            "color": color,
            "thumbnail": {
                "url": item_icon_url(item_id, quality=quality, size=128)
            },
            "fields": [
                {
                    "name": "💰 Enchanting Financial Math",
                    "value": f"Base Item Cost: **{fmt_k(opp.get('base_price', 0))}** (`{base_city}`)\nMaterial Cost: **{mat_unit_str}** x {opp.get('material_qty', 1)} (**{fmt_k(mat_unit * opp.get('material_qty', 1))}**)\n{sell_field_str}\nNet Profit: **+{fmt_k(profit)}**",
                    "inline": False,
                },
                {
                    "name": "📊 Yield & ROI",
                    "value": f"• Margin: **{margin:.1f}%**\n• ROI: **{opp.get('roi', 0):.1f}%**\n• Total Cost: **{fmt_k(opp.get('total_cost', 0))}**",
                    "inline": True,
                },
                {
                    "name": "✨ Components Required",
                    "value": f"• Base: **{base_name}{base_q_str}** (`{base_city}`)\n• Material: {opp.get('material_qty', 1)}x **{mat_name}**\n• Safe Batch: **{opp.get('safe_limit', 0):,} units**",
                    "inline": True,
                },
            ],
            "footer": {"text": f"AQS Quantitative Engine v3.2 • {settings.active_server.value.upper()}"},
            "timestamp": datetime.utcnow().isoformat(),
        }

        return embed

    async def send_signal_alert(self, signal: dict) -> bool:
        """Sends an alert for an alpha signal."""
        badge = SERVER_BADGES.get(settings.active_server.value, "[UNKNOWN]")
        color = 0x3498DB  # Blue for signals

        embed = {
            "title": f"📈 {badge} SIGNAL: {signal['item_id']}",
            "description": f"Signal Type: **{signal['signal_type'].upper()}**",
            "color": color,
            "thumbnail": {"url": item_icon_url(signal["item_id"], quality=1, size=128)},
            "fields": [
                {
                    "name": "🚀 ALPHA SCORE",
                    "value": f"**{signal['alpha_score']:.2f}**",
                    "inline": True,
                },
                {
                    "name": "🧠 CONFIDENCE",
                    "value": f"**{signal['confidence'] * 100:.0f}%**",
                    "inline": True,
                },
                {
                    "name": "⚖️ RISK (MANIP)",
                    "value": f"**{signal['manipulation_risk']:.2f}**",
                    "inline": True,
                },
                {
                    "name": "💧 LIQUIDITY",
                    "value": f"**{signal.get('liquidity_score', 0):.2f}**",
                    "inline": True,
                },
                {
                    "name": "⏳ PERSISTENCE",
                    "value": f"**{signal.get('persistence_score', 0):.2f}**",
                    "inline": True,
                },
                {"name": "🗂️ CLUSTER", "value": signal.get("cluster_id", "None"), "inline": True},
            ],
            "footer": {
                "text": f"AQS vNext Signal Engine • {settings.active_server.value.upper()} Market"
            },
            "timestamp": datetime.utcnow().isoformat(),
        }

        return await self._send_webhook({"embeds": [embed]})

    async def send_patch_alert(self, patch_event: dict) -> bool:
        """Sends an alert for a patch or NDA update."""
        badge = SERVER_BADGES.get(settings.active_server.value, "[UNKNOWN]")
        color = 0xE67E22  # Orange for patch alerts

        embed = {
            "title": f"⚔️ {badge} PATCH/META SHIFT DETECTED",
            "description": f"**{patch_event['title']}**\n\n{patch_event['content']}",
            "color": color,
            "fields": [
                {
                    "name": "🎯 EXPECTED IMPACT",
                    "value": patch_event.get("impact", "Unknown"),
                    "inline": False,
                },
                {
                    "name": "🧠 CONFIDENCE",
                    "value": f"**{patch_event.get('confidence', 'MEDIUM')}**",
                    "inline": True,
                },
                {"name": "⏳ WINDOW", "value": patch_event.get("window", "24-72h"), "inline": True},
            ],
            "footer": {
                "text": f"AQS Patch Intelligence • {settings.active_server.value.upper()} Market"
            },
            "timestamp": datetime.utcnow().isoformat(),
        }

        return await self._send_webhook({"embeds": [embed]})

    async def send_meta_alert(self, meta_event: dict) -> bool:
        """Sends an alert for a meta surge or build rotation."""
        badge = SERVER_BADGES.get(settings.active_server.value, "[UNKNOWN]")
        color = 0xE74C3C  # Red for meta surges

        embed = {
            "title": f"🔥 {badge} META SURGE: {meta_event['item_id']}",
            "description": f"Meta demand score spike detected!",
            "color": color,
            "fields": [
                {
                    "name": "🚀 META SCORE",
                    "value": f"**{meta_event['score']:.2f}**",
                    "inline": True,
                },
                {
                    "name": "📈 TREND",
                    "value": f"**{meta_event.get('trend', 'UP')}**",
                    "inline": True,
                },
                {"name": "📊 USAGE", "value": f"{meta_event.get('usage', 'N/A')}", "inline": True},
            ],
            "footer": {
                "text": f"AQS PvP Meta Engine • {settings.active_server.value.upper()} Market"
            },
            "timestamp": datetime.utcnow().isoformat(),
        }

        return await self._send_webhook({"embeds": [embed]})

    async def send_categorized_alert(self, category: str, data: dict) -> bool:
        """
        Sends a categorized alert as requested in Phase 14.
        Supported categories: META SURGE, PATCH BUFF, PATCH NERF, BUILD ROTATION, RESOURCE PRESSURE, BM META PULL
        """
        badge = SERVER_BADGES.get(settings.active_server.value, "[UNKNOWN]")

        # Color mapping based on category
        colors = {
            "META SURGE": 0xE74C3C,  # Red
            "PATCH BUFF": 0x2ECC71,  # Green
            "PATCH NERF": 0xC0392B,  # Dark Red
            "BUILD ROTATION": 0x3498DB,  # Blue
            "RESOURCE PRESSURE": 0xF1C40F,  # Yellow
            "BM META PULL": 0x9B59B6,  # Purple
        }

        color = colors.get(category, 0x95A5A6)  # Default Gray

        embed = {
            "title": f"📢 {badge} {category}: {data.get('item_name', data.get('item_id', 'Global'))}",
            "description": data.get("description", f"Alert for {category}"),
            "color": color,
            "fields": [],
            "footer": {
                "text": f"AQS vNext Intelligence • {settings.active_server.value.upper()} Market"
            },
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Add dynamic fields if present
        for key, val in data.items():
            if key not in ["item_name", "item_id", "description"]:
                embed["fields"].append(
                    {"name": key.upper().replace("_", " "), "value": str(val), "inline": True}
                )

        # Add thumbnail if item_id is present
        if "item_id" in data:
            embed["thumbnail"] = {
                "url": item_icon_url(data["item_id"], quality=data.get("quality", 1), size=128)
            }

        return await self._send_webhook({"embeds": [embed]})

    def _format_quality_inversion_embed(self, opp: dict) -> dict:
        badge = SERVER_BADGES.get(settings.active_server.value, "[UNKNOWN]")
        margin = _get_true_margin(opp)
        city = opp.get("source_city", opp.get("city", "Caerleon"))
        prem_info = _premium_badge(opp)
        age = _fmt_age(opp.get("data_age_seconds", 0))

        inv_type = opp.get("inversion_type", "MANUAL_LIST_REQUIRED")
        is_instant = inv_type == "INSTANT_BM_FILL"
        color = 0x1ABC9C if is_instant else 0xE67E22  # Teal for Instant BM Fill, Amber/Orange for Manual List

        type_header = "⚡ **QUALITY MISPRICE — INSTANT BM FILL**" if is_instant else "⚠️ **QUALITY MISPRICE — MANUAL LIST REQUIRED**"
        desc = f"-# {type_header} • {prem_info}\n"
        desc += f"-# ⏳ Data Age: {age}\n"
        if is_instant:
            desc += f"# {city}: Buy {opp.get('buy_quality_name', 'High Q')} ➔ Instant Fill @ {opp.get('reference_quality_name', 'Low Q')} BM Buy Order"
        else:
            desc += f"# {city}: Buy {opp.get('buy_quality_name', 'High Q')} ➔ Relist at {opp.get('reference_quality_name', 'Low Q')} Market Sell Price (Wait on Listing)"

        item_id = opp.get("item_id") or opp.get("target_item_id") or opp.get("base_item_id") or "T4_BAG"
        quality = opp.get("buy_quality", 1)

        embed = {
            "title": f"{badge} {opp.get('item_name', item_id)}",
            "description": desc,
            "color": color,
            "thumbnail": {
                "url": item_icon_url(item_id, quality=quality, size=128)
            },
            "fields": [
                {
                    "name": "💎 Quality Inversion Math",
                    "value": f"Buy Price ({opp.get('buy_quality_name')}): **{fmt_k(opp.get('buy_price', 0))}**\nReference Price ({opp.get('reference_quality_name')}): **{fmt_k(opp.get('sell_price', 0))}**\nNet Profit: **+{fmt_k(opp.get('estimated_profit', 0))}**",
                    "inline": False,
                },
                {
                    "name": "📊 Yield & ROI",
                    "value": f"• Margin: **{margin:.1f}%**\n• ROI: **{opp.get('roi', margin):.1f}%**\n• EV/hr: **{fmt_k(opp.get('ev_score', 0))}**",
                    "inline": True,
                },
                {
                    "name": "📦 Execution",
                    "value": f"• Safe Batch: **{opp.get('safe_limit', 1):,} units**\n• 24h Volume: **{opp.get('daily_volume', 0):,} vol**",
                    "inline": True,
                },
            ],
            "footer": {"text": f"AQS Quantitative Engine v3.2 • {settings.active_server.value.upper()}"},
            "timestamp": datetime.utcnow().isoformat(),
        }

        return embed

    def _format_transmutation_embed(self, opp: dict) -> dict:
        badge = SERVER_BADGES.get(settings.active_server.value, "[UNKNOWN]")
        margin = _get_true_margin(opp)
        item_id = opp.get("item_id", "")
        src_name = opp.get("source_item_name", opp.get("source_item_id", ""))
        src_price = opp.get("source_price", 0)
        fee = opp.get("transmutation_fee", 0)
        sell_c = opp.get("destination_city", "Royal City")
        profit = opp.get("profit", opp.get("estimated_profit", 0))
        safe_limit = opp.get("safe_limit", 1)
        if safe_limit < 1:
            safe_limit = 1
        total_batch_profit = profit * safe_limit

        color = 0x9B59B6  # Amethyst Purple for Transmutation

        prem_info = _premium_badge(opp)
        age = _fmt_age(opp.get("data_age_sell", 0))

        desc = f"-# 🔮 **TRANSMUTATION FLIP** • {prem_info}\n"
        desc += f"-# ⏳ Data Age: {age}\n"
        desc += f"# Transmute {src_name} ➔ {opp.get('item_name', item_id)} @ {sell_c}"

        embed = {
            "title": f"{badge} Transmute: {opp.get('item_name', item_id)}",
            "description": desc,
            "color": color,
            "thumbnail": {
                "url": item_icon_url(item_id, quality=1, size=128)
            },
            "fields": [
                {
                    "name": "🔮 Transmutation Financial Math",
                    "value": (
                        f"Base Material Price: **{fmt_k(src_price)}**\n"
                        f"Transmutation Silver Fee: **{fmt_k(fee)}**\n"
                        f"Total Cost: **{fmt_k(opp.get('total_cost', 0))}**\n"
                        f"Market Sell Value: **{fmt_k(opp.get('sell_price', 0))}** (`{sell_c}`)\n"
                        f"Net Profit / Unit: **+{fmt_k(profit)}**\n"
                        f"Total Batch Profit ({safe_limit:,}x): **+{fmt_k(total_batch_profit)}**"
                    ),
                    "inline": False,
                },
                {
                    "name": "📊 Yield & ROI",
                    "value": f"• Margin: **{margin:.1f}%**\n• ROI: **{opp.get('roi', 0):.1f}%**\n• EV Score: **{fmt_k(opp.get('ev_score', 0))}**",
                    "inline": True,
                },
                {
                    "name": "📦 Batch & Volume",
                    "value": f"• Safe Batch: **{safe_limit:,} units**\n• 24h Volume: **{opp.get('daily_volume', 0):,} vol**",
                    "inline": True,
                },
            ],
            "footer": {"text": f"AQS Quantitative Engine v3.2 • {settings.active_server.value.upper()}"},
            "timestamp": datetime.utcnow().isoformat(),
        }
        return embed

    async def send_batch_alerts(
        self,
        arb_opps: list[dict] = None,
        craft_opps: list[dict] = None,
        arb_limit: int = 10,
        craft_limit: int = 10,
        mm_opps: list[dict] = None,
        mm_limit: int = 10,
        refine_opps: list[dict] = None,
        refine_limit: int = 10,
        enchant_opps: list[dict] = None,
        enchant_limit: int = 10,
        quality_opps: list[dict] = None,
        quality_limit: int = 10,
        transmute_opps: list[dict] = None,
        transmute_limit: int = 10,
        island_opps: list[dict] = None,
        island_limit: int = 10,
        bm_arb_opps: list[dict] = None,
        bm_arb_limit: int = 10,
        bm_craft_opps: list[dict] = None,
        bm_craft_limit: int = 10,
        bm_refine_opps: list[dict] = None,
        bm_refine_limit: int = 10,
        bm_enchant_opps: list[dict] = None,
        bm_enchant_limit: int = 10,
        bm_mm_opps: list[dict] = None,
        bm_mm_limit: int = 10,
        max_per_channel: int = 10,
    ):
        from collections import defaultdict
        from app.core import state
        if not getattr(state, "discord_alerts_enabled", True) or not getattr(settings, "discord_alerts_enabled", True):
            log.info("[DISCORD ALERTS] Batch alert dispatch skipped: Discord alerts are currently disabled via setting.")
            return {}

        channel_counts = defaultdict(int)


        if arb_opps is None:
            arb_opps = []
        if craft_opps is None:
            craft_opps = []
        if mm_opps is None:
            mm_opps = []
        if refine_opps is None:
            refine_opps = []
        if enchant_opps is None:
            enchant_opps = []
        if quality_opps is None:
            quality_opps = []
        if transmute_opps is None:
            transmute_opps = []
        if island_opps is None:
            island_opps = [o for o in craft_opps if _is_island_opportunity(o)]
        elif not island_opps and any(_is_island_opportunity(o) for o in craft_opps):
            island_opps = [o for o in craft_opps if _is_island_opportunity(o)]
        craft_opps = [o for o in craft_opps if not _is_island_opportunity(o)]

        if bm_arb_opps is None:
            bm_arb_opps = []
        if bm_craft_opps is None:
            bm_craft_opps = []
        if bm_refine_opps is None:
            bm_refine_opps = []
        if bm_enchant_opps is None:
            bm_enchant_opps = []
        if bm_mm_opps is None:
            bm_mm_opps = []

        # 1. TRANSMUTATION (Safe Royal Cities only)
        if getattr(settings, "enable_alerts_transmute", True):
            sent = 0
            for opp in transmute_opps[:transmute_limit]:
                target_webhook = self.transmute_webhook_url or self.webhook_url
                if target_webhook and sent < max_per_channel:
                    embed = self._format_transmutation_embed(opp)
                    if await self._send_webhook({"embeds": [embed]}, webhook_url=target_webhook):
                        sent += 1
                    await asyncio.sleep(0.8)

        # 2. ISLAND (Safe Royal Cities only)
        if getattr(settings, "enable_alerts_island", True) and self.island_webhook_url:
            sent = 0
            for opp in island_opps[:island_limit]:
                target_webhook = self.island_webhook_url
                if target_webhook and sent < max_per_channel:
                    embed = self._format_island_embed(opp)
                    if await self._send_webhook({"embeds": [embed]}, webhook_url=target_webhook):
                        sent += 1
                    await asyncio.sleep(0.8)

        # 3. B-MARKET-MAKING (Caerleon only)
        if getattr(settings, "enable_alerts_bm_mm", True):
            sent = 0
            for opp in bm_mm_opps[:bm_mm_limit]:
                target_webhook = self.bm_mm_webhook_url or self.bm_webhook_url or self.webhook_url
                if target_webhook and sent < max_per_channel:
                    embed = self._format_mm_embed(opp)
                    if await self._send_webhook({"embeds": [embed]}, webhook_url=target_webhook):
                        sent += 1
                    await asyncio.sleep(0.8)

        # 4. B-REFINING (Caerleon only)
        if getattr(settings, "enable_alerts_bm_refining", True):
            sent = 0
            for opp in bm_refine_opps[:bm_refine_limit]:
                target_webhook = self.bm_refining_webhook_url or self.bm_webhook_url or self.webhook_url
                if target_webhook and sent < max_per_channel:
                    embed = self._format_refining_embed(opp)
                    if await self._send_webhook({"embeds": [embed]}, webhook_url=target_webhook):
                        sent += 1
                    await asyncio.sleep(0.8)

        # 5. B-ENCHANTING (Caerleon -> Black Market)
        if getattr(settings, "enable_alerts_bm_enchanting", True):
            sent = 0
            for opp in bm_enchant_opps[:bm_enchant_limit]:
                target_webhook = self.bm_enchanting_webhook_url or self.bm_webhook_url or self.webhook_url
                if target_webhook and sent < max_per_channel:
                    embed = self._format_enchanting_embed(opp)
                    if await self._send_webhook({"embeds": [embed]}, webhook_url=target_webhook):
                        sent += 1
                    await asyncio.sleep(0.8)

        # 6. B-CRAFTING (Caerleon -> Black Market)
        if getattr(settings, "enable_alerts_bm_crafting", True):
            sent = 0
            for opp in bm_craft_opps[:bm_craft_limit]:
                target_webhook = self.bm_crafting_webhook_url or self.bm_webhook_url or self.webhook_url
                if target_webhook and sent < max_per_channel:
                    embed = self._format_crafting_embed(opp)
                    if await self._send_webhook({"embeds": [embed]}, webhook_url=target_webhook):
                        sent += 1
                    await asyncio.sleep(0.8)

        # 7. B-ARBITRAGE (Safe Royal Cities -> Black Market)
        if getattr(settings, "enable_alerts_bm_arb", True):
            sent = 0
            for opp in bm_arb_opps[:bm_arb_limit]:
                target_webhook = self.bm_arb_webhook_url or self.bm_webhook_url or self.webhook_url
                if target_webhook and sent < max_per_channel:
                    embed = self._format_arbitrage_embed(opp)
                    if await self._send_webhook({"embeds": [embed]}, webhook_url=target_webhook):
                        sent += 1
                    await asyncio.sleep(0.8)

        # 8. MARKET-MAKING (Safe Royal Cities only)
        if getattr(settings, "enable_alerts_mm", True):
            sent = 0
            for opp in mm_opps[:mm_limit]:
                target_webhook = self.mm_webhook_url or self.webhook_url
                if target_webhook and sent < max_per_channel:
                    embed = self._format_mm_embed(opp)
                    if await self._send_webhook({"embeds": [embed]}, webhook_url=target_webhook):
                        sent += 1
                    await asyncio.sleep(0.8)

        # 9. REFINING (Safe Royal Cities only)
        if getattr(settings, "enable_alerts_refining", True):
            sent = 0
            for opp in refine_opps[:refine_limit]:
                target_webhook = self.refining_webhook_url or self.webhook_url
                if target_webhook and sent < max_per_channel:
                    embed = self._format_refining_embed(opp)
                    if await self._send_webhook({"embeds": [embed]}, webhook_url=target_webhook):
                        sent += 1
                    await asyncio.sleep(0.8)

        # 10. ENCHANTING (Safe Royal Cities only)
        if getattr(settings, "enable_alerts_enchanting", True):
            sent = 0
            for opp in enchant_opps[:enchant_limit]:
                target_webhook = self.enchanting_webhook_url or self.webhook_url
                if target_webhook and sent < max_per_channel:
                    embed = self._format_enchanting_embed(opp)
                    if await self._send_webhook({"embeds": [embed]}, webhook_url=target_webhook):
                        sent += 1
                    await asyncio.sleep(0.8)

        # 11. CRAFTING (Safe Royal Cities only)
        if getattr(settings, "enable_alerts_crafting", True):
            sent = 0
            for opp in craft_opps[:craft_limit]:
                target_webhook = self.crafting_webhook_url or self.webhook_url
                if target_webhook and sent < max_per_channel:
                    embed = self._format_crafting_embed(opp)
                    if await self._send_webhook({"embeds": [embed]}, webhook_url=target_webhook):
                        sent += 1
                    await asyncio.sleep(0.8)

        # 12. ARBITRAGE (Safe Royal Cities only)
        if getattr(settings, "enable_alerts_arb", True):
            sent = 0
            for opp in arb_opps[:arb_limit]:
                target_webhook = self.arb_webhook_url or self.webhook_url
                if target_webhook and sent < max_per_channel:
                    embed = self._format_arbitrage_embed(opp)
                    if await self._send_webhook({"embeds": [embed]}, webhook_url=target_webhook):
                        sent += 1
                    await asyncio.sleep(0.8)

        # 13. QUALITY MISPRICES (Intra-city quality inversions - MUST NOT leak to Arbitrage webhook)
        if getattr(settings, "enable_alerts_quality", True) and self.quality_webhook_url:
            sent_qual = 0
            for opp in quality_opps[:quality_limit]:
                target_webhook = self.quality_webhook_url
                if target_webhook and sent_qual < max_per_channel:
                    embed = self._format_quality_inversion_embed(opp)
                    if await self._send_webhook({"embeds": [embed]}, webhook_url=target_webhook):
                        sent_qual += 1
                    await asyncio.sleep(0.8)

