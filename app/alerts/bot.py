import asyncio
import io
import json
import re
from datetime import datetime, timezone

import discord
from discord.ext import commands

from app.core.config import AlbionServer, settings
from app.core.icons import item_icon_url
from app.core.logging import log
from app.db.models import ArbitrageOpportunity, CraftingOpportunity, Item, MarketPrice
from app.db.session import get_db_session

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

SERVER_BADGES = {
    "west": "🇺🇸 [WEST]",
    "east": "🇸🇬 [ASIA]",
    "europe": "🇪🇺 [EUROPE]",
}


@bot.event
async def on_ready():
    from app.core import state

    log.info(f"Discord Bot AQS v3.2 logged in as {bot.user}")

    badge = SERVER_BADGES.get(settings.active_server.value, "[UNKNOWN]")
    tier_str = f"T{state.tier_lock}" if state.tier_lock else "ALL"

    # Send standby dashboard to the first available text channel
    for guild in bot.guilds:
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                embed = discord.Embed(
                    title="",
                    description=(
                        "```ansi\n"
                        "\x1b[1;33m╔══════════════════════════════════════╗\n"
                        "║     ALBION QUANT SYSTEM  v3.2        ║\n"
                        "║         ⏸️  STANDBY MODE              ║\n"
                        "╚══════════════════════════════════════╝\n"
                        "\x1b[0m```"
                    ),
                    color=0x2B2D31,  # Discord dark embed
                )
                embed.add_field(
                    name="📡 SYSTEM",
                    value=(
                        f"> Server: **{badge}**\n> Tier Lock: **{tier_str}**\n> Engine: **PAUSED**"
                    ),
                    inline=True,
                )
                embed.add_field(
                    name="⚙️ BEFORE LAUNCH",
                    value=(
                        "> `!purge DD/MM DD/MM` — Clear old alerts\n"
                        "> `!server europe` — Switch region\n"
                        "> `!tier 4` — Lock to a tier\n"
                        "> `!status` — Check DB health"
                    ),
                    inline=True,
                )
                embed.add_field(
                    name="\u200b",  # spacer
                    value=(
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        "🟢 Type **`!start`** when ready to begin scanning\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                    ),
                    inline=False,
                )
                embed.set_footer(text="AQS v3.2 Quantitative Engine • Standby")
                embed.timestamp = datetime.now(timezone.utc)
                await channel.send(embed=embed)
                return  # Only send to first writable channel


@bot.command()
async def help(ctx):
    """Custom help command for AQS manual controls."""
    embed = discord.Embed(
        title="📖  AQS Command Reference",
        description="Albion Quant System v3.2 — All available commands",
        color=0x5865F2,  # Discord blurple
    )

    embed.add_field(
        name="🔧 SYSTEM",
        value=(
            "`!start` — Launch the scanning engine\n"
            "`!stop` — Pause all background tasks\n"
            "`!status` — System health dashboard\n"
            "`!server [name]` — Switch region\n"
            "`!schedule [time]` — Set poll interval"
        ),
        inline=True,
    )
    embed.add_field(
        name="🎯 FILTERS",
        value=(
            "`!tier [num|all]` — Lock to tier\n"
            "`!minbm <profit>` — BM min profit\n"
            "`!mincraft <profit>` — Craft min profit"
        ),
        inline=True,
    )
    embed.add_field(
        name="📊 DATA",
        value=(
            "`!price <item>` — City prices\n"
            "`!scan [bm]` — Manual scan\n"
            "`!bm` — BM shortages\n"
            "`!meta` — PvP meta items\n"
            "`!patch` — Patch intel"
        ),
        inline=True,
    )
    embed.add_field(
        name="🚀 TOOLS",
        value=(
            "`!caravan <src> <dst> [kg]` — Trade route packer\n"
            "`!focus [amount] [spec]` — Focus optimizer\n"
            "`!purge <start> <end>` — Delete messages (DD/MM/YYYY)"
        ),
        inline=False,
    )
    embed.set_footer(text="AQS v3.2 • Use !price <name> for fuzzy search")
    await ctx.send(embed=embed)


@bot.command(name="price")
async def price_cmd(ctx, *, query: str):
    """Prices across all royal cities for any item.
    Usage:
      !price T6_MAIN_SWORD            direct ID, enchant 0, Normal quality
      !price T6_MAIN_SWORD@2          direct ID, enchant 2, Normal quality
      !price T6_MAIN_SWORD@2 3        direct ID, enchant 2, Outstanding quality
      !price broadsword               name search, enchant 0, Normal quality
      !price broadsword @2            name search, enchant 2, Normal quality
      !price broadsword @2 3          name search, enchant 2, Outstanding quality
    """
    import re as _re

    query = query.strip()
    quality = 1
    enchant_override = None

    QUALITY_NAMES = {1: "Normal", 2: "Good", 3: "Outstanding", 4: "Excellent", 5: "Masterpiece"}
    ROYAL_CITIES = ["Bridgewatch", "Martlock", "Lymhurst", "Fort Sterling", "Thetford"]
    CITY_SHORT = {
        "Bridgewatch": "BRW",
        "Martlock": "MRT",
        "Lymhurst": "LYM",
        "Fort Sterling": "FST",
        "Thetford": "THF",
    }

    # Strip trailing quality number 1-5
    quality_match = _re.search(r"\s+([1-5])$", query)
    if quality_match:
        quality = int(quality_match.group(1))
        query = query[: quality_match.start()].strip()

    # Strip trailing @N enchantment (for name searches only)
    enchant_match = _re.search(r"\s+@([0-4])$", query)
    if enchant_match:
        enchant_override = int(enchant_match.group(1))
        query = query[: enchant_match.start()].strip()

    def fmt_price(p):
        return f"{int(p):,}" if p and int(p) > 0 else "—"

    def fmt_age(sec):
        if sec is None:
            return "?"
        sec = int(sec)
        if sec < 60:
            return f"{sec}s"
        if sec < 3600:
            return f"{sec // 60}m"
        return f"{sec // 3600}h {(sec % 3600) // 60}m"

    with get_db_session() as db:
        # Mode 1: direct item ID (e.g. T6_MAIN_SWORD or T6_MAIN_SWORD@2)
        if _re.match(r"^[Tt][1-8]_", query):
            item = db.query(Item).filter_by(item_id=query.upper()).first()
            if not item:
                await ctx.send(
                    f"❌ `{query.upper()}` not found. Use `!price <name>` to search by name."
                )
                return
            matched = [item]

        # Mode 2: name search — covers every item in the game
        else:
            q = db.query(Item).filter(Item.name.ilike(f"%{query}%"))
            if enchant_override is not None:
                q = q.filter(Item.enchant == enchant_override)
            matched = q.order_by(Item.tier, Item.enchant, Item.name).limit(11).all()

            if not matched:
                await ctx.send(
                    f"❌ No items found for `{query}`. Try a broader name or use a direct item ID."
                )
                return

            if len(matched) > 1:
                lines = [f"`{i.item_id}` — {i.name} (T{i.tier}.{i.enchant})" for i in matched[:10]]
                if len(matched) == 11:
                    lines.append("*…more results — refine your search*")
                embed = discord.Embed(
                    title=f'🔍 Multiple matches for "{query}"',
                    description="\n".join(lines),
                    color=discord.Color.orange(),
                )
                embed.set_footer(text="Use the exact item ID: !price T6_MAIN_SWORD@2 3")
                await ctx.send(embed=embed)
                return

        item = matched[0]

        city_rows = {}
        for city in ROYAL_CITIES:
            row = (
                db.query(MarketPrice)
                .filter(
                    MarketPrice.item_id == item.item_id,
                    MarketPrice.city == city,
                    MarketPrice.quality == quality,
                )
                .order_by(MarketPrice.captured_at.desc())
                .first()
            )
            city_rows[city] = row

        lines = []
        for city in ROYAL_CITIES:
            row = city_rows[city]
            abbr = CITY_SHORT[city]
            if row and (row.sell_price_min or row.buy_price_max):
                sell = fmt_price(row.sell_price_min)
                buy = fmt_price(row.buy_price_max)
                vol = row.volume_24h or 0
                age = fmt_age(row.data_age_seconds)
                lines.append(f"`{abbr}` Sell `{sell}` · Buy `{buy}` · Vol `{vol}` · `{age}` ago")
            else:
                lines.append(f"`{abbr}` — no data")

        embed = discord.Embed(
            title=f"📊 {item.name}",
            description=f"`{item.item_id}` · T{item.tier}.{item.enchant} · {QUALITY_NAMES.get(quality, 'Unknown')}",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Royal City Prices", value="\n".join(lines), inline=False)
        embed.set_thumbnail(url=item_icon_url(item.item_id, quality=quality, size=64))
        embed.set_footer(
            text="Sell = cheapest sell order (what you pay) · Buy = highest buy order (instant sell)"
        )
        await ctx.send(embed=embed)


@bot.command()
async def purge(ctx, start_str: str, end_str: str):
    """
    Delete messages in a date range.
    Usage: !purge 01/02/2026 01/04/2026
    """
    try:
        # Parse dates (assuming DD/MM/YYYY)
        start_date = datetime.strptime(start_str, "%d/%m/%Y").replace(tzinfo=timezone.utc)
        end_date = datetime.strptime(end_str, "%d/%m/%Y").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc
        )

        if start_date > end_date:
            await ctx.send("❌ Start date must be before end date.")
            return

        await ctx.send(
            f"🧹 **Purging messages** from {start_str} to {end_str}... this may take a while."
        )

        def check(m):
            return start_date <= m.created_at <= end_date

        deleted = await ctx.channel.purge(limit=1000, check=check, bulk=True)
        await ctx.send(
            f"✅ Successfully deleted **{len(deleted)}** messages from the specified range.",
            delete_after=5,
        )

    except ValueError:
        await ctx.send("❌ Invalid date format. Please use **DD/MM/YYYY**.")
    except Exception as e:
        await ctx.send(f"❌ Error during purge: {e}")


@bot.command()
async def status(ctx):
    """Check system health and active server."""
    from sqlalchemy import func

    from app.core import state

    with get_db_session() as db:
        price_count = db.query(func.count(MarketPrice.id)).scalar()
        arb_count = (
            db.query(func.count(ArbitrageOpportunity.id))
            .filter(ArbitrageOpportunity.is_active == True)
            .scalar()
        )
        craft_count = (
            db.query(func.count(CraftingOpportunity.id))
            .filter(CraftingOpportunity.is_active == True)
            .scalar()
        )

    badge = SERVER_BADGES.get(settings.active_server.value, "[UNKNOWN]")
    scheduler_status = (
        "🟢 ACTIVE"
        if state.scheduler_instance and state.scheduler_instance._is_running
        else "🔴 PAUSED"
    )
    interval = settings.market_poll_interval

    embed = discord.Embed(title="📊 AQS v3.0 System Status", color=discord.Color.blue())
    embed.add_field(name="Active Server", value=f"**{badge}**", inline=True)
    embed.add_field(name="Scheduler", value=scheduler_status, inline=True)
    embed.add_field(name="Interval", value=f"**{interval} min**", inline=True)

    embed.add_field(name="Market Data", value=f"Price Records: **{price_count:,}**", inline=False)
    embed.add_field(
        name="Active Opps",
        value=f"Arbitrage: **{arb_count}** | Crafting: **{craft_count}**",
        inline=False,
    )

    await ctx.send(embed=embed)


@bot.command()
async def server(ctx, name: str = None):
    """View or switch the active Albion server."""
    if not name:
        badge = SERVER_BADGES.get(settings.active_server.value, "[UNKNOWN]")
        await ctx.send(f"Current Active Server: **{badge}**")
        return

    name = name.lower()
    if name not in ["west", "east", "europe"]:
        await ctx.send("❌ Invalid server. Use `west`, `east`, or `europe`.")
        return

    settings.active_server = AlbionServer(name)
    badge = SERVER_BADGES.get(name, "[UNKNOWN]")
    await ctx.send(f"✅ Switched to **{badge}**. Next collection will target this region.")


@bot.command(name="schedule")
async def schedule_cmd(ctx, *, time_str: str):
    """Manually set the polling interval."""
    from app.core import state

    if not state.scheduler_instance:
        await ctx.send("❌ Scheduler instance not initialized.")
        return

    minutes = 0
    hours_match = re.search(r"(\d+)\s*(h|hr|hour)", time_str, re.IGNORECASE)
    mins_match = re.search(r"(\d+)\s*(m|min|minute)", time_str, re.IGNORECASE)
    only_num = re.match(r"^(\d+)$", time_str.strip())

    if only_num:
        minutes = int(only_num.group(1))
    else:
        if hours_match:
            minutes += int(hours_match.group(1)) * 60
        if mins_match:
            minutes += int(mins_match.group(1))

    if minutes < 1:
        await ctx.send("❌ Invalid time format. Examples: `!schedule 30m`, `!schedule 1h 30m`.")
        return

    state.scheduler_instance.reschedule(minutes)
    await ctx.send(f"📅 **Scheduler Updated**: Poll interval set to **{minutes} minutes**.")


@bot.command()
async def start(ctx):
    """Launch the AQS scanning engine with a countdown sequence."""
    from app.core import state

    if not state.scheduler_instance:
        await ctx.send("❌ Scheduler not available.")
        return

    if state.scheduler_instance._is_running:
        await ctx.send("⚠️ Engine is already running. Use `!stop` first to restart.")
        return

    badge = SERVER_BADGES.get(settings.active_server.value, "[UNKNOWN]")
    tier_str = f"T{state.tier_lock}" if state.tier_lock else "ALL"

    # Phase 1: Launch countdown
    launch_embed = discord.Embed(
        title="",
        description=(
            "```ansi\n"
            "\x1b[1;32m╔══════════════════════════════════════╗\n"
            "║       🚀  LAUNCH SEQUENCE            ║\n"
            "╚══════════════════════════════════════╝\n"
            "\x1b[0m```"
        ),
        color=0x57F287,  # Discord green
    )
    launch_embed.add_field(
        name="📡 CONFIG",
        value=(
            f"> Server: **{badge}**\n"
            f"> Tier: **{tier_str}**\n"
            f"> Interval: **{settings.market_poll_interval}m**"
        ),
        inline=True,
    )
    launch_embed.add_field(
        name="⏳ STATUS",
        value=("> Initializing engines...\n> Connecting to AODP...\n> Warming up scanners..."),
        inline=True,
    )
    launch_embed.set_footer(text="AQS v3.2 • Starting up...")
    launch_embed.timestamp = datetime.now(timezone.utc)
    msg = await ctx.send(embed=launch_embed)

    await asyncio.sleep(2)

    # Phase 2: Actually start
    state.scheduler_instance.start()
    state.standby_mode = False

    # Phase 3: Confirm active
    active_embed = discord.Embed(
        title="",
        description=(
            "```ansi\n"
            "\x1b[1;32m╔══════════════════════════════════════╗\n"
            "║      ✅  ENGINE ONLINE                ║\n"
            "╚══════════════════════════════════════╝\n"
            "\x1b[0m```"
        ),
        color=0x57F287,
    )
    active_embed.add_field(
        name="📡 ACTIVE CONFIG",
        value=(
            f"> Server: **{badge}**\n"
            f"> Tier: **{tier_str}**\n"
            f"> Interval: **{settings.market_poll_interval}m**"
        ),
        inline=True,
    )
    active_embed.add_field(
        name="✅ STATUS",
        value=("> Engines: **ONLINE** 🟢\n> Scanner: **ACTIVE** 🟢\n> Alerts: **ARMED** 🟢"),
        inline=True,
    )
    active_embed.add_field(
        name="\u200b",
        value="Alerts will begin arriving shortly. Use `!stop` to pause.",
        inline=False,
    )
    active_embed.set_footer(text="AQS v3.2 Quantitative Engine • LIVE")
    active_embed.timestamp = datetime.now(timezone.utc)
    await msg.edit(embed=active_embed)


@bot.command()
async def stop(ctx):
    """Pause the background collector/scanner."""
    from app.core import state

    if not state.scheduler_instance:
        await ctx.send("❌ Scheduler not available.")
        return

    if not state.scheduler_instance._is_running:
        await ctx.send("⚠️ Engine is already stopped.")
        return

    state.scheduler_instance.stop()
    state.standby_mode = True

    embed = discord.Embed(
        title="",
        description=(
            "```ansi\n"
            "\x1b[1;31m╔══════════════════════════════════════╗\n"
            "║       ⏸️  ENGINE PAUSED               ║\n"
            "╚══════════════════════════════════════╝\n"
            "\x1b[0m```"
        ),
        color=0xED4245,  # Discord red
    )
    embed.add_field(
        name="STATUS",
        value=("> Engines: **OFFLINE** 🔴\n> Scanner: **PAUSED** 🔴\n> Alerts: **DISARMED** 🔴"),
        inline=True,
    )
    embed.add_field(
        name="CONTROLS",
        value=(
            "> `!start` — Resume scanning\n"
            "> `!scan` — One-shot manual scan\n"
            "> `!purge` — Clean up messages"
        ),
        inline=True,
    )
    embed.set_footer(text="AQS v3.2 • Paused")
    embed.timestamp = datetime.now(timezone.utc)
    await ctx.send(embed=embed)


@bot.command()
async def tier(ctx, tier_val: str = ""):
    """Lock alerts to a specific tier (e.g., !tier 4) or unlock with !tier all."""
    from app.core import state

    tier_val = tier_val.strip().lower()

    if not tier_val:
        current = f"T{state.tier_lock}" if state.tier_lock else "ALL"
        await ctx.send(
            f"ℹ️ Current tier lock: **{current}**\nUse `!tier <4-8>` to lock or `!tier all` to unlock."
        )
        return

    if tier_val == "all":
        state.tier_lock = None
        await ctx.send("🔓 **Tier Lock Removed**: Now showing opportunities for ALL tiers.")
        return

    if tier_val.isdigit() and 1 <= int(tier_val) <= 8:
        state.tier_lock = int(tier_val)
        await ctx.send(
            f"🔒 **Tier Lock Enabled**: Only showing opportunities for **Tier {state.tier_lock}** items."
        )
    else:
        await ctx.send("❌ Invalid tier. Please specify a number between 1 and 8, or 'all'.")


@bot.command()
async def minbm(ctx, profit: int = None):
    """Set minimum profit for Black Market alerts."""
    from app.core import state

    if profit is None:
        await ctx.send(
            f"ℹ️ Current **Black Market Minimum Profit** is **{state.min_bm_profit:,}** silver."
        )
        return
    if profit < 0:
        await ctx.send("❌ Profit cannot be negative.")
        return
    state.min_bm_profit = profit
    await ctx.send(f"✅ **Black Market Minimum Profit** set to **{profit:,}** silver.")


@bot.command()
async def mincraft(ctx, profit: int = None):
    """Set minimum profit for Crafting alerts."""
    from app.core import state

    if profit is None:
        await ctx.send(
            f"ℹ️ Current **Crafting Minimum Profit** is **{state.min_craft_profit:,}** silver."
        )
        return
    if profit < 0:
        await ctx.send("❌ Profit cannot be negative.")
        return
    state.min_craft_profit = profit
    await ctx.send(f"✅ **Crafting Minimum Profit** set to **{profit:,}** silver.")


@bot.command()
async def scan(ctx, bm_flag: str = ""):
    """Trigger a manual scan using the UnifiedScanner (same engine as scheduler).
    Usage: !scan [bm]
    """
    scan_bm = bm_flag.lower() == "bm"

    await ctx.send(
        f"🚀 Starting manual scan for **{settings.active_server.value.upper()}**... (BM: {'enabled' if scan_bm else 'disabled'})"
    )
    from app.alerts.discord import DiscordAlerter
    from app.core.scanner_integration import UnifiedScanner

    alerter = DiscordAlerter()
    scanner = UnifiedScanner()

    try:
        bm, crafting, arb = await scanner.scan_all(scan_bm=scan_bm)
        all_arb = bm + arb

        await alerter.send_batch_alerts(all_arb, crafting, arb_limit=10, craft_limit=10)
        await ctx.send(
            f"✅ Scan complete: **{len(bm)}** BM, **{len(crafting)}** Crafting, **{len(arb)}** Arb opportunities found."
        )
    except Exception as e:
        await ctx.send(f"❌ Scan failed: {e}")


@bot.command()
async def bm(ctx):
    """Quick Black Market shortage report."""
    from sqlalchemy import desc

    from app.db.models import BlackMarketSnapshot

    with get_db_session() as db:
        snaps = (
            db.query(BlackMarketSnapshot)
            .order_by(desc(BlackMarketSnapshot.captured_at))
            .limit(5)
            .all()
        )

        if not snaps:
            await ctx.send("❌ No Black Market data available. Run collection first.")
            return

        embed = discord.Embed(title="💀 Black Market Shortages", color=discord.Color.dark_red())
        for s in snaps:
            bp = f"{int(s.buy_price_max):,}" if s.buy_price_max else "—"
            age = f"{int(s.data_age_seconds) // 60}m" if s.data_age_seconds is not None else "?"
            embed.add_field(
                name=f"{s.item_id} @{s.enchantment}",
                value=f"Buy Order: **{bp}**\nAge: {age}",
                inline=False,
            )
        await ctx.send(embed=embed)


@bot.command()
async def meta(ctx):
    """View top PvP meta items."""
    from sqlalchemy import desc

    from app.db.models import ItemMetaScore

    with get_db_session() as db:
        scores = db.query(ItemMetaScore).order_by(desc(ItemMetaScore.score)).limit(5).all()

        if not scores:
            await ctx.send("ℹ️ No meta scores calculated yet. Waiting for next scan.")
            return

        embed = discord.Embed(title="🔥 Top PvP Meta Items", color=discord.Color.red())
        for s in scores:
            embed.add_field(
                name=f"{s.item_id}", value=f"Meta Score: **{s.score:.2f}**", inline=False
            )
        await ctx.send(embed=embed)


@bot.command()
async def patch(ctx):
    """View latest patch intelligence."""
    from sqlalchemy import desc

    from app.db.models import PatchForecast

    with get_db_session() as db:
        forecasts = db.query(PatchForecast).order_by(desc(PatchForecast.created_at)).limit(3).all()

        if not forecasts:
            await ctx.send("ℹ️ No patch forecasts tracked yet.")
            return

        embed = discord.Embed(title="⚔️ Latest Patch Intelligence", color=discord.Color.orange())
        for f in forecasts:
            embed.add_field(
                name=f"{f.item_id}",
                value=f"Impact: **{f.expected_impact}**\nConfidence: **{f.confidence}**",
                inline=False,
            )
        await ctx.send(embed=embed)


@bot.command(name="caravan")
async def caravan_cmd(ctx, source: str, dest: str, weight: float = 1000.0):
    from app.arbitrage.caravan import optimize_caravan

    res = optimize_caravan(source.capitalize(), dest.capitalize(), weight)

    if not res["items"]:
        await ctx.send(
            f"⚠️ No profitable transport routes found from {source.capitalize()} to {dest.capitalize()}."
        )
        return

    embed = discord.Embed(
        title=f"🐪 Caravan: {source.capitalize()} ➔ {dest.capitalize()}",
        description=f"Capacity: {res['used_weight']}/{res['max_weight_capacity']}kg\nTotal Profit: **{int(res['total_expected_profit']):,}**\nInvestment: **{int(res['total_investment']):,}**",
        color=discord.Color.gold(),
    )

    for item in res["items"][:15]:
        embed.add_field(
            name=f"{item['quantity']}x {item['item_name']}",
            value=f"Profit: {int(item['total_profit']):,} ({int(item['profit_per_kg']):,}/kg) • Cost: {int(item['total_cost']):,}",
            inline=False,
        )
    if len(res["items"]) > 15:
        embed.set_footer(text=f"...and {len(res['items']) - 15} more items.")

    await ctx.send(embed=embed)


@bot.command(name="focus")
async def focus_cmd(ctx, max_focus: int = 10000, spec_level: int = 0):
    from app.crafting.focus import optimize_focus

    res = optimize_focus(max_focus, spec_level)

    if not res["items"]:
        await ctx.send("⚠️ No active crafting opportunities found to use focus on.")
        return

    embed = discord.Embed(
        title=f"✨ Focus Point Maximizer (Spec: {spec_level})",
        description=f"Focus Used: {int(res['focus_used'])}/{res['max_focus_allowance']}\nTotal Extra Profit: **{int(res['total_extra_profit_gained']):,}**",
        color=discord.Color.purple(),
    )

    for item in res["items"][:10]:
        embed.add_field(
            name=f"{item['quantity']}x {item['item_name']} ({item['crafting_city']} ➔ {item['sell_city']})",
            value=f"Extra Profit: {int(item['extra_profit']):,} • Focus Cost/Item: {int(item['focus_cost_per_item']):,}\nProfit/Focus: **{int(item['profit_per_focus']):,}**",
            inline=False,
        )

    await ctx.send(embed=embed)


async def start_discord_bot():
    if settings.discord_bot_token:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await bot.start(settings.discord_bot_token)
                break
            except discord.errors.HTTPException as e:
                if e.status == 429:
                    log.error(
                        f"Discord bot is being rate limited (429): {e}. Retrying in 5s... (Attempt {attempt + 1}/{max_retries})"
                    )
                    await asyncio.sleep(5.0)
                elif e.status == 503 or "no healthy upstream" in str(e):
                    log.error(
                        f"Discord service unavailable (503): {e}. Retrying in 5s... (Attempt {attempt + 1}/{max_retries})"
                    )
                    await asyncio.sleep(5.0)
                else:
                    log.error(f"Discord bot failed to start with HTTP error: {e}")
                    break
            except Exception as e:
                log.error(f"Discord bot failed to start: {e}")
                break


async def stop_discord_bot():
    if not bot.is_closed():
        await bot.close()
