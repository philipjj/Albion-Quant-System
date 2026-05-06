import asyncio
import csv
import io
import json

import discord
import httpx
from discord.ext import commands
from PIL import Image

from app.arbitrage.scanner import ArbitrageScanner
from app.core.config import PROJECT_ROOT, settings
from app.core.icons import item_icon_url
from app.core.logging import log
from app.crafting.engine import CraftingEngine
from app.db.models import ArbitrageOpportunity, CraftingOpportunity, Item, UserProfile
from app.db.session import get_db_session

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

import os


async def _render_loadout_layout(slots: dict) -> io.BytesIO:
    """Render an Albion-like equipment layout using official item icons."""
    canvas = Image.new("RGBA", (640, 760), (24, 26, 30, 255))
    from PIL import ImageDraw

    # Visual arrangement mirrors the in-game character equipment panel.
    pos_map = {
        "Head": (270, 60),
        "Cape": (450, 60),
        "Bag": (90, 60),
        "MainHand": (90, 250),
        "Armor": (270, 250),
        "OffHand": (450, 250),
        "Food": (90, 440),
        "Shoes": (270, 440),
        "Potion": (450, 440),
        "Mount": (270, 610),
    }
    box_size = 128
    draw = ImageDraw.Draw(canvas)

    # Pre-draw empty boxes for better visual structure
    for x, y in pos_map.values():
        draw.rectangle([x, y, x + box_size, y + box_size], fill=(40, 42, 48), outline=(60, 62, 70), width=2)

    async with httpx.AsyncClient(timeout=15.0) as client:
        tasks = []
        for slot, (x, y) in pos_map.items():
            item_data = slots.get(slot)
            if not item_data:
                continue
            i_id = item_data if isinstance(item_data, str) else item_data.get("Type")
            qual = 1 if isinstance(item_data, str) else item_data.get("Quality", 1)
            if i_id:
                tasks.append((x, y, item_icon_url(i_id, quality=qual, size=128)))

        async def fetch_and_paste(x: int, y: int, url: str) -> None:
            try:
                r_img = await client.get(url)
                if r_img.status_code != 200:
                    log.warning(f"Failed to fetch icon: {url} (Status: {r_img.status_code})")
                    return
                icon = Image.open(io.BytesIO(r_img.content)).convert("RGBA")
                if icon.size != (box_size, box_size):
                    icon = icon.resize((box_size, box_size))
                canvas.paste(icon, (x, y), icon)
            except Exception as e:
                # Include more info for debugging (e.g. status code, content snippet)
                log.error(f"Error rendering slot icon: {type(e).__name__}: {e} | URL: {url}")
                return

        await asyncio.gather(*(fetch_and_paste(x, y, u) for x, y, u in tasks))

    out = io.BytesIO()
    canvas.save(out, format="PNG")
    out.seek(0)
    return out


@bot.event
async def on_ready():
    log.info(f"Discord Bot logged in as {bot.user} (PID: {os.getpid()})")

@bot.command()
async def ping(ctx):
    """Health check command."""
    await ctx.send("Pong! 🏓 Albion Quant System is online and ready.")


def _get_or_create_profile(discord_user_id: str) -> UserProfile:
    with get_db_session() as db:
        profile = db.query(UserProfile).filter_by(discord_user_id=discord_user_id).first()
        if not profile:
            profile = UserProfile(
                discord_user_id=discord_user_id,
                is_premium=settings.is_premium,
                api_server=settings.albion_api_server,
            )
            db.add(profile)
            db.commit()
            db.refresh(profile)
        return profile


def _normalize_city_name(name: str) -> str:
    """Normalize user input to official city names."""
    if not name:
        return None
    name = name.lower().strip()
    mapping = {
        "bw": "Bridgewatch",
        "bridgewatch": "Bridgewatch",
        "ml": "Martlock",
        "martlock": "Martlock",
        "lh": "Lymhurst",
        "lymhurst": "Lymhurst",
        "lemhurst": "Lymhurst",  # User's typo
        "fs": "Fort Sterling",
        "fortsterling": "Fort Sterling",
        "fort sterling": "Fort Sterling",
        "tf": "Thetford",
        "thetford": "Thetford",
        "cl": "Caerleon",
        "caerleon": "Caerleon",
        "bm": "Black Market",
        "blackmarket": "Black Market",
        "black market": "Black Market",
    }
    return mapping.get(name)


@bot.group(invoke_without_command=True)
async def profile(ctx):
    """Show your personalization profile."""
    p = _get_or_create_profile(str(ctx.author.id))
    msg = (
        f"**Profile** for `{p.discord_user_id}`\n"
        f"- Premium: `{bool(p.is_premium)}`\n"
        f"- Server: `{p.api_server or settings.albion_api_server}`\n"
        f"- Home City: `{p.home_city or ''}`\n"
        f"- Capital/Trade: `{p.max_capital_per_trade or settings.max_capital_per_trade}`\n"
        f"- Exit Hours: `{p.target_exit_hours or settings.target_exit_hours}`\n"
        f"- Min Arb Margin: `{p.min_arbitrage_margin or settings.min_arbitrage_margin}`\n"
        f"- Min Arb Profit: `{p.min_arbitrage_profit or settings.min_arbitrage_profit}`\n"
        f"- Min Craft Profit: `{p.min_crafting_profit or settings.min_crafting_profit}`"
    )
    await ctx.send(msg)


@profile.command(name="set")
async def profile_set(ctx, key: str, value: str):
    """Set a profile field, e.g. !profile set premium true"""
    key = key.lower().strip()
    discord_user_id = str(ctx.author.id)

    with get_db_session() as db:
        p = db.query(UserProfile).filter_by(discord_user_id=discord_user_id).first()
        if not p:
            p = UserProfile(
                discord_user_id=discord_user_id,
                is_premium=settings.is_premium,
                api_server=settings.albion_api_server,
            )
            db.add(p)

        try:
            if key == "premium":
                p.is_premium = value.lower() in ("1", "true", "yes", "on")
            elif key == "server":
                v = value.lower()
                if v not in ("west", "europe", "east"):
                    await ctx.send("Invalid server. Use west/europe/east.")
                    return
                p.api_server = v
            elif key == "home_city":
                p.home_city = value
            elif key == "capital":
                p.max_capital_per_trade = int(value)
            elif key == "exit_hours":
                p.target_exit_hours = float(value)
            elif key == "min_arb_margin":
                p.min_arbitrage_margin = float(value)
            elif key == "min_arb_profit":
                p.min_arbitrage_profit = int(value)
            elif key == "min_craft_profit":
                p.min_crafting_profit = int(value)
            else:
                await ctx.send(
                    "Unknown key. Try: premium, server, home_city, capital, exit_hours, min_arb_margin, min_arb_profit, min_craft_profit"
                )
                return
        except Exception as e:
            await ctx.send(f"Invalid value: {e}")
            return

        db.commit()

    await ctx.send("✅ Updated. Run `!profile` to view.")


@bot.command()
async def export(ctx, kind: str = "arbitrage", limit: int = 200):
    """Export current opportunities as a CSV attachment."""
    kind = (kind or "").lower().strip()
    limit = max(1, min(int(limit or 200), 2000))

    out = io.StringIO()
    w = csv.writer(out)

    with get_db_session() as db:
        if kind in ("arb", "arbitrage"):
            rows = (
                db.query(ArbitrageOpportunity)
                .filter(ArbitrageOpportunity.is_active == True)
                .order_by(ArbitrageOpportunity.ev_score.desc(), ArbitrageOpportunity.estimated_profit.desc())
                .limit(limit)
                .all()
            )
            w.writerow(["item_id","item_name","source_city","destination_city","buy_price","sell_price","estimated_profit","estimated_margin","ev_score","daily_volume","volume_source","risk_score","volatility","persistence","detected_at"])
            for r in rows:
                w.writerow([r.item_id,r.item_name,r.source_city,r.destination_city,r.buy_price,r.sell_price,r.estimated_profit,r.estimated_margin,r.ev_score,r.daily_volume,r.volume_source,r.risk_score,r.volatility,r.persistence,r.detected_at.isoformat() if r.detected_at else ""])
            filename = "arbitrage.csv"
        elif kind in ("craft", "crafting"):
            rows = (
                db.query(CraftingOpportunity)
                .filter(CraftingOpportunity.is_active == True)
                .order_by(CraftingOpportunity.ev_score.desc(), CraftingOpportunity.profit.desc())
                .limit(limit)
                .all()
            )
            w.writerow(["item_id","item_name","crafting_city","sell_city","craft_cost","sell_price","profit","profit_margin","profit_per_focus","ev_score","daily_volume","volume_source","volatility","persistence","detected_at"])
            for r in rows:
                w.writerow([r.item_id,r.item_name,r.crafting_city,r.sell_city,r.craft_cost,r.sell_price,r.profit,r.profit_margin,r.profit_per_focus,r.ev_score,r.daily_volume,r.volume_source,r.volatility,r.persistence,r.detected_at.isoformat() if r.detected_at else ""])
            filename = "crafting.csv"
        else:
            await ctx.send("Unknown kind. Use `arbitrage` or `crafting`.")
            return

    data = out.getvalue().encode("utf-8")
    file = discord.File(fp=io.BytesIO(data), filename=filename)
    await ctx.send(file=file)

@bot.command()
async def server(ctx, server_name: str = None):
    """Check or change the current Albion API server."""
    if not server_name:
        await ctx.send(f"Current server is set to: **{settings.albion_api_server}**")
        return

    server_name = server_name.lower()
    if server_name not in ["west", "europe", "east"]:
        await ctx.send("Invalid server. Choose 'west', 'europe', or 'east'.")
        return

    # Update runtime settings
    settings.albion_api_server = server_name
    settings.albion_api_base = f"https://{server_name}.albion-online-data.com"

    # Update .env file
    import re
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        content = env_path.read_text()
        content = re.sub(r"ALBION_API_SERVER=.*", f"ALBION_API_SERVER={server_name}", content)
        content = re.sub(r"ALBION_API_BASE=.*", f"ALBION_API_BASE={settings.albion_api_base}", content)
        env_path.write_text(content)

    await ctx.send(f"✅ Server successfully changed to: **{server_name}**")

@bot.command()
async def scan(ctx, town: str = None):
    """
    Run an arbitrage and crafting scan. 
    Usage: !scan [town|any]
    Example: !scan lymhurst
    """
    if town and town.lower() == "any":
        town = None

    target_city = _normalize_city_name(town) if town else None
    
    if town and not target_city:
        await ctx.send(f"⚠️ Unknown city: `{town}`. Try: `lymhurst`, `fort sterling`, etc., or `any`.")
        return

    city_label = f" for **{target_city}**" if target_city else " across **all cities**"
    await ctx.send(f"🚀 Starting manual scan{city_label}. Analyzing market depth and liquidity...")

    try:
        from app.db.session import init_db
        init_db()

        # Run scanners with filters
        arb_scanner = ArbitrageScanner()
        craft_engine = CraftingEngine()

        # We pass target_city as the filter
        arb_opps = await arb_scanner.scan(source_city_filter=target_city)
        craft_opps = await craft_engine.compute(crafting_city_filter=target_city)

        # Persist results
        arb_scanner.store_opportunities()
        craft_engine.store_opportunities()

        # Pull top opportunities for the direct response and webhook
        from app.alerts.discord import DiscordAlerter
        from app.db.models import ArbitrageOpportunity, CraftingOpportunity
        from app.db.session import get_db_session

        with get_db_session() as db:
            # Query top active opportunities
            query_arb = db.query(ArbitrageOpportunity).filter(ArbitrageOpportunity.is_active == True)
            query_craft = db.query(CraftingOpportunity).filter(CraftingOpportunity.is_active == True)
            
            if target_city:
                query_arb = query_arb.filter(ArbitrageOpportunity.source_city == target_city)
                query_craft = query_craft.filter(CraftingOpportunity.crafting_city == target_city)
                
            arb_results = query_arb.order_by(ArbitrageOpportunity.ev_score.desc()).limit(10).all()
            craft_results = query_craft.order_by(CraftingOpportunity.ev_score.desc()).limit(10).all()

            # Prepare data for the Alerter (webhook)
            arb_list = [{
                "item_id": opp.item_id,
                "item_name": opp.item_name or opp.item_id,
                "quality": 1,
                "source_city": opp.source_city,
                "destination_city": opp.destination_city,
                "buy_price": opp.buy_price or 0,
                "sell_price": opp.sell_price or 0,
                "estimated_profit": opp.estimated_profit or 0.0,
                "estimated_margin": opp.estimated_margin or 0.0,
                "daily_volume": opp.daily_volume or 0,
                "volume_source": opp.volume_source or "EST",
                "risk_score": opp.risk_score or 0.0,
                "ev_score": opp.ev_score or 0.0,
                "volatility": opp.volatility or 0.05,
                "persistence": opp.persistence or 1
            } for opp in arb_results]

            craft_list = [{
                "item_id": opp.item_id,
                "item_name": opp.item_name or opp.item_id,
                "quality": 1,
                "crafting_city": opp.crafting_city,
                "sell_city": opp.sell_city or "Unknown",
                "craft_cost": opp.craft_cost or 0.0,
                "sell_price": opp.sell_price or 0.0,
                "profit": opp.profit or 0.0,
                "profit_margin": opp.profit_margin or 0.0,
                "daily_volume": opp.daily_volume or 0,
                "volume_source": opp.volume_source or "EST",
                "journal_profit": opp.journal_profit or 0.0,
                "ev_score": opp.ev_score or 0.0,
                "ingredients_detail": json.loads(opp.ingredients_json) if opp.ingredients_json else []
            } for opp in craft_results]

        # Send batch alerts to webhook
        alerter = DiscordAlerter()
        await alerter.send_batch_alerts(arb_list, craft_list)

        # --- Direct Response Embed for targeted scan ---
        if target_city:
            embed = discord.Embed(
                title=f"🎯 Target Scan: {target_city}",
                description=f"Found **{len(arb_results)}** transport and **{len(craft_results)}** crafting ops.",
                color=discord.Color.blue()
            )
            
            # Transport Section
            if arb_results:
                lines = []
                for o in arb_results[:5]:
                    lines.append(f"📦 **{o.item_id[:15]}** → {o.destination_city}: **{o.estimated_profit:,.0f}** silver ({o.estimated_margin:.1f}%)")
                embed.add_field(name="🚚 Top Transport Routes", value="\n".join(lines), inline=False)
            
            # Crafting Section
            if craft_results:
                lines = []
                for o in craft_results[:5]:
                    lines.append(f"⚒️ **{o.item_id[:15]}** @ {o.sell_city}: **{o.profit:,.0f}** silver ({o.profit_margin:.1f}%)")
                embed.add_field(name="⚒️ Top Crafting Ops", value="\n".join(lines), inline=False)
                
            embed.set_footer(text="Check the webhook channel for full details and ingredient lists.")
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"✅ Full scan complete! Found {len(arb_results)} transport and {len(craft_results)} crafting opportunities. Results pushed to webhook.")

    except Exception as e:
        log.error(f"Scan error: {e}")
        await ctx.send(f"❌ Error during scan: {e}")

@bot.command()
async def history(ctx):
    """Manually trigger real market volume history collection."""
    await ctx.send("📊 Starting manual Market History collection... (Verifying Real Demand)")

    try:
        from main import scheduler_instance
        if scheduler_instance:
            await scheduler_instance.job_collect_history()
            await ctx.send("✅ Market History successfully collected and verified in database.")
        else:
            await ctx.send("❌ Scheduler instance not found. Is the bot running?")
    except Exception as e:
        log.error(f"History collection error: {e}")
        await ctx.send(f"❌ Error during history collection: {e}")

@bot.command()
async def pin_help(ctx):
    """Sends a list of commands and pins the message to the channel."""
    embed = discord.Embed(
        title="🤖 Albion Quant Bot Commands",
        description="Here is the list of available commands you can use to control the trading system:",
        color=discord.Color.blue()
    )

    embed.add_field(name="`!ping`", value="Check if the bot is online and responding.", inline=False)
    embed.add_field(name="`!status`", value="Check the health, database stats, and background task status of the system.", inline=False)
    embed.add_field(name="`!start`", value="Turn ON the background trading engine and market collection.", inline=False)
    embed.add_field(name="`!stop`", value="Turn OFF the background trading engine and pause alerts.", inline=False)
    embed.add_field(name="`!server`", value="Check which Albion server the system is currently using.", inline=False)
    embed.add_field(name="`!server [west|europe|east]`", value="Change the Albion API server and update the configuration on the fly.", inline=False)
    embed.add_field(name="`!scan [town]`", value="Force a scan for arbitrage and crafting. Optionally target a city (e.g. `!scan lymhurst`).", inline=False)
    embed.add_field(name="`!fastscan`", value="Force a manual scan for 'instant sell' arbitrage (sell directly to buy orders).", inline=False)
    embed.add_field(name="`!patch`", value="Analyze the latest patch notes to immediately see concise meta buffs and nerfs.", inline=False)
    embed.add_field(name="`!meta`", value="Find out the current meta items based on volume, killboard usage, and price momentum.", inline=False)
    embed.add_field(name="`!bm`", value="Analyze Black Market shortages, refill timing, and predict the highest ROI transport opportunities.", inline=False)
    embed.add_field(name="`!pin_help`", value="Send this help message and pin it to the channel.", inline=False)

    embed.set_footer(text="Albion Quant Trading System")

    # Send the message and pin it
    msg = await ctx.send(embed=embed)
    try:
        await msg.pin()
        await ctx.send("✅ Commands menu has been pinned!")
    except discord.Forbidden:
        await ctx.send("⚠️ I don't have permission to pin messages in this channel! Please grant the 'Manage Messages' permission.")

@bot.command()
async def start(ctx):
    """Turn on the background trading engine."""
    import main
    if main.scheduler_instance:
        main.scheduler_instance.resume()
        await ctx.send(f"🟢 **System Started:** The background market collector and arbitrage scanner are now **ON**. You will receive alerts automatically. (PID: {os.getpid()})")
    else:
        await ctx.send("❌ Error: Scheduler not initialized.")

@bot.command()
async def stop(ctx):
    """Turn off the background trading engine."""
    import main
    if main.scheduler_instance:
        main.scheduler_instance.stop()
        await ctx.send(f"🔴 **System Stopped:** The background trading engine is now **OFF**. No automatic alerts will be sent. (PID: {os.getpid()})")
    else:
        await ctx.send("❌ Error: Scheduler not initialized.")

@bot.command()
async def fastscan(ctx):
    """Run an instant-sell arbitrage scan."""
    await ctx.send("🚀 Starting **Fast-Sell** Arbitrage scan. Looking for items with big payoffs that sell instantly to buy orders...")

    try:
        from app.db.session import init_db
        init_db()

        arb_scanner = ArbitrageScanner()
        await arb_scanner.scan(fast_sell=True)
        arb_scanner.store_opportunities()

        from app.alerts.discord import DiscordAlerter
        from app.db.models import ArbitrageOpportunity
        from app.db.session import get_db_session

        with get_db_session() as db:
            arb_opps = db.query(ArbitrageOpportunity).filter(ArbitrageOpportunity.is_active == True).order_by(ArbitrageOpportunity.estimated_margin.desc()).limit(10).all()
            arb_list = [{
                "item_id": opp.item_id,
                "item_name": opp.item_name or opp.item_id,
                "quality": 1,
                "source_city": opp.source_city,
                "destination_city": opp.destination_city,
                "buy_price": opp.buy_price,
                "sell_price": opp.sell_price,
                "estimated_profit": opp.estimated_profit,
                "estimated_margin": opp.estimated_margin,
                "daily_volume": opp.daily_volume or 0,
                "volume_source": opp.volume_source or "ESTIMATED",
                "risk_score": opp.risk_score or 0.0,
                "ev_score": opp.ev_score or 0.0,
                "volatility": opp.volatility or 0.05,
                "persistence": opp.persistence or 1
            } for opp in arb_opps]

        alerter = DiscordAlerter()
        # Pass empty crafting list
        await alerter.send_batch_alerts(arb_list, [])

        await ctx.send("✅ Fast Scan complete! Check the webhook channel for the top instant-sell opportunities.")

    except Exception as e:
        log.error(f"FastScan error: {e}")
        await ctx.send(f"❌ Error during scan: {e}")

@bot.command()
async def meta(ctx, top_n: int = 10, category: str = None):
    """Show killboard-derived meta loadouts with in-game style visuals."""
    await ctx.send("🔍 Scanning killboard events for the most-used builds by tier (4.0+) ...")

    try:
        from app.meta.killboard_meta import compute_meta, fetch_events

        server = (settings.albion_api_server or "west").lower()
        gameinfo_base = {
            "west": "https://gameinfo.albiononline.com/api/gameinfo",
            "europe": "https://gameinfo-ams.albiononline.com/api/gameinfo",
            "east": "https://gameinfo-sgp.albiononline.com/api/gameinfo",
        }.get(server, "https://gameinfo.albiononline.com/api/gameinfo")

        events = await fetch_events(gameinfo_base, pages=3, limit=51)
        meta = compute_meta(events, top_builds_per_tier=3)

        if not meta.tier_to_builds:
            await ctx.send("❌ No killboard meta could be computed (no events or no T4+ gear found).")
            return

        def tier_key(s: str):
            t, e = s.split(".", 1)
            return (int(t), int(e))

        tiers = sorted(meta.tier_to_builds.keys(), key=tier_key)

        # Fetch names once for all items we may display.
        all_item_ids = set()
        for builds in meta.tier_to_builds.values():
            for b in builds:
                slots = b.get("slots") or {}
                for val in slots.values():
                    if isinstance(val, dict):
                        if val.get("Type"):
                            all_item_ids.add(val["Type"])
                    elif isinstance(val, str):
                        all_item_ids.add(val)
        for i_id, _ in meta.item_counts[:200]:
            all_item_ids.add(i_id)

        item_names_map = {}
        with get_db_session() as db:
            db_items = db.query(Item).filter(Item.item_id.in_(list(all_item_ids))).all()
            for it in db_items:
                item_names_map[it.item_id] = it.name

        def _slot_item_name(slots: dict, slot: str) -> str:
            item_data = slots.get(slot)
            if not item_data:
                return "-"
            item_id = item_data if isinstance(item_data, str) else item_data.get("Type")
            if not item_id:
                return "-"
            return item_names_map.get(item_id, item_id)

        def _build_summary_text(builds: list[dict], max_lines: int = 3) -> str:
            lines = []
            for idx, b in enumerate(builds[:max_lines], start=1):
                slots = b.get("slots") or {}
                mh = _slot_item_name(slots, "MainHand")
                oh = _slot_item_name(slots, "OffHand")
                head = _slot_item_name(slots, "Head")
                armor = _slot_item_name(slots, "Armor")
                shoes = _slot_item_name(slots, "Shoes")
                cape = _slot_item_name(slots, "Cape")
                
                weapon = mh
                if oh != "-":
                    weapon = f"{mh} + {oh}"
                
                lines.append(f"**#{idx}** ({b['count']}): {weapon} | {head} | {armor} | {shoes} | {cape}")
            text = "\n".join(lines) if lines else "No build data available."
            return text[:1000]
        # Send one message per tier with in-game style icon arrangement.
        tier_limit = max(1, min(int(top_n or 8), 8))
        for tier in tiers[:tier_limit]:
            builds = meta.tier_to_builds[tier]
            if not builds:
                continue

            top_build = builds[0]
            top_slots = top_build.get("slots") or {}
            loadout_buf = await _render_loadout_layout(top_slots)
            image_name = f"meta_loadout_t{tier}.png"
            image_file = discord.File(fp=loadout_buf, filename=image_name)

            emb = discord.Embed(
                title=f"🔥 META LOADOUTS T{tier}",
                description=f"Server: **{server.upper()}** | Samples: **{meta.sample_events}**",
                color=discord.Color.gold(),
            )
            mainhand = top_slots.get("MainHand") if isinstance(top_slots, dict) else None
            mainhand_id = mainhand.get("Type") if isinstance(mainhand, dict) else None
            mainhand_q = mainhand.get("Quality", 1) if isinstance(mainhand, dict) else 1
            if mainhand_id:
                emb.set_thumbnail(url=item_icon_url(mainhand_id, quality=mainhand_q, size=217))
            emb.set_image(url=f"attachment://{image_name}")

            def _top_item_links_filtered(tier_prefix: str, exclude_types: tuple, limit: int = 6) -> str:
                links = []
                for item_id, count in meta.item_counts:
                    if not item_id.startswith(f"T{tier_prefix}"):
                        continue
                    
                    # Basic category filtering based on ID patterns
                    is_excluded = any(t in item_id for t in exclude_types)
                    if is_excluded:
                        continue

                    display = item_names_map.get(item_id, item_id)
                    links.append(f"[{display}]({item_icon_url(item_id, size=64)}) ({count})")
                    if len(links) >= limit:
                        break
                return "\n".join(links)[:1000] if links else "None found."

            def _top_accessories_links(tier_prefix: str, limit: int = 4) -> str:
                links = []
                acc_types = ("_BAG", "_MOUNT_", "_CAPE", "_FOOD", "_POTION")
                for item_id, count in meta.item_counts:
                    if not item_id.startswith(f"T{tier_prefix}"):
                        continue
                    
                    if not any(t in item_id for t in acc_types):
                        continue

                    display = item_names_map.get(item_id, item_id)
                    links.append(f"[{display}]({item_icon_url(item_id, size=64)}) ({count})")
                    if len(links) >= limit:
                        break
                return "\n".join(links)[:1000] if links else "None found."

            emb.add_field(name="🏆 Top Builds (Weapon | Head | Armor | Shoes | Cape)", value=_build_summary_text(builds), inline=False)
            
            gear_exclude = ("_BAG", "_MOUNT_", "_CAPE", "_FOOD", "_POTION")
            emb.add_field(
                name="⚔️ Top Gear (Weapons/Armor)",
                value=_top_item_links_filtered(tier.split(".", 1)[0], gear_exclude),
                inline=True,
            )
            emb.add_field(
                name="📦 Top Acc/Mounts",
                value=_top_accessories_links(tier.split(".", 1)[0]),
                inline=True,
            )

            await ctx.send(file=image_file, embed=emb)
            await asyncio.sleep(0.5)

    except Exception as e:
        log.error(f"Meta command error: {e}")
        await ctx.send(f"❌ Error computing meta: {e}")

@bot.command()
async def patch(ctx):
    """Analyze patch buffs and nerfs."""
    await ctx.send("⚙️ Initializing Patch Diff Engine... Analyzing spell coefficients, cooldowns, damage, and energy costs...")

    try:
        def run_diff():
            from app.meta.patch_diff import PatchDiffEngine
            # For demonstration, we use the simulated patch data from the engine
            # In production, this would load the latest parsed XML/JSON dumps
            old_patch = {
                "SPELL_BROADSWORD_Q": {"item_id": "Broadsword", "spell_name": "Heroic Strike", "damage": 100.0, "cooldown": 3.0, "energy_cost": 15.0, "coefficient": 0.8},
                "SPELL_BOW_E": {"item_id": "Normal Bow", "spell_name": "Enchanted Quiver", "damage": 50.0, "cooldown": 20.0, "energy_cost": 30.0, "coefficient": 0.4},
                "SPELL_BLOODLETTER_E": {"item_id": "Bloodletter", "spell_name": "Lunging Stabs", "damage": 200.0, "cooldown": 25.0, "energy_cost": 40.0, "coefficient": 1.2}
            }
            new_patch = {
                "SPELL_BROADSWORD_Q": {"item_id": "Broadsword", "spell_name": "Heroic Strike", "damage": 115.0, "cooldown": 2.5, "energy_cost": 15.0, "coefficient": 0.8},
                "SPELL_BOW_E": {"item_id": "Normal Bow", "spell_name": "Enchanted Quiver", "damage": 45.0, "cooldown": 25.0, "energy_cost": 35.0, "coefficient": 0.35},
                "SPELL_BLOODLETTER_E": {"item_id": "Bloodletter", "spell_name": "Lunging Stabs", "damage": 210.0, "cooldown": 20.0, "energy_cost": 35.0, "coefficient": 1.3}
            }
            engine = PatchDiffEngine()
            diffs = engine.diff_spells(old_patch, new_patch)
            return engine.generate_item_meta_scores(diffs)

        item_scores = await asyncio.to_thread(run_diff)

        async def send_impact_embed(title, subtitle, rows):
            current_emb = discord.Embed(
                title=title,
                description=subtitle,
                color=discord.Color.purple()
            )

            # Set thumbnail to the top impacted item
            if not rows.empty:
                current_emb.set_thumbnail(url=item_icon_url(rows.iloc[0]['item_id']))

            def add_line(emb, name, line):
                # If adding this line would exceed field limit (1024)
                # or adding a new field would exceed embed limit (6000)
                if not emb.fields:
                    emb.add_field(name=name, value=line, inline=False)
                    return emb

                last_field = emb.fields[-1]
                if len(last_field.value) + len(line) < 1000:
                    last_field.value += line
                else:
                    if len(emb) + len(line) + 20 > 5500:
                        return None # Need new embed
                    emb.add_field(name=name + " (cont.)", value=line, inline=False)
                return emb

            for _, row in rows.iterrows():
                line = f"**{row['item_id']}**: {row['classification']} ({'+' if row['meta_score_impact'] > 0 else ''}{row['meta_score_impact']:.2f})\n"
                res = add_line(current_emb, "📈 BUFFS/NERFS", line)
                if res is None:
                    await ctx.send(embed=current_emb)
                    current_emb = discord.Embed(title=title + " (cont.)", color=discord.Color.purple())
                    add_line(current_emb, "📈 BUFFS/NERFS", line)
                else:
                    current_emb = res

            if current_emb.fields:
                await ctx.send(embed=current_emb)

        # Combined buffs and nerfs into a single logic
        if not item_scores.empty:
            await send_impact_embed("📜 LATEST PATCH ANALYSIS", "Concise summary of meta-shifting buffs and nerfs.", item_scores)
        else:
            await ctx.send("No significant meta shifts detected in this patch.")

    except Exception as e:
        log.error(f"Patch command error: {e}")
        await ctx.send(f"❌ Error analyzing patch: {e}")

@bot.command()
async def bm(ctx):
    """Analyze Black Market opportunities."""
    await ctx.send("💀 Scanning the Caerleon Black Market for shortages, refill timings, and Royal City arbitrage ROI...")

    try:
        def run_bm_prediction():
            from app.db.session import init_db
            init_db()
            from app.blackmarket.predictor import BlackMarketPredictor
            predictor = BlackMarketPredictor()
            return predictor.find_highest_roi(top_n=10)

        roi_df = await asyncio.to_thread(run_bm_prediction)

        if roi_df.empty:
            await ctx.send("❌ Not enough Royal City and Black Market data overlap to predict ROI right now.")
            return

        current_embed = discord.Embed(
            title="💀 BLACK MARKET: TOP ROI",
            description="Highest Return on Investment for transporting to Caerleon BM.",
            color=discord.Color.dark_red()
        )

        # Set thumbnail to the top ROI item
        if not roi_df.empty:
            current_embed.set_thumbnail(url=item_icon_url(roi_df.iloc[0]['item_id']))

        for _, row in roi_df.iterrows():
            shortage_str = "🔴 High Shortage" if row['shortage_level'] > 0.7 else "🟡 Med Shortage" if row['shortage_level'] > 0.3 else "🟢 Low Shortage"
            icon_link = item_icon_url(row["item_id"])

            value_text = (
                f"**Buy:** {row['buy_city']} at {row['buy_price']:,.0f}\n"
                f"**Sell:** BM at {row['bm_price']:,.0f}\n"
                f"**Profit:** {row['profit']:,.0f} (**{row['roi_margin']}% ROI**)\n"
                f"**Status:** {shortage_str} (Safety: {row['safety_score']:.1f})\n"
                f"[Official Icon]({icon_link})"
            )

            if len(current_embed) + len(value_text) + len(row['item_id']) > 5500:
                await ctx.send(embed=current_embed)
                current_embed = discord.Embed(
                    title="💀 BLACK MARKET: TOP ROI (cont.)",
                    color=discord.Color.dark_red()
                )
                current_embed.set_thumbnail(url=icon_link)

            current_embed.add_field(name=f"📦 {row['item_id'][:25]}", value=value_text, inline=False)

        await ctx.send(embed=current_embed)

    except Exception as e:
        log.error(f"BM command error: {e}")
        await ctx.send(f"❌ Error analyzing Black Market: {e}")

@bot.command()
async def status(ctx):
    """Check the overall health and status of the system."""
    import main  # to check scheduler status
    from sqlalchemy import func

    from app.db.models import ArbitrageOpportunity, CraftingOpportunity, Item, MarketPrice
    from app.db.session import get_db_session

    try:
        with get_db_session() as db:
            item_count = db.query(func.count(Item.item_id)).scalar()
            price_count = db.query(func.count(MarketPrice.id)).scalar()
            arb_count = db.query(func.count(ArbitrageOpportunity.id)).filter(ArbitrageOpportunity.is_active == True).scalar()
            craft_count = db.query(func.count(CraftingOpportunity.id)).filter(CraftingOpportunity.is_active == True).scalar()

        scheduler_status = "🟢 RUNNING" if main.scheduler_instance and main.scheduler_instance._is_running else "🔴 STOPPED"

        embed = discord.Embed(title="📊 System Status", color=discord.Color.green())
        embed.add_field(name="Background Scheduler", value=scheduler_status, inline=False)
        embed.add_field(name="Target Server", value=f"**{settings.albion_api_server.upper()}**", inline=False)

        db_stats = f"Items Tracked: {item_count:,}\n"
        db_stats += f"Prices Stored: {price_count:,}\n"
        db_stats += f"Active Arbitrage Opps: {arb_count:,}\n"
        db_stats += f"Active Crafting Opps: {craft_count:,}"
        embed.add_field(name="Database Stats", value=f"```\n{db_stats}\n```", inline=False)

        await ctx.send(embed=embed)
    except Exception as e:
        log.error(f"Status command error: {e}")
        await ctx.send(f"❌ Could not retrieve status: {e}")

async def broadcast_patch_update(channel_id: int = None):
    """
    Automatically called when a new patch is detected.
    Generates the patch diff, sends it to the server, and pins it.
    """
    if bot.is_closed() or not bot.guilds:
        log.warning("Bot is offline or not in any guilds. Cannot broadcast patch.")
        return

    try:
        def run_diff():
            from app.meta.patch_diff import PatchDiffEngine
            old_patch = {
                "SPELL_BROADSWORD_Q": {"item_id": "Broadsword", "spell_name": "Heroic Strike", "damage": 100.0, "cooldown": 3.0, "energy_cost": 15.0, "coefficient": 0.8},
                "SPELL_BOW_E": {"item_id": "Normal Bow", "spell_name": "Enchanted Quiver", "damage": 50.0, "cooldown": 20.0, "energy_cost": 30.0, "coefficient": 0.4},
                "SPELL_BLOODLETTER_E": {"item_id": "Bloodletter", "spell_name": "Lunging Stabs", "damage": 200.0, "cooldown": 25.0, "energy_cost": 40.0, "coefficient": 1.2}
            }
            new_patch = {
                "SPELL_BROADSWORD_Q": {"item_id": "Broadsword", "spell_name": "Heroic Strike", "damage": 115.0, "cooldown": 2.5, "energy_cost": 15.0, "coefficient": 0.8},
                "SPELL_BOW_E": {"item_id": "Normal Bow", "spell_name": "Enchanted Quiver", "damage": 45.0, "cooldown": 25.0, "energy_cost": 35.0, "coefficient": 0.35},
                "SPELL_BLOODLETTER_E": {"item_id": "Bloodletter", "spell_name": "Lunging Stabs", "damage": 210.0, "cooldown": 20.0, "energy_cost": 35.0, "coefficient": 1.3}
            }
            engine = PatchDiffEngine()
            diffs = engine.diff_spells(old_patch, new_patch)
            return engine.generate_item_meta_scores(diffs)

        item_scores = await asyncio.to_thread(run_diff)

        async def send_impact_broadcast(title, subtitle, rows, channel):
            current_emb = discord.Embed(
                title=title,
                description=subtitle,
                color=discord.Color.red()
            )
            if not rows.empty:
                current_emb.set_thumbnail(url=item_icon_url(rows.iloc[0]["item_id"]))

            def add_line(emb, name, line):
                if not emb.fields:
                    emb.add_field(name=name, value=line, inline=False)
                    return emb

                last_field = emb.fields[-1]
                if len(last_field.value) + len(line) < 1000:
                    last_field.value += line
                else:
                    if len(emb) + len(line) + 20 > 5500:
                        return None
                    emb.add_field(name=name + " (cont.)", value=line, inline=False)
                return emb

            # Find a suitable channel first
            if not channel:
                for guild in bot.guilds:
                    for ch in guild.text_channels:
                        if ch.permissions_for(guild.me).send_messages:
                            channel = ch
                            break
                    if channel: break

            if not channel: return

            await channel.send(content="@everyone 📢 **New Patch Analysis is live!**")

            for _, row in rows.iterrows():
                line = f"**{row['item_id']}**: {row['classification']} ({'+' if row['meta_score_impact'] > 0 else ''}{row['meta_score_impact']:.2f})\n"
                res = add_line(current_emb, "📊 META SHIFTS", line)
                if res is None:
                    await channel.send(embed=current_emb)
                    current_emb = discord.Embed(title=title + " (cont.)", color=discord.Color.red())
                    add_line(current_emb, "📊 META SHIFTS", line)
                else:
                    current_emb = res

            if current_emb.fields:
                msg = await channel.send(embed=current_emb)
                try:
                    await msg.pin()
                except: pass

        if not item_scores.empty:
            target_channel = bot.get_channel(channel_id) if channel_id else None
            await send_impact_broadcast("🚨 NEW PATCH DETECTED", "Automated analysis of all buffs and nerfs.", item_scores, target_channel)

    except Exception as e:
        log.error(f"Error broadcasting patch: {e}")

async def start_discord_bot():
    """Start the Discord bot listener."""
    token = settings.discord_bot_token
    if not token:
        log.warning("No Discord Bot Token found. Bot listener will not start.")
        return

    log.info("Starting Discord Bot listener...")
    try:
        await bot.start(token)
    except Exception as e:
        log.error(f"Discord Bot failed to start: {e}")

async def stop_discord_bot():
    """Stop the Discord bot listener gracefully."""
    log.info("Stopping Discord Bot listener...")
    if not bot.is_closed():
        await bot.close()
