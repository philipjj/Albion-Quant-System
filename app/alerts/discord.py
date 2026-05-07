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

def _get_category_group(item_id: str) -> str:
    id_upper = item_id.upper()
    if any(k in id_upper for k in ["POTION", "FOOD", "MEAL", "SOUP", "STEW"]):
        return "Consumables"
    if any(k in id_upper for k in ["WOOD", "ORE", "FIBER", "HIDE", "ROCK", "BAR", "PLANK", "CLOTH", "LEATHER", "STONE"]):
        return "Resources"
    return "Equipment"

class DiscordAlerter:
    def __init__(self):
        self.webhook_url = settings.discord_webhook_url
        self.enabled = bool(self.webhook_url and "YOUR_WEBHOOK" not in self.webhook_url)

    async def _send_webhook(self, payload: dict) -> bool:
        if not self.enabled: return False
        payload["username"] = "Albion Quant Bot"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self.webhook_url, json=payload)
                resp.raise_for_status()
                return True
        except Exception as e:
            log.error(f"Discord webhook failed: {e}")
            return False

    async def send_arbitrage_alert(self, opp: dict) -> bool:
        confidence = scorer.calculate_data_confidence(opp)
        badge = SERVER_BADGES.get(settings.active_server.value, "[UNKNOWN]")
        
        # [v3.1] Special Black Market Branding
        dest_city = opp['destination_city']
        if dest_city == "Black Market":
            dest_city = "🏷️ Black Market"
            color = 0x9B59B6 # Purple for BM
        else:
            color = 0x00FF88 if opp["estimated_margin"] > 30 else 0xFFAA00
        
        embed = {
            "title": f"⚔️ {badge} ARBITRAGE: {opp['item_name']}",
            "description": f"Margin: **{opp['estimated_margin']:.1f}%**",
            "color": color,
            "thumbnail": {"url": item_icon_url(opp["item_id"], quality=opp.get("quality", 1), size=128)},
            "fields": [
                {"name": "🏙️ ROUTE", "value": f"**{opp['source_city']}** ➔ **{dest_city}**", "inline": True},
                {"name": "⚖️ RISK", "value": _risk_label(opp.get("risk_score", 0)), "inline": True},
                {"name": "💎 PROFIT", "value": f"**{opp['estimated_profit']:,.0f}**", "inline": True},
                {"name": "🚀 ALPHA", "value": f"**{opp.get('ev_score', 0):,.0f}**", "inline": True},
                {"name": "🧠 CONF", "value": f"**{confidence*100:.0f}%**", "inline": True},
                {"name": "📊 VOL", "value": f"{opp.get('daily_volume', 0):,}", "inline": True},
            ],
            "footer": {"text": f"AQS v3.1 High-Efficiency • {settings.active_server.value.upper()} Market"},
            "timestamp": datetime.utcnow().isoformat()
        }
        
        if opp.get("coverage_suspect"):
            embed["description"] += "\n⚠️ **ENCRYPTION GAP**: 0 Volume, price may be stale."
            
        return await self._send_webhook({"embeds": [embed]})

    async def send_crafting_alert(self, opp: dict) -> bool:
        confidence = scorer.calculate_data_confidence(opp)
        badge = SERVER_BADGES.get(settings.active_server.value, "[UNKNOWN]")
        
        # [v3.1] Black Market Destination logic
        sell_city = opp.get("sell_city", "Any")
        if sell_city == "Black Market":
            sell_city = "🏷️ Black Market"
            color = 0x9B59B6
        else:
            color = 0xFFCC00

        # Build Crafting Path string
        details = opp.get("details", [])
        path_str = ""
        for d in details:
            mode_icon = "🛒" if d.get("mode") == "BUY" else "🔨"
            qty = d.get("quantity", 1)
            # Cleanup names: T4_HEAD_CLOTH_SET1 -> Cloth Headgear
            raw_name = d.get("id", "Unknown")
            name = raw_name.split("_")[1] if "_" in raw_name else raw_name
            price = d.get("unit_price", 0)
            path_str += f"{mode_icon} x{qty} {name} (@{price:,.0f})\n"
            
        embed = {
            "title": f"🔨 {badge} CRAFTING: {opp['item_name']}",
            "description": f"Margin: **{opp['profit_margin']:.1f}%** @ {opp['crafting_city']}",
            "color": color,
            "thumbnail": {"url": item_icon_url(opp["item_id"], quality=opp.get("quality", 1), size=128)},
            "fields": [
                {"name": "🚚 SELL CITY", "value": sell_city, "inline": True},
                {"name": "💰 PROFIT", "value": f"**{opp['profit']:,.0f}**", "inline": True},
                {"name": "🚀 ALPHA", "value": f"**{opp.get('ev_score', 0):,.0f}**", "inline": True},
                {"name": "🧠 CONF", "value": f"**{confidence*100:.0f}%**", "inline": True},
                {"name": "📊 VOL", "value": f"{opp.get('daily_volume', 0):,}", "inline": True},
                {"name": "📜 CRAFTING PATH", "value": f"```\n{path_str[:900]}\n```" if path_str else "No details", "inline": False},
            ],
            "footer": {"text": f"AQS v3.1 High-Efficiency • {settings.active_server.value.upper()} Market"},
            "timestamp": datetime.utcnow().isoformat()
        }
        
        if opp.get("coverage_suspect"):
            embed["description"] += "\n⚠️ **ENCRYPTION GAP**: 0 Volume, price may be stale."

        return await self._send_webhook({"embeds": [embed]})

    async def send_batch_alerts(self, arb_opps: list[dict], craft_opps: list[dict], arb_limit: int = 5, craft_limit: int = 10):
        for opp in arb_opps[:arb_limit]:
            await self.send_arbitrage_alert(opp)
            await asyncio.sleep(1.0)
        for opp in craft_opps[:craft_limit]:
            await self.send_crafting_alert(opp)
            await asyncio.sleep(1.0)
