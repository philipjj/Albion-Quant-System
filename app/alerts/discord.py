"""
Discord Alert System for Albion Quant.
Sends formatted alerts via Discord webhooks for arbitrage and crafting opportunities.
"""

import asyncio
from datetime import datetime

import httpx

from app.core.config import settings
from app.core.icons import item_icon_url
from app.core.logging import log

RISK_LABELS = {
    (0.0, 0.15): "🟢 LOW",
    (0.15, 0.30): "🟡 MEDIUM",
    (0.30, 0.50): "🟠 HIGH",
    (0.50, 1.01): "🔴 EXTREME",
}


def _risk_label(score: float) -> str:
    for (lo, hi), label in RISK_LABELS.items():
        if lo <= score < hi:
            return label
    return "⚪ UNKNOWN"


def _get_category_group(item_id: str) -> str:
    """Group item IDs into logical market segments."""
    id_upper = item_id.upper()
    if any(k in id_upper for k in ["POTION", "FOOD", "MEAL", "SOUP", "STEW"]):
        return "Consumables"
    if any(k in id_upper for k in ["WOOD", "ORE", "FIBER", "HIDE", "ROCK", "BAR", "PLANK", "CLOTH", "LEATHER", "STONE"]):
        return "Resources"
    return "Equipment"


class DiscordAlerter:
    """Sends trading alerts to Discord via webhook."""

    def __init__(self):
        self.webhook_url = settings.discord_webhook_url
        self.enabled = bool(self.webhook_url and "YOUR_WEBHOOK" not in self.webhook_url)
        if not self.enabled:
            log.warning("Discord webhook not configured. Alerts will be logged only.")

    async def _send_webhook(self, payload: dict) -> bool:
        if not self.enabled:
            log.info(f"[ALERT] {payload.get('embeds', [{}])[0].get('title', 'Alert')}")
            return False

        # Identity override
        payload["username"] = "Albion Quant Bot"
        payload["avatar_url"] = "https://i.imgur.com/rL7t5jT.png"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self.webhook_url, json=payload)
                resp.raise_for_status()
                return True
        except Exception as e:
            log.error(f"Discord webhook failed: {e}")
            return False

    async def send_arbitrage_alert(self, opp: dict) -> bool:
        """Send a formatted premium arbitrage alert."""
        from app.core.scoring import scorer

        risk = _risk_label(opp.get("risk_score", 0))
        margin = opp.get("estimated_margin", 0)
        confidence = scorer.calculate_data_confidence(opp)
        icon = item_icon_url(
            opp.get("item_id", ""),
            quality=int(opp.get("quality") or 1),
            size=128,
        )

        # Color based on margin quality
        color = 0x00FF88 if margin > 30 else 0xFFAA00 if margin > 20 else 0x00AAFF

        display_name = opp.get("item_name") or opp["item_id"]
        embed = {
            "title": f"⚔️ HIGH VELOCITY ARBITRAGE: {display_name}",
            "description": f"Targeting **{margin:.1f}%** net margin after taxes and transport.",
            "color": color,
            "thumbnail": {"url": icon},
            "fields": [
                {"name": "🏙️ ROUTE", "value": f"**{opp['source_city']}** ➔ **{opp['destination_city']}**", "inline": True},
                {"name": "⚖️ RISK", "value": risk, "inline": True},
                {"name": "\u200b", "value": "\u200b", "inline": True},
                {"name": "💰 BUY AT", "value": f"**{opp['buy_price']:,}** silver", "inline": True},
                {"name": "📈 SELL AT", "value": f"**{opp['sell_price']:,}** silver", "inline": True},
                {"name": "\u200b", "value": "\u200b", "inline": True},
                {"name": "💎 NET PROFIT", "value": f"**{opp['estimated_profit']:,.0f}** silver", "inline": True},
                {"name": "🚀 ALPHA SCORE", "value": f"**{opp.get('ev_score', 0):,.0f}** EV/hr", "inline": True},
                {"name": "🧠 DATA CONF", "value": f"**{confidence*100:.0f}%**", "inline": True},
                {"name": "📊 REAL DEMAND (24H)", "value": f"{opp.get('daily_volume', 0):,}" if opp.get("volume_source") == "VERIFIED 24H" else f"{opp.get('daily_volume', 0):,} (Est)", "inline": True},
                {"name": "🛡️ VOLATILITY", "value": f"{opp.get('volatility', 0)*100:.1f}%", "inline": True},
                {"name": "📈 PERSISTENCE", "value": f"{opp.get('persistence', 1)} scans", "inline": True},
                {"name": "\u200b", "value": "\u200b", "inline": True},
            ],
            "timestamp": datetime.utcnow().isoformat(),
            "footer": {"text": "Albion Quant Bot • High-Frequency Transport System"},
        }
        return await self._send_webhook({"embeds": [embed]})

    async def send_crafting_alert(self, opp: dict) -> bool:
        """Send a formatted premium crafting alert with ingredient breakdown."""
        from app.core.scoring import scorer

        confidence = scorer.calculate_data_confidence(opp)
        icon = item_icon_url(
            opp.get("item_id", ""),
            quality=int(opp.get("quality") or 1),
            size=128,
        )

        # Format ingredients / optimized path summary
        ing_text = ""
        if opp.get("ingredients_lines"):
            for line in opp.get("ingredients_lines", [])[:12]:
                ing_text += f"• {line}\n"
        else:
            for ing in opp.get("ingredients_detail", []):
                qty = ing.get("quantity", 0)
                name = ing.get("name", "?")
                unit = ing.get("unit_price", 0)
                ing_text += f"• **{qty}x** {name} (@{unit:,})\n"

        if not ing_text:
            ing_text = "Check in-game recipe."

        # Add optimization note
        shopping_list_title = "📜 SHOPPING LIST (Optimized Starting Point)"

        display_name = opp.get("item_name") or opp["item_id"]
        embed = {
            "title": f"🔨 CRAFTING OPS: {display_name}",
            "description": f"Located in **{opp['crafting_city']}** | Margin: **{opp['profit_margin']:.1f}%**",
            "color": 0xFFCC00,
            "thumbnail": {"url": icon},
            "fields": [
                {"name": "🚚 SELL CITY", "value": opp.get("sell_city", "Any"), "inline": True},
                {"name": "\u200b", "value": "\u200b", "inline": True},
                {"name": "📊 REAL DEMAND (24H)", "value": f"{opp.get('daily_volume', 0):,}" if opp.get("volume_source") == "VERIFIED 24H" else f"{opp.get('daily_volume', 0):,} (Est)", "inline": True},
                {"name": "📦 CURRENT SUPPLY", "value": "N/A (Europe API)", "inline": True},
                {"name": "🔓 MARKET GAP", "value": "N/A (Europe API)", "inline": True},
                {"name": "🛡️ SAFE LIMIT", "value": f"**{opp.get('safe_limit', 1):,}** units", "inline": True},
                {"name": "🛡️ TAX STATUS", "value": f"{'Premium' if settings.is_premium else 'Non-Premium'} {(settings.tax_rate + settings.setup_fee_rate)*100:.1f}%", "inline": True},
                {"name": "🧠 DATA CONF", "value": f"**{confidence*100:.0f}%**", "inline": True},

                {"name": "💰 ECONOMICS", "value": (
                    f"Total Cost: **{opp['craft_cost']:,.0f}**\n"
                    f"Market Sell: **{opp['sell_price']:,.0f}**\n"
                    f"Net Profit: **{opp['profit']:,.0f}**\n"
                    f"🚀 Alpha Score: **{opp.get('ev_score', 0):,.0f}** EV/hr"
                ), "inline": False},

                {"name": shopping_list_title, "value": ing_text, "inline": False},

                {"name": "✨ FOCUS VALUE", "value": f"**{opp.get('profit_per_focus', 0):,.1f}** silver/focus", "inline": True},
                {"name": "📚 JOURNAL", "value": f"**+{opp.get('journal_profit', 0):,.0f}** extra", "inline": True},
                {"name": "\u200b", "value": "\u200b", "inline": True},
            ],
            "timestamp": datetime.utcnow().isoformat(),
            "footer": {"text": "Albion Quant Bot • Crafting Intelligence Engine"},
        }
        return await self._send_webhook({"embeds": [embed]})

    async def send_batch_alerts(
        self, arbitrage_opps: list[dict], crafting_opps: list[dict],
        arb_limit: int = 5, craft_limit: int = 10,
    ) -> dict:
        """Send top opportunities grouped by category."""
        stats = {"arbitrage_sent": 0, "crafting_sent": 0}

        # 1. ARBITRAGE SECTION
        if arbitrage_opps:
            top_arb = [o for o in arbitrage_opps if o.get("estimated_margin", 0) > 12.0]
            if top_arb:
                await self.send_system_message("🚚 TRANSPORT ARBITRAGE", "Top cross-city transport opportunities (Royal Cities & Caerleon).", 0x3498db)
                for opp in top_arb[:arb_limit]:
                    if await self.send_arbitrage_alert(opp):
                        stats["arbitrage_sent"] += 1
                    await asyncio.sleep(0.5)

        # 2. CONSUMABLES SECTION (Foods & Potions)
        consumables = [o for o in crafting_opps if _get_category_group(o["item_id"]) == "Consumables"]
        if consumables:
            await self.send_system_message("🧪 CONSUMABLES (FOOD & POTIONS)", "High-velocity crafting opportunities for the alchemy and cooking markets.", 0x2ecc71)
            for opp in consumables[:craft_limit]:
                if await self.send_crafting_alert(opp):
                    stats["crafting_sent"] += 1
                await asyncio.sleep(0.5)

        # 3. EQUIPMENT SECTION (Armor & Weapons)
        equipment = [o for o in crafting_opps if _get_category_group(o["item_id"]) == "Equipment"]
        if equipment:
            await self.send_system_message("⚔️ EQUIPMENT & GEAR", "Niche crafting opportunities for weapons, armor, and accessories.", 0xe74c3c)
            for opp in equipment[:craft_limit]:
                if await self.send_crafting_alert(opp):
                    stats["crafting_sent"] += 1
                await asyncio.sleep(0.5)

        # 4. RESOURCES SECTION
        resources = [o for o in crafting_opps if _get_category_group(o["item_id"]) == "Resources"]
        if resources:
            await self.send_system_message("🪵 REFINING & RESOURCES", "Opportunities in the refining and raw material markets.", 0x95a5a6)
            for opp in resources[:craft_limit]:
                if await self.send_crafting_alert(opp):
                    stats["crafting_sent"] += 1
                await asyncio.sleep(0.5)

        log.info(f"Categorized alerts sent: {stats}")
        return stats

    async def send_system_message(self, title: str, message: str, color: int = 0x5555FF) -> bool:
        """Send a system/status message."""
        embed = {
            "title": title,
            "description": message,
            "color": color,
            "timestamp": datetime.utcnow().isoformat(),
            "footer": {"text": "Albion Quant System"},
        }
        return await self._send_webhook({"embeds": [embed]})
