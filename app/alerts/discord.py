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
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(self.webhook_url, json=payload)
                    
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
                log.error(f"Discord webhook failed with status {e.response.status_code} (Attempt {attempt+1}/{max_retries})")
                if attempt == max_retries - 1:
                    return False
            except Exception as e:
                log.error(f"Discord webhook failed: {e} (Attempt {attempt+1}/{max_retries})")
                if attempt == max_retries - 1:
                    return False
            
            await asyncio.sleep(1.0)
            
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

    async def send_signal_alert(self, signal: dict) -> bool:
        """Sends an alert for an alpha signal."""
        badge = SERVER_BADGES.get(settings.active_server.value, "[UNKNOWN]")
        color = 0x3498DB # Blue for signals
        
        embed = {
            "title": f"📈 {badge} SIGNAL: {signal['item_id']}",
            "description": f"Signal Type: **{signal['signal_type'].upper()}**",
            "color": color,
            "thumbnail": {"url": item_icon_url(signal["item_id"], quality=1, size=128)},
            "fields": [
                {"name": "🚀 ALPHA SCORE", "value": f"**{signal['alpha_score']:.2f}**", "inline": True},
                {"name": "🧠 CONFIDENCE", "value": f"**{signal['confidence']*100:.0f}%**", "inline": True},
                {"name": "⚖️ RISK (MANIP)", "value": f"**{signal['manipulation_risk']:.2f}**", "inline": True},
                {"name": "💧 LIQUIDITY", "value": f"**{signal.get('liquidity_score', 0):.2f}**", "inline": True},
                {"name": "⏳ PERSISTENCE", "value": f"**{signal.get('persistence_score', 0):.2f}**", "inline": True},
                {"name": "🗂️ CLUSTER", "value": signal.get("cluster_id", "None"), "inline": True},
            ],
            "footer": {"text": f"AQS vNext Signal Engine • {settings.active_server.value.upper()} Market"},
            "timestamp": datetime.utcnow().isoformat()
        }
        
        return await self._send_webhook({"embeds": [embed]})

    async def send_patch_alert(self, patch_event: dict) -> bool:
        """Sends an alert for a patch or NDA update."""
        badge = SERVER_BADGES.get(settings.active_server.value, "[UNKNOWN]")
        color = 0xE67E22 # Orange for patch alerts
        
        embed = {
            "title": f"⚔️ {badge} PATCH/META SHIFT DETECTED",
            "description": f"**{patch_event['title']}**\n\n{patch_event['content']}",
            "color": color,
            "fields": [
                {"name": "🎯 EXPECTED IMPACT", "value": patch_event.get("impact", "Unknown"), "inline": False},
                {"name": "🧠 CONFIDENCE", "value": f"**{patch_event.get('confidence', 'MEDIUM')}**", "inline": True},
                {"name": "⏳ WINDOW", "value": patch_event.get("window", "24-72h"), "inline": True},
            ],
            "footer": {"text": f"AQS Patch Intelligence • {settings.active_server.value.upper()} Market"},
            "timestamp": datetime.utcnow().isoformat()
        }
        
        return await self._send_webhook({"embeds": [embed]})

    async def send_meta_alert(self, meta_event: dict) -> bool:
        """Sends an alert for a meta surge or build rotation."""
        badge = SERVER_BADGES.get(settings.active_server.value, "[UNKNOWN]")
        color = 0xE74C3C # Red for meta surges
        
        embed = {
            "title": f"🔥 {badge} META SURGE: {meta_event['item_id']}",
            "description": f"Meta demand score spike detected!",
            "color": color,
            "fields": [
                {"name": "🚀 META SCORE", "value": f"**{meta_event['score']:.2f}**", "inline": True},
                {"name": "📈 TREND", "value": f"**{meta_event.get('trend', 'UP')}**", "inline": True},
                {"name": "📊 USAGE", "value": f"{meta_event.get('usage', 'N/A')}", "inline": True},
            ],
            "footer": {"text": f"AQS PvP Meta Engine • {settings.active_server.value.upper()} Market"},
            "timestamp": datetime.utcnow().isoformat()
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
            "META SURGE": 0xE74C3C, # Red
            "PATCH BUFF": 0x2ECC71, # Green
            "PATCH NERF": 0xC0392B, # Dark Red
            "BUILD ROTATION": 0x3498DB, # Blue
            "RESOURCE PRESSURE": 0xF1C40F, # Yellow
            "BM META PULL": 0x9B59B6 # Purple
        }
        
        color = colors.get(category, 0x95A5A6) # Default Gray
        
        embed = {
            "title": f"📢 {badge} {category}: {data.get('item_name', data.get('item_id', 'Global'))}",
            "description": data.get("description", f"Alert for {category}"),
            "color": color,
            "fields": [],
            "footer": {"text": f"AQS vNext Intelligence • {settings.active_server.value.upper()} Market"},
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Add dynamic fields if present
        for key, val in data.items():
            if key not in ["item_name", "item_id", "description"]:
                embed["fields"].append({"name": key.upper().replace("_", " "), "value": str(val), "inline": True})
                
        # Add thumbnail if item_id is present
        if "item_id" in data:
            embed["thumbnail"] = {"url": item_icon_url(data["item_id"], quality=data.get("quality", 1), size=128)}
            
        return await self._send_webhook({"embeds": [embed]})

    async def send_batch_alerts(self, arb_opps: list[dict], craft_opps: list[dict], arb_limit: int = 5, craft_limit: int = 10):

        for opp in arb_opps[:arb_limit]:
            await self.send_arbitrage_alert(opp)
            await asyncio.sleep(1.0)
        for opp in craft_opps[:craft_limit]:
            await self.send_crafting_alert(opp)
            await asyncio.sleep(1.0)

