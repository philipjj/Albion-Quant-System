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
    if any(k in id_upper for k in ["POTION", "FOOD", "MEAL", "SOUP", "STEW"]):
        return "Consumables"
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
    tax_pct = (opp.get("tax_rate", 0.04 if is_prem else 0.08)) * 100.0
    if is_prem:
        return f"👑 Premium ({tax_pct:.1f}% Tax)"
    return f"🛡️ Non-Premium ({tax_pct:.1f}% Tax)"


class DiscordAlerter:
    def __init__(self):
        self.webhook_url = settings.discord_webhook_url
        self.arb_webhook_url = settings.discord_arb_webhook_url
        self.bm_webhook_url = settings.discord_bm_webhook_url
        self.bm_arb_webhook_url = settings.discord_bm_arb_webhook_url
        self.crafting_webhook_url = settings.discord_crafting_webhook_url
        self.bm_crafting_webhook_url = settings.discord_bm_crafting_webhook_url
        self.refining_webhook_url = settings.discord_refining_webhook_url
        self.bm_refining_webhook_url = settings.discord_bm_refining_webhook_url
        self.enchanting_webhook_url = settings.discord_enchanting_webhook_url
        self.bm_enchanting_webhook_url = settings.discord_bm_enchanting_webhook_url
        self.mm_webhook_url = settings.discord_mm_webhook_url
        self.bm_mm_webhook_url = settings.discord_bm_mm_webhook_url

        all_urls = [
            self.webhook_url, self.arb_webhook_url, self.bm_webhook_url, self.bm_arb_webhook_url,
            self.crafting_webhook_url, self.bm_crafting_webhook_url, self.refining_webhook_url,
            self.bm_refining_webhook_url, self.enchanting_webhook_url, self.bm_enchanting_webhook_url,
            self.mm_webhook_url, self.bm_mm_webhook_url
        ]
        self.enabled = any(u and "YOUR_WEBHOOK" not in u for u in all_urls)

    async def _send_webhook(self, payload: dict, webhook_url: str = None) -> bool:
        if not self.enabled:
            return False
        if webhook_url is None:
            webhook_url = self.webhook_url
        if not webhook_url:
            return False

        payload["username"] = "Albion Quant Bot"

        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    resp = await client.post(webhook_url, json=payload)

                    if resp.status_code == 429:
                        retry_after = float(resp.headers.get("Retry-After", 2.0))
                        log.warning(f"Discord rate limit (429). Waiting {retry_after}s...")
                        await asyncio.sleep(retry_after)
                        continue

                    if resp.status_code == 503:
                        log.warning(f"Discord service unavailable (503). Retrying in 2s...")
                        await asyncio.sleep(2.0)
                        continue

                    resp.raise_for_status()
                    return True
            except httpx.HTTPStatusError as e:
                log.error(
                    f"Discord webhook failed with status {e.response.status_code} (Attempt {attempt + 1}/{max_retries})"
                )
                if attempt == max_retries - 1:
                    return False
            except Exception as e:
                log.error(
                    f"Discord webhook failed: {repr(e)} (Attempt {attempt + 1}/{max_retries})"
                )
                if attempt == max_retries - 1:
                    return False

            await asyncio.sleep(1.0)

    def _format_arbitrage_embed(self, opp: dict) -> dict:
        confidence = scorer.calculate_data_confidence(opp)
        badge = SERVER_BADGES.get(settings.active_server.value, "[UNKNOWN]")
        margin = opp.get("estimated_margin", opp.get("profit_margin", opp.get("profit_pct", 0.0)))

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

        trade_math_val = (
            f"Target Quantity Needed: **{safe_qty}x items**\n"
            f"Buy Price: **{fmt_k(opp.get('buy_price', 0))}** (`{src_city}`)\n"
            f"Sell Price: **{fmt_k(opp.get('sell_price', 0))}** (`{dest_city}`)\n"
            f"Net Profit / Item: **+{fmt_k(opp.get('estimated_profit', 0))}**\n"
            f"Total Batch Profit ({safe_qty}x): **+{fmt_k(opp.get('estimated_profit', 0) * safe_qty)}**"
        ) if is_bm else (
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
        margin = opp.get("profit_margin", opp.get("estimated_margin", opp.get("profit_pct", 0.0)))
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

        item_id = opp.get("item_id") or "T4_BAG"
        item_name = opp.get("item_name", item_id)
        quality = opp.get("quality", 1)
        safe_qty = opp.get("safe_limit", 1)
        if safe_qty < 1:
            safe_qty = 1

        if is_bm:
            embed_title = f"{badge} 📦 {safe_qty}x {item_name} (BM Crafting Demand)"
            craft_math_val = (
                f"Target Quantity Needed: **{safe_qty}x items**\n"
                f"Craft Cost / Item: **{fmt_k(opp.get('craft_cost', 0))}** (`{craft_city}`)\n"
                f"BM Sell Value / Item: **{fmt_k(opp.get('sell_price', 0))}** (`{sell_city}`)\n"
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
        margin = opp.get("profit_margin", 0)
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

        item_id = opp.get("item_id") or "T4_BAG"
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
        margin = opp.get("estimated_margin", opp.get("profit_margin", opp.get("profit_pct", 0.0)))
        base_name = opp.get("base_item_id", "").replace("_", " ").title()
        mat_name = opp.get("material_id", "").replace("_", " ").title()
        base_city = opp.get("base_city", opp.get("source_city", "Caerleon"))
        dest_city = opp.get("destination_city", opp.get("sell_city", "Black Market"))
        is_bm = (dest_city in ["Black Market", "Caerleon"])

        color = 0xE91E63 if not is_bm else 0x8E44AD  # Neon Pink for Enchanting, Purple for BM

        prem_info = _premium_badge(opp)
        age_base = _fmt_age(opp.get("data_age_base", 0))
        age_bm = _fmt_age(opp.get("data_age_bm", 0))

        desc = f"-# ✨ **ITEM ENCHANTING** • {prem_info}\n"
        desc += f"-# ⏳ Data Age: Base Item {age_base} | Sell Market {age_bm}\n"
        if base_city != "Caerleon":
            desc += f"# {base_city} (Buy Base) ➔ Caerleon (Enchant) ➔ {dest_city} (Sell)"
        else:
            desc += f"# Caerleon (Buy & Enchant) ➔ {dest_city} (Sell)"

        item_id = opp.get("target_item_id") or opp.get("item_id") or "T7_MAIN_SWORD@1"
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
                    "name": "💰 Enchanting Financial Math",
                    "value": f"Base Item Cost: **{fmt_k(opp.get('base_price', 0))}** (`{base_city}`)\nMaterial Cost: **{fmt_k(opp.get('material_price', 0))}** x {opp.get('material_qty', 1)} (**{fmt_k(opp.get('material_price', 0) * opp.get('material_qty', 1))}**)\nTarget Sell Price: **{fmt_k(opp.get('bm_buy_price', opp.get('sell_price', 0)))}** (`{dest_city}`)\nNet Profit: **+{fmt_k(opp.get('estimated_profit', 0))}**",
                    "inline": False,
                },
                {
                    "name": "📊 Yield & ROI",
                    "value": f"• Margin: **{margin:.1f}%**\n• ROI: **{opp.get('roi', 0):.1f}%**\n• Total Cost: **{fmt_k(opp.get('total_cost', 0))}**",
                    "inline": True,
                },
                {
                    "name": "✨ Components Required",
                    "value": f"• Base: **{base_name}** (`{base_city}`)\n• Material: {opp.get('material_qty', 1)}x **{mat_name}**\n• Safe Batch: **{opp.get('safe_limit', 0):,} units**",
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

    async def send_batch_alerts(
        self,
        arb_opps: list[dict],
        craft_opps: list[dict],
        arb_limit: int = 10,
        craft_limit: int = 10,
        mm_opps: list[dict] = None,
        mm_limit: int = 10,
        refine_opps: list[dict] = None,
        refine_limit: int = 10,
        enchant_opps: list[dict] = None,
        enchant_limit: int = 10,
        max_per_channel: int = 10,
    ):
        from collections import defaultdict
        channel_counts = defaultdict(int)

        if mm_opps is None:
            mm_opps = []
        if refine_opps is None:
            refine_opps = []
        if enchant_opps is None:
            enchant_opps = []

        # Process Arbitrage Opportunities
        for opp in arb_opps[:arb_limit]:
            dest = opp.get("destination_city", "") or opp.get("sell_city", "")
            src = opp.get("source_city", "") or opp.get("buy_city", "")
            is_bm = (dest in ["Black Market", "Caerleon"] or src == "Caerleon")
            target_webhook = (
                (self.bm_arb_webhook_url or self.bm_webhook_url or self.arb_webhook_url or self.webhook_url)
                if is_bm
                else (self.arb_webhook_url or self.webhook_url)
            )
            if target_webhook and channel_counts[target_webhook] < max_per_channel:
                embed = self._format_arbitrage_embed(opp)
                await self._send_webhook({"embeds": [embed]}, webhook_url=target_webhook)
                channel_counts[target_webhook] += 1
                await asyncio.sleep(0.5)

        # Process Crafting Opportunities
        for opp in craft_opps[:craft_limit]:
            sell_c = opp.get("sell_city", "")
            craft_c = opp.get("crafting_city", "") or opp.get("craft_city", "")
            is_bm = (sell_c in ["Black Market", "Caerleon"] or opp.get("sell_mode") == "BM" or craft_c == "Caerleon")
            target_webhook = (
                (self.bm_crafting_webhook_url or self.bm_webhook_url or self.crafting_webhook_url or self.webhook_url)
                if is_bm
                else (self.crafting_webhook_url or self.webhook_url)
            )
            if target_webhook and channel_counts[target_webhook] < max_per_channel:
                embed = self._format_crafting_embed(opp)
                await self._send_webhook({"embeds": [embed]}, webhook_url=target_webhook)
                channel_counts[target_webhook] += 1
                await asyncio.sleep(0.5)

        # Process Market Making Opportunities
        for opp in mm_opps[:mm_limit]:
            dest = opp.get("destination_city", "")
            src = opp.get("source_city", "")
            is_bm = (dest in ["Black Market", "Caerleon"] or src in ["Black Market", "Caerleon"])
            target_webhook = (
                (self.bm_mm_webhook_url or self.bm_webhook_url or self.mm_webhook_url or self.webhook_url)
                if is_bm
                else (self.mm_webhook_url or self.webhook_url)
            )
            if target_webhook and channel_counts[target_webhook] < max_per_channel:
                embed = self._format_mm_embed(opp)
                await self._send_webhook({"embeds": [embed]}, webhook_url=target_webhook)
                channel_counts[target_webhook] += 1
                await asyncio.sleep(0.5)

        # Process Refining Opportunities
        for opp in refine_opps[:refine_limit]:
            sell_c = opp.get("sell_city", "")
            is_bm = (sell_c in ["Black Market"] or opp.get("sell_mode") == "BM")
            target_webhook = (
                (self.bm_refining_webhook_url or self.bm_webhook_url or self.refining_webhook_url or self.webhook_url)
                if is_bm
                else (self.refining_webhook_url or self.webhook_url)
            )
            if target_webhook and channel_counts[target_webhook] < max_per_channel:
                embed = self._format_refining_embed(opp)
                await self._send_webhook({"embeds": [embed]}, webhook_url=target_webhook)
                channel_counts[target_webhook] += 1
                await asyncio.sleep(0.5)
                
        # Process Enchanting Opportunities
        for opp in enchant_opps[:enchant_limit]:
            dest = opp.get("destination_city", "") or opp.get("sell_city", "")
            is_bm = (dest in ["Black Market", "Caerleon"])
            target_webhook = (
                (self.bm_enchanting_webhook_url or self.bm_webhook_url or self.enchanting_webhook_url or self.webhook_url)
                if is_bm
                else (self.enchanting_webhook_url or self.webhook_url)
            )
            if target_webhook and channel_counts[target_webhook] < max_per_channel:
                embed = self._format_enchanting_embed(opp)
                await self._send_webhook({"embeds": [embed]}, webhook_url=target_webhook)
                channel_counts[target_webhook] += 1
                await asyncio.sleep(0.5)

