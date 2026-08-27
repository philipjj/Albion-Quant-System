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
bot = commands.Bot(
    command_prefix=["!", "！"],
    intents=intents,
    help_command=None,
    case_insensitive=True,
)

SERVER_BADGES = {
    "west": "🇺🇸 [WEST]",
    "east": "🇸🇬 [ASIA]",
    "europe": "🇪🇺 [EUROPE]",
}


@bot.event
async def on_ready():
    from app.core import state

    log.info(f"Discord Bot AQS v3.2 logged in as {bot.user} (ID: {bot.user.id if bot.user else 'N/A'})")

    badge = SERVER_BADGES.get(settings.active_server.value, "[UNKNOWN]")
    tier_str = f"T{state.tier_lock}" if state.tier_lock else "ALL"

    # Send standby dashboard to the first available text channel
    for guild in bot.guilds:
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                embed = discord.Embed(
                    title="",
                    description=(
                        "# ALBION QUANT SYSTEM v3.2\n"
                        "-# ⏸️ STANDBY MODE"
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
                        "> `!purge` or `!purge all` — Clear channel alerts\n"
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


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Diagnostic check for Discord Developer Portal 'Message Content Intent'
    if not message.content and message.guild:
        log.warning(
            f"⚠️ [DISCORD INTENT WARNING] Received message from {message.author} in #{message.channel} "
            "with empty content. 'MESSAGE CONTENT INTENT' is likely DISABLED in Discord Developer Portal! "
            "Go to https://discord.com/developers/applications -> Your Bot -> Bot -> Privileged Gateway Intents -> Enable 'Message Content Intent'."
        )
    elif message.content.startswith(("!", "！")):
        log.info(f"📩 [DISCORD COMMAND] {message.author} executed: {message.content.strip()} in #{getattr(message.channel, 'name', 'DM')}")

    await bot.process_commands(message)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        log.debug(f"[DISCORD] Unknown command: {ctx.message.content}")
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"⚠️ Missing required argument: `{error.param.name}`. Type `!help` for usage.")
        return
    if isinstance(error, commands.BadArgument):
        await ctx.send(f"⚠️ Invalid argument provided: {error}. Type `!help` for usage.")
        return
    log.error(f"Unhandled Discord command error in !{getattr(ctx, 'command', 'unknown')}: {repr(error)}")
    await ctx.send(f"❌ Error executing `!{getattr(ctx, 'command', 'command')}`: {str(error)}")



def parse_silver_amount(val_str: str) -> int | None:
    if not val_str:
        return None
    val_str = val_str.strip().lower()
    if val_str in ("0", "off", "none", "reset", "disable", "disabled", "clear"):
        return 0
    import re
    m = re.match(r"^([0-9.]+)\s*([km])?$", val_str)
    if not m:
        return None
    num_part = float(m.group(1))
    suffix = m.group(2)
    if suffix == "k":
        return int(num_part * 1_000)
    elif suffix == "m":
        return int(num_part * 1_000_000)
    else:
        return int(num_part)


@bot.command()
async def help(ctx):
    """Custom help command for AQS manual controls."""
    embed = discord.Embed(
        title="📖  AQS Command Reference",
        description="Albion Quant System v3.2 — Quantitative Engine Controls",
        color=0x5865F2,  # Discord blurple
    )

    embed.add_field(
        name="🔧 SYSTEM CONTROLS",
        value=(
            "`!start` — Launch background scanning engine\n"
            "`!stop` — Pause background scanner\n"
            "`!status` — View system health & database dashboard\n"
            "`!server [west|east|europe]` — Switch server region\n"
            "`!schedule [time]` — Set poll interval (e.g. `!schedule 15m`)"
        ),
        inline=False,
    )
    embed.add_field(
        name="🎯 FILTERS & TOGGLES",
        value=(
            "`!toggle [channel|all|off]` — Turn alert feeds ON/OFF (e.g. `!toggle b-crafting`)\n"
            "`!premium [on|off]` — Toggle player tax mode (4.0% Premium vs 8.0% Non-Premium)\n"
            "`!enchanttransport [on|off]` — Toggle outer-city transport for enchanting\n"
            "`!tier [1-8|all]` — Filter items by Tier level (e.g. `!tier 7` or `!tier all`)\n"
            "`!maxinvest <amount|off>` — Set maximum budget cap (e.g. `!maxinvest 1m` or `off`)\n"
            "`!minrev <amount|off>` — Set minimum revenue floor (e.g. `!minrev 1.5m` or `off`)\n"
            "`!minbm <profit|off>` — Min profit for Black Market (e.g. `!minbm 50k` or `off`)\n"
            "`!mincraft <profit|off>` — Min profit for Crafting (e.g. `!mincraft 20k` or `off`)"
        ),
        inline=False,
    )
    embed.add_field(
        name="📊 MARKET DATA",
        value=(
            "`!price <item>` — Compare prices across all 8 market hubs (Royal + Caerleon + Brecilien + BM)\n"
            "`!scan [bm]` — Trigger immediate manual scan\n"
            "`!bm` — View top Black Market shortages\n"
            "`!meta` — View top PvP Meta item scores\n"
            "`!patch` — View patch forecast intelligence"
        ),
        inline=False,
    )
    embed.add_field(
        name="🚀 TOOLS & UTILITIES",
        value=(
            "`!caravan <src> <dst> [kg]` — Transport route profit optimizer\n"
            "`!focus [amount] [spec]` — Focus points profit optimizer\n"
            "`!localsourcing <on|off>` — Toggle single-city local craft sourcing\n"
            "`!purge [all|50|dates]` — Purge channel messages (`!purge`, `!purge all`, or `!purge 50`)"
        ),
        inline=False,
    )
    embed.set_footer(text="AQS v3.2 • Tip: You can use 50k, 500k, 1m, 1.5m, off for filters")
    await ctx.send(embed=embed)


@bot.command(name="price")
async def price_cmd(ctx, *, query: str):
    """Prices across all 8 market hubs for any item."""
    import re as _re

    query = query.strip()
    quality = 1
    enchant_override = None

    QUALITY_NAMES = {1: "Normal", 2: "Good", 3: "Outstanding", 4: "Excellent", 5: "Masterpiece"}
    ALL_MARKET_CITIES = [
        "Bridgewatch", "Martlock", "Lymhurst", "Fort Sterling", "Thetford",
        "Caerleon", "Brecilien", "Black Market"
    ]

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

    def fmt_k(n):
        if n is None or n <= 0: return "—"
        if n >= 1000000: return f"{n/1000000:.2f}M"
        if n >= 1000: return f"{n/1000:.1f}k".replace(".0k", "k")
        return f"{n:,.0f}"

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
        for city in ALL_MARKET_CITIES:
            row = (
                db.query(MarketPrice)
                .filter(
                    MarketPrice.item_id == item.item_id,
                    MarketPrice.city == city,
                    MarketPrice.quality == quality,
                    MarketPrice.server == settings.active_server.value,
                )
                .order_by(MarketPrice.captured_at.desc())
                .first()
            )
            city_rows[city] = row

        embed = discord.Embed(
            title=f"{item.name}",
            description=f"-# `{item.item_id}` · T{item.tier}.{item.enchant} · {QUALITY_NAMES.get(quality, 'Unknown')}",
            color=0x5865F2,
        )
        for city in ALL_MARKET_CITIES:
            row = city_rows[city]
            if row and (row.sell_price_min or row.buy_price_max):
                sell = fmt_k(row.sell_price_min)
                buy = fmt_k(row.buy_price_max)
                vol = row.volume_24h or 0
                age = fmt_age(row.data_age_seconds)
                embed.add_field(name=city, value=f"Buy: **{sell}**\nSell: **{buy}**\nVol: {vol} ({age})", inline=True)
            else:
                embed.add_field(name=city, value="No data", inline=True)
                
        embed.set_thumbnail(url=item_icon_url(item.item_id, quality=quality, size=64))
        embed.set_footer(
            text="Buy = cheapest sell order (what you pay) · Sell = highest buy order (instant sell)"
        )
        await ctx.send(embed=embed)


@bot.command()
async def purge(ctx, arg1: str = "all", arg2: str = ""):
    """
    Delete messages from the current channel.
    Usage:
      !purge             -> Purge all recent messages
      !purge all         -> Purge all recent messages
      !purge 50          -> Purge last 50 messages
      !purge 01/02 05/02 -> Purge messages in date range (DD/MM)
    """
    try:
        # Check permissions if in a guild
        if ctx.guild and not ctx.channel.permissions_for(ctx.guild.me).manage_messages:
            await ctx.send("❌ Bot requires `Manage Messages` permission to purge channel messages.")
            return

        arg1_clean = arg1.strip().lower()

        # Case 1: Numeric count (e.g. !purge 50)
        if arg1_clean.isdigit():
            count = min(int(arg1_clean), 1000)
            deleted = await ctx.channel.purge(limit=count + 1, bulk=True)
            del_count = max(0, len(deleted) - 1)
            await ctx.send(f"✅ Successfully deleted **{del_count}** messages.", delete_after=4)
            return

        # Case 2: Date range (e.g. !purge 01/02 05/02)
        if arg2.strip():
            start_str = arg1.strip()
            end_str = arg2.strip()
            cur_year = datetime.now(timezone.utc).year
            if len(start_str.split("/")) == 2:
                start_str += f"/{cur_year}"
            if len(end_str.split("/")) == 2:
                end_str += f"/{cur_year}"

            start_date = datetime.strptime(start_str, "%d/%m/%Y").replace(tzinfo=timezone.utc)
            end_date = datetime.strptime(end_str, "%d/%m/%Y").replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )

            if start_date > end_date:
                await ctx.send("❌ Start date must be before end date.")
                return

            await ctx.send(
                f"🧹 **Purging messages** from {start_str} to {end_str}..."
            )

            def check(m):
                return start_date <= m.created_at <= end_date

            deleted = await ctx.channel.purge(limit=1000, check=check, bulk=True)
            await ctx.send(
                f"✅ Successfully deleted **{len(deleted)}** messages from the specified range.",
                delete_after=4,
            )
            return

        # Case 3: !purge or !purge all
        if arg1_clean in ("all", "", "clear", "channel"):
            deleted = await ctx.channel.purge(limit=1000, bulk=True)
            await ctx.send(
                f"✅ Successfully purged **{len(deleted)}** messages from this channel.",
                delete_after=4,
            )
            return

        await ctx.send("❌ Usage: `!purge` (all), `!purge 50` (count), or `!purge DD/MM DD/MM` (date range).")

    except ValueError:
        await ctx.send("❌ Invalid date format. Please use **DD/MM/YYYY** or `!purge all`.")
    except Exception as e:
        await ctx.send(f"❌ Error during purge: {e}")


@bot.command(name="localsourcing")
async def localsourcing_cmd(ctx, toggle: str = ""):
    """Toggle strict local-only crafting ingredient sourcing (on/off)."""
    from app.core import state
    toggle = toggle.strip().lower()
    if toggle in ("on", "true", "1", "yes", "local"):
        state.crafting_local_sourcing_only = True
        await ctx.send("✅ **Crafting Sourcing locked to LOCAL ONLY** (materials must be available in craft city).")
    elif toggle in ("off", "false", "0", "no", "multi"):
        state.crafting_local_sourcing_only = False
        await ctx.send("⚠️ **Crafting Sourcing set to MULTI-CITY** (materials can be sourced from refining hubs).")
    else:
        current = "ON (Local Only)" if state.crafting_local_sourcing_only else "OFF (Multi-City)"
        await ctx.send(f"ℹ️ Current Crafting Sourcing mode: **{current}**\nUse `!localsourcing on` or `!localsourcing off` to toggle.")


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
            "# ALBION QUANT SYSTEM v3.2\n"
            "-# 🚀 LAUNCH SEQUENCE"
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
            "# ALBION QUANT SYSTEM v3.2\n"
            "-# ✅ ENGINE ONLINE"
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
            "# ALBION QUANT SYSTEM v3.2\n"
            "-# ⏸️ ENGINE PAUSED"
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


@bot.command(name="alerts")
async def alerts_cmd(ctx, action: str = ""):
    """Toggle or check Discord alert broadcasting (!alerts on / !alerts off / !alerts status)."""
    from app.core import state
    action = (action or "").strip().lower()

    if action in ("on", "enable", "enabled", "1", "true", "start"):
        state.discord_alerts_enabled = True
        embed = discord.Embed(
            title="🔔  DISCORD ALERTS ENABLED",
            description="Discord webhook alerts are now **ACTIVE** 🟢. Alert notifications will be broadcast across all configured channels.",
            color=0x57F287,
        )
        embed.set_footer(text="AQS v3.2 • Alerts Armed")
        embed.timestamp = datetime.now(timezone.utc)
        await ctx.send(embed=embed)
    elif action in ("off", "disable", "disabled", "0", "false", "stop", "mute", "muted"):
        state.discord_alerts_enabled = False
        embed = discord.Embed(
            title="🔕  DISCORD ALERTS MUTED",
            description="Discord webhook alerts are now **MUTED** 🔴. Scanners continue running in the background and updating Web UI/DB without sending Discord notifications.",
            color=0xED4245,
        )
        embed.set_footer(text="AQS v3.2 • Alerts Muted")
        embed.timestamp = datetime.now(timezone.utc)
        await ctx.send(embed=embed)
    else:
        status_str = "ENABLED 🟢" if getattr(state, "discord_alerts_enabled", True) else "MUTED 🔴"
        embed = discord.Embed(
            title="🔔  DISCORD ALERTS STATUS",
            description=f"Current Discord Alerts Broadcast Status: **{status_str}**\n\nUse `!alerts on` to enable or `!alerts off` to mute.",
            color=0x5865F2,
        )
        embed.set_footer(text="AQS v3.2 • Alerts Control")
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
async def minbm(ctx, *, val: str = None):
    """Set minimum profit for Black Market alerts."""
    from app.core import state
    if val is None:
        amt_str = f"**{state.min_bm_profit:,}** silver" if state.min_bm_profit > 0 else "**OFF (0)**"
        await ctx.send(f"ℹ️ Current **Black Market Minimum Profit**: {amt_str}\nUsage: `!minbm 50k` or `!minbm off`")
        return
    parsed = parse_silver_amount(val)
    if parsed is None or parsed < 0:
        await ctx.send("❌ Invalid amount. Examples: `!minbm 50k`, `!minbm 1m`, `!minbm off`.")
        return
    state.min_bm_profit = parsed
    if parsed == 0:
        await ctx.send("✅ **Black Market Minimum Profit** filter turned **OFF**.")
    else:
        await ctx.send(f"✅ **Black Market Minimum Profit** set to **{parsed:,}** silver.")


@bot.command()
async def mincraft(ctx, *, val: str = None):
    """Set minimum profit for Crafting alerts."""
    from app.core import state
    if val is None:
        amt_str = f"**{state.min_craft_profit:,}** silver" if state.min_craft_profit > 0 else "**OFF (0)**"
        await ctx.send(f"ℹ️ Current **Crafting Minimum Profit**: {amt_str}\nUsage: `!mincraft 20k` or `!mincraft off`")
        return
    parsed = parse_silver_amount(val)
    if parsed is None or parsed < 0:
        await ctx.send("❌ Invalid amount. Examples: `!mincraft 20k`, `!mincraft 500k`, `!mincraft off`.")
        return
    state.min_craft_profit = parsed
    if parsed == 0:
        await ctx.send("✅ **Crafting Minimum Profit** filter turned **OFF**.")
    else:
        await ctx.send(f"✅ **Crafting Minimum Profit** set to **{parsed:,}** silver.")


@bot.command()
async def maxinvest(ctx, *, val: str = None):
    """Set maximum investment limit."""
    from app.core.config import settings
    if val is None:
        amt_str = f"**{settings.max_investment_silver:,}** silver" if settings.max_investment_silver > 0 else "**OFF (No budget cap)**"
        await ctx.send(f"ℹ️ Current **Max Investment**: {amt_str}\nUsage: `!maxinvest 1m` or `!maxinvest off`")
        return
    parsed = parse_silver_amount(val)
    if parsed is None or parsed < 0:
        await ctx.send("❌ Invalid amount. Examples: `!maxinvest 1m`, `!maxinvest 500k`, `!maxinvest off`.")
        return
    settings.max_investment_silver = parsed
    if parsed == 0:
        await ctx.send("✅ **Max Investment Limit** turned **OFF** (No budget cap).")
    else:
        await ctx.send(f"✅ **Max Investment Limit** set to **{parsed:,}** silver.")


@bot.command()
async def minrev(ctx, *, val: str = None):
    """Set minimum revenue target."""
    from app.core.config import settings
    if val is None:
        amt_str = f"**{settings.min_revenue_silver:,}** silver" if settings.min_revenue_silver > 0 else "**OFF (No revenue floor)**"
        await ctx.send(f"ℹ️ Current **Min Revenue**: {amt_str}\nUsage: `!minrev 1.5m` or `!minrev off`")
        return
    parsed = parse_silver_amount(val)
    if parsed is None or parsed < 0:
        await ctx.send("❌ Invalid amount. Examples: `!minrev 1.5m`, `!minrev 100k`, `!minrev off`.")
        return
    settings.min_revenue_silver = parsed
    if parsed == 0:
        await ctx.send("✅ **Min Revenue Filter** turned **OFF** (No revenue floor).")
    else:
        await ctx.send(f"✅ **Min Revenue Filter** set to **{parsed:,}** silver.")


@bot.command()
async def enchanttransport(ctx, mode: str = None):
    """Toggle transport-based enchanting (e.g. Thetford -> Caerleon)."""
    from app.core import state
    if mode is None:
        status = "🟢 **ENABLED** (Outer city transport allowed)" if state.allow_enchant_transport else "🔴 **DISABLED** (Caerleon local buy & enchant ONLY)"
        await ctx.send(f"ℹ️ **Enchantment Transport Status**: {status}\nUsage: `!enchanttransport on` or `!enchanttransport off`.")
        return
    mode_clean = mode.strip().lower()
    if mode_clean in ("on", "true", "enable", "enabled", "1"):
        state.allow_enchant_transport = True
        await ctx.send("✅ **Enchantment Transport ENABLED**: Showing outer city base items (e.g. Thetford ➔ Caerleon ➔ BM).")
    elif mode_clean in ("off", "false", "disable", "disabled", "0"):
        state.allow_enchant_transport = False
        await ctx.send("✅ **Enchantment Transport DISABLED**: Showing ONLY Caerleon local buy & enchant (Caerleon ➔ BM).")
    else:
        await ctx.send("❌ Invalid option. Use `!enchanttransport on` or `!enchanttransport off`.")



@bot.command()
async def premium(ctx, status: str = None):
    """View or toggle player Premium status (4% Tax with Premium vs 8% Tax without Premium)."""
    from app.core.config import settings

    if status is None:
        mode = "👑 **PREMIUM (4.0% Market Sales Tax)**" if settings.is_premium else "🛡️ **NON-PREMIUM (8.0% Market Sales Tax)**"
        await ctx.send(f"ℹ️ Current Tax Setting: {mode}\nUsage: `!premium on` or `!premium off` to switch.")
        return

    clean = status.strip().lower()
    if clean in ("on", "true", "enable", "enabled", "1", "yes"):
        settings.is_premium = True
        await ctx.send("✅ Player tax mode set to **👑 PREMIUM (4.0% Market Sales Tax)**.")
    elif clean in ("off", "false", "disable", "disabled", "0", "no"):
        settings.is_premium = False
        await ctx.send("✅ Player tax mode set to **🛡️ NON-PREMIUM (8.0% Market Sales Tax)**.")
    else:
        await ctx.send("❌ Invalid status. Usage: `!premium on` or `!premium off`.")


@bot.command()
async def toggle(ctx, channel: str = None):
    """Toggle alert channels ON or OFF."""
    from app.core.config import settings
    
    mapping = {
        "arb": "enable_alerts_arb",
        "arbitrage": "enable_alerts_arb",
        "crafting": "enable_alerts_crafting",
        "craft": "enable_alerts_crafting",
        "enchanting": "enable_alerts_enchanting",
        "enchant": "enable_alerts_enchanting",
        "mm": "enable_alerts_mm",
        "marketmaking": "enable_alerts_mm",
        "refining": "enable_alerts_refining",
        "refine": "enable_alerts_refining",
        "island": "enable_alerts_island",
        "farming": "enable_alerts_island",
        "transmute": "enable_alerts_transmute",
        "transmutation": "enable_alerts_transmute",
        
        "b-arb": "enable_alerts_bm_arb",
        "b-arbitrage": "enable_alerts_bm_arb",
        "bm-arb": "enable_alerts_bm_arb",
        "b-crafting": "enable_alerts_bm_crafting",
        "b-craft": "enable_alerts_bm_crafting",
        "bm-crafting": "enable_alerts_bm_crafting",
        "b-enchanting": "enable_alerts_bm_enchanting",
        "b-enchant": "enable_alerts_bm_enchanting",
        "bm-enchanting": "enable_alerts_bm_enchanting",
        "b-mm": "enable_alerts_bm_mm",
        "bm-mm": "enable_alerts_bm_mm",
        "b-refining": "enable_alerts_bm_refining",
        "b-refine": "enable_alerts_bm_refining",
        "bm-refining": "enable_alerts_bm_refining",
        "b-transmute": "enable_alerts_bm_transmute",
        "bm-transmute": "enable_alerts_bm_transmute",
    }
    
    display_names = {
        "arb": "Royal Arbitrage",
        "crafting": "Royal Crafting",
        "enchanting": "Royal Enchanting",
        "mm": "Royal Market Making",
        "refining": "Royal Refining",
        "island": "Island Agriculture & Farming",
        "transmute": "Royal Transmutation",
        "b-arb": "Black Market Arbitrage",
        "b-crafting": "Black Market Crafting",
        "b-enchanting": "Black Market Enchanting",
        "b-mm": "Black Market MM",
        "b-refining": "Caerleon Refining Transport",
        "b-transmute": "Black Market Transmutation",
    }
    
    if not channel:
        lines = ["# 🔔 ALERT FEED TOGGLES (12 Channels)"]
        for key, name in display_names.items():
            attr = mapping[key]
            status = getattr(settings, attr)
            badge = "🟢 **ON**" if status else "🔴 **OFF**"
            lines.append(f"> `{key.ljust(12)}` — {name}: {badge}")
        lines.append("\n*Usage: `!toggle b-crafting` to switch a channel ON/OFF.*")
        await ctx.send("\n".join(lines))
        return
        
    channel_clean = channel.lower().strip()
    
    if channel_clean in ("all", "reset", "on"):
        for attr in set(mapping.values()):
            setattr(settings, attr, True)
        await ctx.send("✅ **All 12 alert channels are now turned ON.**")
        return
        
    if channel_clean in ("off", "none", "clear"):
        for attr in set(mapping.values()):
            setattr(settings, attr, False)
        await ctx.send("🛑 **All 12 alert channels are now turned OFF.**")
        return

    if channel_clean not in mapping:
        await ctx.send(f"❌ Unknown channel `{channel}`. Valid channels:\n`arb`, `crafting`, `enchanting`, `mm`, `refining`, `island`, `transmute`, `b-arb`, `b-crafting`, `b-enchanting`, `b-mm`, `b-refining`")
        return
        
    attr = mapping[channel_clean]
    new_val = not getattr(settings, attr)
    setattr(settings, attr, new_val)
    status_str = "🟢 **ON**" if new_val else "🔴 **OFF**"
    await ctx.send(f"✅ Alert channel `{channel_clean}` is now {status_str}.")


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
        scan_res = await scanner.scan_all(scan_bm=scan_bm)
        if len(scan_res) >= 13:
            bm_arb, crafting, arb, refining, mm, enchant, quality, transmute, island, bm_craft, bm_refine, bm_enchant, bm_mm = scan_res[:13]
        elif len(scan_res) >= 9:
            bm_arb, crafting, arb, refining, mm, enchant, quality, transmute, island = scan_res[:9]
            bm_craft, bm_refine, bm_enchant, bm_mm = [], [], [], []
        else:
            bm_arb, crafting, arb, refining, mm, enchant, quality, transmute = scan_res[:8]
            island, bm_craft, bm_refine, bm_enchant, bm_mm = [], [], [], [], []

        await alerter.send_batch_alerts(
            arb_opps=arb,
            arb_limit=10,
            craft_opps=crafting,
            craft_limit=10,
            refine_opps=refining,
            refine_limit=10,
            enchant_opps=enchant,
            enchant_limit=10,
            mm_opps=mm,
            mm_limit=10,
            transmute_opps=transmute,
            transmute_limit=10,
            island_opps=island,
            island_limit=10,
            bm_arb_opps=bm_arb,
            bm_arb_limit=10,
            bm_craft_opps=bm_craft,
            bm_craft_limit=10,
            bm_refine_opps=bm_refine,
            bm_refine_limit=10,
            bm_enchant_opps=bm_enchant,
            bm_enchant_limit=10,
            bm_mm_opps=bm_mm,
            bm_mm_limit=10,
            quality_opps=quality,
            quality_limit=10,
        )
        await ctx.send(
            f"✅ **12-Channel Scan Complete**:\n"
            f"• 🏛️ **Royal Channels**: Transmute ({len(transmute)}), Island ({len(island)}), Crafting ({len(crafting)}), Refining ({len(refining)}), Enchanting ({len(enchant)}), Arbitrage ({len(arb)}), MM ({len(mm)})\n"
            f"• 💀 **Caerleon & Black Market**: B-Arb ({len(bm_arb)}), B-Crafting ({len(bm_craft)}), B-Refining ({len(bm_refine)}), B-Enchanting ({len(bm_enchant)}), B-MM ({len(bm_mm)})"
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
async def caravan_cmd(ctx, source: str, dest: str, weight: int = 1000):
    """Transport route profit optimizer using greedy knapsack packing."""
    from app.arbitrage.caravan import optimize_caravan

    def norm_city(c: str) -> str:
        c_clean = c.strip()
        if c_clean.lower() in ("bm", "blackmarket", "black_market"):
            return "Black Market"
        return c_clean.title()

    src_city = norm_city(source)
    dst_city = norm_city(dest)
    res = optimize_caravan(src_city, dst_city, weight)

    if not res["items"]:
        await ctx.send(
            f"⚠️ No profitable transport routes found from {src_city} to {dst_city}."
        )
        return

    embed = discord.Embed(
        title=f"🐪 Caravan: {src_city} ➔ {dst_city}",
        description=f"Capacity: {res['used_weight']}/{res['max_weight_capacity']}kg\nTotal Profit: **{int(res['total_expected_profit']):,}**\nInvestment: **{int(res['total_investment']):,}**",
        color=discord.Color.gold(),
    )

    desc_lines = []
    for item in res["items"][:15]:
        def fmt_k(n):
            if n is None or n <= 0: return "0"
            if n >= 1000000: return f"{n/1000000:.2f}M"
            if n >= 1000: return f"{n/1000:.1f}k".replace(".0k", "k")
            return f"{n:,.0f}"
            
        desc_lines.append(f"- **{item['quantity']}x {item['item_name']}** — Profit: **{fmt_k(item['total_profit'])}** (*{fmt_k(item['profit_per_kg'])}/kg*)")
        
    embed.add_field(name="Pack List", value="\n".join(desc_lines), inline=False)
    
    if len(res["items"]) > 15:
        embed.set_footer(text=f"...and {len(res['items']) - 15} more items.")

    await ctx.send(embed=embed)


@bot.command(name="focus")
async def focus_cmd(ctx, max_focus: int = 10000, spec_level: int = 0):
    """Focus Point Maximizer — ranks active crafting opportunities by Silver-per-Focus."""
    from sqlalchemy import desc
    from app.db.models import CraftingOpportunity

    with get_db_session() as db:
        opps = (
            db.query(CraftingOpportunity)
            .filter(
                CraftingOpportunity.is_active == True,
                CraftingOpportunity.profit > 0,
            )
            .order_by(desc(CraftingOpportunity.profit_per_focus), desc(CraftingOpportunity.profit))
            .limit(20)
            .all()
        )

    if not opps:
        await ctx.send("⚠️ No active crafting opportunities found to calculate focus efficiency on.")
        return

    # Focus efficiency calculation with mastery/specialization scaling
    spec_efficiency_mult = 0.5 ** (spec_level / 100.0) if spec_level > 0 else 1.0

    items_packed = []
    focus_remaining = float(max_focus)
    total_extra_profit = 0.0

    for o in opps:
        base_focus = o.focus_cost if o.focus_cost and o.focus_cost > 0 else 250.0
        effective_focus = max(10.0, base_focus * spec_efficiency_mult)

        spf = o.profit_per_focus if o.profit_per_focus and o.profit_per_focus > 0 else (o.profit / effective_focus)

        if focus_remaining < effective_focus:
            continue

        max_units = int(focus_remaining // effective_focus)
        safe_qty = min(max_units, o.safe_limit if o.safe_limit and o.safe_limit > 0 else 10)

        if safe_qty > 0:
            used = safe_qty * effective_focus
            extra = safe_qty * o.profit
            focus_remaining -= used
            total_extra_profit += extra
            items_packed.append({
                "item_name": o.item_name or o.item_id,
                "quantity": safe_qty,
                "crafting_city": o.crafting_city,
                "sell_city": o.sell_city or o.crafting_city,
                "extra_profit": extra,
                "focus_cost_per_item": effective_focus,
                "profit_per_focus": spf,
            })

    if not items_packed:
        await ctx.send(f"⚠️ Focus allowance ({max_focus:,}) too low to craft any active item.")
        return

    embed = discord.Embed(
        title=f"✨ Focus Point Maximizer (Spec: {spec_level})",
        description=f"Focus Used: **{int(max_focus - focus_remaining):,}/{max_focus:,}**\nTotal Expected Profit: **{int(total_extra_profit):,}** silver",
        color=discord.Color.purple(),
    )

    for item in items_packed[:10]:
        embed.add_field(
            name=f"{item['quantity']}x {item['item_name']} ({item['crafting_city']} ➔ {item['sell_city']})",
            value=f"Profit: **{int(item['extra_profit']):,}** • Focus/Item: **{int(item['focus_cost_per_item']):,}**\nSilver/Focus: **{int(item['profit_per_focus']):,}**",
            inline=False,
        )

    await ctx.send(embed=embed)


async def start_discord_bot():
    if not settings.discord_bot_token:
        return

    max_retries = 10
    for attempt in range(max_retries):
        try:
            if bot.is_closed():
                # Bot session was closed, re-initialize if needed
                pass
            await bot.start(settings.discord_bot_token)
            break
        except (discord.errors.LoginFailure, discord.errors.PrivilegedIntentsRequired) as e:
            log.error(f"[DISCORD BOT] Authentication/Intents fatal error: {e}. Please check DISCORD_BOT_TOKEN.")
            break
        except discord.errors.HTTPException as e:
            if e.status == 429:
                wait_sec = 10.0
                log.warning(
                    f"[DISCORD BOT] Rate limited (429): {e}. Retrying in {wait_sec}s... (Attempt {attempt + 1}/{max_retries})"
                )
                await asyncio.sleep(wait_sec)
            elif e.status in (500, 502, 503, 504) or "no healthy upstream" in str(e).lower():
                wait_sec = min(30.0, 5.0 * (attempt + 1))
                log.warning(
                    f"[DISCORD BOT] Discord gateway temporary error ({e.status}): {e}. Retrying in {wait_sec}s... (Attempt {attempt + 1}/{max_retries})"
                )
                await asyncio.sleep(wait_sec)
            else:
                log.warning(f"[DISCORD BOT] HTTP error: {e}. Retrying in 5s... (Attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(5.0)
        except asyncio.CancelledError:
            log.info("[DISCORD BOT] Task cancelled during shutdown.")
            break
        except Exception as e:
            wait_sec = min(30.0, 5.0 * (attempt + 1))
            err_msg = str(e) if str(e).strip() else repr(e)
            log.warning(
                f"[DISCORD BOT] Connection error ({err_msg}). Reconnecting in {wait_sec}s... (Attempt {attempt + 1}/{max_retries})"
            )
            try:
                if not bot.is_closed():
                    await bot.close()
            except Exception:
                pass
            await asyncio.sleep(wait_sec)


async def stop_discord_bot():
    try:
        if not bot.is_closed():
            await bot.close()
    except (asyncio.CancelledError, Exception):
        pass
