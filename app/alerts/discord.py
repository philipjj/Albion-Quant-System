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


class DiscordAlerter:
    def __init__(self):
        self.webhook_url = settings.discord_webhook_url
        self.bm_webhook_url = settings.discord_bm_webhook_url
        self.enabled = bool(
            (self.webhook_url and "YOUR_WEBHOOK" not in self.webhook_url)
            or (self.bm_webhook_url and "YOUR_WEBHOOK" not in self.bm_webhook_url)
        )

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

        return False

    def _format_arbitrage_embed(self, opp: dict) -> dict:
        confidence = scorer.calculate_data_confidence(opp)
        badge = SERVER_BADGES.get(settings.active_server.value, "[UNKNOWN]")
        margin = opp["estimated_margin"]

        # Color coding by opportunity quality
        dest_city = opp["destination_city"]
        if dest_city == "Black Market":
            dest_city = "☠️ Black Market"
            color = 0x9B59B6  # Purple for BM
        elif margin > 30:
            color = 0x57F287  # Discord green — strong margin
        elif margin > 15:
            color = 0xFEE75C  # Discord yellow — moderate
        else:
            color = 0xFFAA00  # Amber — thin margin

        # Build description with visual margin bar
        bar_filled = min(int(margin / 5), 10)
        bar_empty = 10 - bar_filled
        margin_bar = "█" * bar_filled + "░" * bar_empty

        desc = f"**{margin:.1f}%** `{margin_bar}` margin"
        if opp.get("can_be_crafted"):
            desc += f"\n🔨 Craftable at **{opp.get('craft_city')}** (Cost: **{opp.get('craft_cost', 0):,.0f}**)"
        if opp.get("coverage_suspect"):
            desc += "\n⚠️ Low volume — price may be stale"

        embed = {
            "title": f"⚔️ {badge} {opp['item_name']}",
            "description": desc,
            "color": color,
            "thumbnail": {
                "url": item_icon_url(opp["item_id"], quality=opp.get("quality", 1), size=128)
            },
            "fields": [
                {
                    "name": "🏙️ ROUTE",
                    "value": f"**{opp['source_city']}** ➔ {dest_city}",
                    "inline": False,
                },
                {"name": "BUY", "value": f"`{opp['buy_price']:,.0f}`", "inline": True},
                {"name": "SELL", "value": f"`{opp['sell_price']:,.0f}`", "inline": True},
                {
                    "name": "💰 PROFIT",
                    "value": f"**{opp['estimated_profit']:,.0f}**",
                    "inline": True,
                },
                {
                    "name": "🛡️ SAFE QTY",
                    "value": f"**{opp.get('safe_limit', 0):,}** / {opp.get('daily_volume', 0):,} vol",
                    "inline": True,
                },
                {"name": "🚀 EV", "value": f"**{opp.get('ev_score', 0):,.0f}**", "inline": True},
                {"name": "⚖️ RISK", "value": _risk_label(opp.get("risk_score", 0)), "inline": True},
            ],
            "footer": {"text": f"AQS v3.2 • {settings.active_server.value.upper()} Market"},
            "timestamp": datetime.utcnow().isoformat(),
        }

        return embed

    def _format_crafting_embed(self, opp: dict) -> dict:
        confidence = scorer.calculate_data_confidence(opp)
        badge = SERVER_BADGES.get(settings.active_server.value, "[UNKNOWN]")
        margin = opp["profit_margin"]

        # Color coding
        sell_city = opp.get("sell_city", "Any")
        if sell_city == "Black Market":
            sell_city = "☠️ Black Market"
            color = 0x9B59B6
        elif margin > 25:
            color = 0x57F287  # Green — strong
        elif margin > 10:
            color = 0xFEE75C  # Yellow — moderate
        else:
            color = 0xFFAA00  # Amber

        # Build Crafting Path string with proper names
        details = opp.get("details", opp.get("ingredients", []))
        path_lines = []
        rrr = opp.get("rrr_used", 0.0)

        for d in details:
            mode = d.get("mode")
            if not mode:
                mode = "BUY" if d.get("buy_city") else "CRAFT"

            mode_icon = "🛒" if mode == "BUY" else "🔨"
            raw_qty = d.get("quantity", 1)
            qty = int(raw_qty) if raw_qty == int(raw_qty) else raw_qty

            # Use localized name from engine, fallback to readable item_id
            name = d.get("name")
            if not name or name == d.get("id") or name == d.get("item_id"):
                raw_id = d.get("item_id", d.get("id", "Unknown"))
                name = raw_id.replace("_", " ").title()

            price = d.get("unit_price", 0)
            is_returnable = d.get("is_returnable", False)

            if is_returnable and rrr > 0:
                net_price = price * (1.0 - rrr)
                path_lines.append(f"{mode_icon} x{qty} {name}")
                path_lines.append(f"   └ @{price:,.0f} ➔ Net: {net_price:,.0f}")
            else:
                path_lines.append(f"{mode_icon} x{qty} {name}")
                path_lines.append(f"   └ @{price:,.0f}")

        path_str = "\n".join(path_lines)

        # Build margin bar
        bar_filled = min(int(margin / 5), 10)
        bar_empty = 10 - bar_filled
        margin_bar = "█" * bar_filled + "░" * bar_empty

        desc = f"**{margin:.1f}%** `{margin_bar}` @ {opp['crafting_city']}"
        if opp.get("coverage_suspect"):
            desc += "\n⚠️ Low volume — price may be stale"

        embed = {
            "title": f"🔨 {badge} {opp['item_name']}",
            "description": desc,
            "color": color,
            "thumbnail": {
                "url": item_icon_url(opp["item_id"], quality=opp.get("quality", 1), size=128)
            },
            "fields": [
                {"name": "🚢 SELL AT", "value": f"**{sell_city}**", "inline": True},
                {"name": "💰 PROFIT", "value": f"**{opp['profit']:,.0f}**", "inline": True},
                {"name": "🛠️ COST", "value": f"**{opp.get('craft_cost', 0):,.0f}**", "inline": True},
                {
                    "name": "📈 VOL",
                    "value": f"**{opp.get('daily_volume', 0):,}**/day",
                    "inline": True,
                },
                {"name": "🚀 EV", "value": f"**{opp.get('ev_score', 0):,.0f}**", "inline": True},
                {
                    "name": "♻️ RRR",
                    "value": f"**{opp.get('rrr_used', 0.152) * 100:.1f}%** {'🔮 Focus' if opp.get('use_focus') else ''}",
                    "inline": True,
                },
                {
                    "name": "📜 INGREDIENTS",
                    "value": f"```\n{path_str[:900]}\n```" if path_str else "No details",
                    "inline": False,
                },
            ],
            "footer": {"text": f"AQS v3.2 • {settings.active_server.value.upper()} Market"},
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
        arb_limit: int = 5,
        craft_limit: int = 10,
    ):
        # Process Arbitrage Opportunities
        for opp in arb_opps[:arb_limit]:
            embed = self._format_arbitrage_embed(opp)
            # Route to BM webhook if destination is Black Market
            target_webhook = (
                self.bm_webhook_url
                if opp.get("destination_city") == "Black Market" and self.bm_webhook_url
                else self.webhook_url
            )
            if target_webhook:
                await self._send_webhook({"embeds": [embed]}, webhook_url=target_webhook)
                await asyncio.sleep(4.0)  # 4-second gap to allow user to read

        # Process Crafting Opportunities
        for opp in craft_opps[:craft_limit]:
            embed = self._format_crafting_embed(opp)
            # Route to BM webhook if sell city is Black Market
            target_webhook = (
                self.bm_webhook_url
                if opp.get("sell_city") == "Black Market" and self.bm_webhook_url
                else self.webhook_url
            )
            if target_webhook:
                await self._send_webhook({"embeds": [embed]}, webhook_url=target_webhook)
                await asyncio.sleep(4.0)  # 4-second gap to allow user to read
