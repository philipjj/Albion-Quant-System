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
    log.info(f"Discord Bot AQS v3.0 logged in as {bot.user}")

@bot.command()
async def help(ctx):
    """Custom help command for AQS v3.0 manual controls."""
    embed = discord.Embed(title="📖 AQS v3.0 Manual Controls", color=discord.Color.green())
    embed.add_field(name="`!status`", value="Check system health, active server, and scheduler state.", inline=False)
    embed.add_field(name="`!server [name]`", value="Switch between `europe`, `west`, or `east`.", inline=False)
    embed.add_field(name="`!schedule [time]`", value="Set poll interval (e.g., `!schedule 1h 30m`).", inline=False)
    embed.add_field(name="`!start` / `!stop`", value="Start or pause background collection tasks.", inline=False)
    embed.add_field(name="`!scan`", value="Trigger an immediate manual scan (Top 5 + Consumables/Materials).", inline=False)
    embed.add_field(name="`!purge [start] [end]`", value="Delete messages in a date range (DD/MM/YYYY).", inline=False)
    embed.add_field(name="`!bm`", value="Quick Black Market shortage report.", inline=False)
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
        end_date = datetime.strptime(end_str, "%d/%m/%Y").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
        
        if start_date > end_date:
            await ctx.send("❌ Start date must be before end date.")
            return

        await ctx.send(f"🧹 **Purging messages** from {start_str} to {end_str}... this may take a while.")
        
        def check(m):
            return start_date <= m.created_at <= end_date

        deleted = await ctx.channel.purge(limit=1000, check=check, bulk=True)
        await ctx.send(f"✅ Successfully deleted **{len(deleted)}** messages from the specified range.", delete_after=5)
        
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
        arb_count = db.query(func.count(ArbitrageOpportunity.id)).filter(ArbitrageOpportunity.is_active == True).scalar()
        craft_count = db.query(func.count(CraftingOpportunity.id)).filter(CraftingOpportunity.is_active == True).scalar()
        
    badge = SERVER_BADGES.get(settings.active_server.value, "[UNKNOWN]")
    scheduler_status = "🟢 ACTIVE" if state.scheduler_instance and state.scheduler_instance._is_running else "🔴 PAUSED"
    interval = settings.market_poll_interval
    
    embed = discord.Embed(title="📊 AQS v3.0 System Status", color=discord.Color.blue())
    embed.add_field(name="Active Server", value=f"**{badge}**", inline=True)
    embed.add_field(name="Scheduler", value=scheduler_status, inline=True)
    embed.add_field(name="Interval", value=f"**{interval} min**", inline=True)
    
    embed.add_field(name="Market Data", value=f"Price Records: **{price_count:,}**", inline=False)
    embed.add_field(name="Active Opps", value=f"Arbitrage: **{arb_count}** | Crafting: **{craft_count}**", inline=False)
    
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
    """Start the background collector/scanner."""
    from app.core import state
    if not state.scheduler_instance:
        await ctx.send("❌ Scheduler not available.")
        return
    
    state.scheduler_instance.start()
    await ctx.send("🟢 **AQS Scheduler Started**. Background tasks are now running.")

@bot.command()
async def stop(ctx):
    """Pause the background collector/scanner."""
    from app.core import state
    if not state.scheduler_instance:
        await ctx.send("❌ Scheduler not available.")
        return
    
    state.scheduler_instance.stop()
    await ctx.send("🔴 **AQS Scheduler Paused**. No more background data will be collected.")

@bot.command()
async def scan(ctx):
    """Trigger a manual arbitrage and crafting scan."""
    await ctx.send(f"🚀 Starting manual scan for **{settings.active_server.value.upper()}** (Top 5 + Specialty)...")
    from app.alerts.discord import DiscordAlerter
    from app.arbitrage.scanner import ArbitrageScanner
    from app.crafting.engine import CraftingEngine
    
    alerter = DiscordAlerter()
    
    # 1. Arbitrage
    scanner = ArbitrageScanner()
    arb_opps = await scanner.scan()
    scanner.store_opportunities()
    
    # 2. Crafting
    engine = CraftingEngine()
    craft_opps = await engine.scan()
    engine.store_opportunities()
    
    # 3. Filtering for Consumables / Materials
    consumable_ids = []
    resource_ids = []
    with get_db_session() as db:
        cons = db.query(Item.item_id).filter(Item.category == 'consumables').all()
        consumable_ids = [c[0] for c in cons]
        res = db.query(Item.item_id).filter(Item.category.in_(['gathering', 'crafting'])).all()
        resource_ids = [r[0] for r in res]
        
    special_arb = [o for o in arb_opps if o['item_id'] in consumable_ids or o['item_id'] in resource_ids][:3]
    special_craft = [o for o in craft_opps if o['item_id'] in consumable_ids or o['item_id'] in resource_ids][:3]

    # 4. Alert Top 5 of each + Specials
    await alerter.send_batch_alerts(arb_opps, craft_opps, arb_limit=5, craft_limit=5)
    
    if special_arb or special_craft:
        await ctx.send("📦 **Specialty Categories (Consumables/Materials) found:**")
        await alerter.send_batch_alerts(special_arb, special_craft, arb_limit=3, craft_limit=3)
    
    await ctx.send(f"✅ Scan complete. Results sent to alerts channel.")

@bot.command()
async def bm(ctx):
    """Quick Black Market shortage report."""
    from sqlalchemy import desc

    from app.db.models import BlackMarketSnapshot
    
    with get_db_session() as db:
        snaps = db.query(BlackMarketSnapshot).order_by(desc(BlackMarketSnapshot.captured_at)).limit(5).all()
        
    if not snaps:
        await ctx.send("❌ No Black Market data available. Run collection first.")
        return
        
    embed = discord.Embed(title="💀 Black Market Shortages", color=discord.Color.dark_red())
    for s in snaps:
        embed.add_field(
            name=f"{s.item_id} @{s.enchantment}",
            value=f"Buy Order: **{s.buy_price_max:,}**\nAge: {s.data_age_seconds // 60 if s.data_age_seconds else '?' }m",
            inline=False
        )
    await ctx.send(embed=embed)

async def start_discord_bot():
    if settings.discord_bot_token:
        await bot.start(settings.discord_bot_token)

async def stop_discord_bot():
    if not bot.is_closed():
        await bot.close()
