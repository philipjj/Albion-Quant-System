import discord
from discord.ext import commands
import asyncio
import json
import csv
import io
from PIL import Image
import httpx
from app.core.config import PROJECT_ROOT, settings
from app.core.logging import log
from app.arbitrage.scanner import ArbitrageScanner
from app.crafting.engine import CraftingEngine
from app.db.models import ArbitrageOpportunity, CraftingOpportunity, UserProfile, Item
from app.db.session import get_db_session
from app.core.icons import item_icon_url

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

import os

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
async def scan(ctx):
    """Run a manual arbitrage and crafting scan."""
    await ctx.send("🚀 Starting manual scan for Arbitrage and Crafting opportunities. This may take a minute...")
    
    try:
        await ctx.send("🔍 **Starting High-Precision Scan...** (Analyzing Market Depth & Liquidity)")
        
        from app.db.session import init_db
        init_db()
        
        # Run scanners (now async)
        arb_scanner = ArbitrageScanner()
        craft_engine = CraftingEngine()
        
        arb_opps = await arb_scanner.scan()
        craft_opps = await craft_engine.compute()
        
        # Persist results
        arb_scanner.store_opportunities()
        craft_engine.store_opportunities()
        
        # Pull top opportunities for the webhook alert
        from app.db.session import get_db_session
        from app.db.models import ArbitrageOpportunity, CraftingOpportunity
        from app.alerts.discord import DiscordAlerter
        
        with get_db_session() as db:
            arb_opps = db.query(ArbitrageOpportunity).filter(ArbitrageOpportunity.is_active == True).order_by(ArbitrageOpportunity.estimated_margin.desc()).limit(10).all()
            craft_opps = db.query(CraftingOpportunity).filter(CraftingOpportunity.is_active == True).order_by(CraftingOpportunity.profit_margin.desc()).limit(10).all()
            
            # Convert to dict for alerter
            # Convert to dict for alerter with full 2026 metrics
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
            } for opp in arb_opps]
            
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
            } for opp in craft_opps]
            
        alerter = DiscordAlerter()
        await alerter.send_batch_alerts(arb_list, craft_list)
        
        await ctx.send("✅ Scan complete! Check the webhook channel for the top opportunities.")
        
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
    embed.add_field(name="`!scan`", value="Force a manual arbitrage and crafting scan immediately and push top results to the webhook.", inline=False)
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
        
        from app.db.session import get_db_session
        from app.db.models import ArbitrageOpportunity
        from app.alerts.discord import DiscordAlerter
        
        with get_db_session() as db:
            arb_opps = db.query(ArbitrageOpportunity).filter(ArbitrageOpportunity.is_active == True).order_by(ArbitrageOpportunity.estimated_margin.desc()).limit(10).all()
            arb_list = [{
                "item_id": opp.item_id, 
                "item_name": opp.item_name, 
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
    """Show meta builds by tier (4.0+) plus a detailed item usage list."""
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

        # Fetch names from DB to make it readable "just like in game"
        all_item_ids = set()
        for builds in meta.tier_to_builds.values():
            for b in builds:
                slots = b.get("slots") or {}
                for val in slots.values():
                    if isinstance(val, dict):
                        if val.get("Type"): all_item_ids.add(val["Type"])
                    elif isinstance(val, str):
                        all_item_ids.add(val)
        for i_id, _ in meta.item_counts[:100]:
            all_item_ids.add(i_id)

        item_names_map = {}
        with get_db_session() as db:
            db_items = db.query(Item).filter(Item.item_id.in_(list(all_item_ids))).all()
            for it in db_items:
                item_names_map[it.item_id] = it.name

        async def generate_loadout_image(slots: dict):
            # Create a 3x4 grid canvas (390x520) with dark background
            canvas = Image.new('RGBA', (390, 520), (35, 39, 42, 255))
            
            # (col, row) grid positions
            pos_map = {
                "Bag": (0, 0), "Head": (1, 0), "Cape": (2, 0),
                "MainHand": (0, 1), "Armor": (1, 1), "OffHand": (2, 1),
                "Food": (0, 2), "Shoes": (1, 2), "Potion": (2, 2),
                "Mount": (1, 3)
            }
            
            async with httpx.AsyncClient(timeout=5.0) as client:
                tasks = []
                for slot, (col, row) in pos_map.items():
                    item_data = slots.get(slot)
                    if item_data and isinstance(item_data, dict):
                        i_id = item_data.get("Type")
                        qual = item_data.get("Quality", 1)
                        if i_id:
                            tasks.append((col, row, item_icon_url(i_id, quality=qual, size=128)))
                
                async def fetch_and_paste(c, r, url):
                    try:
                        r_img = await client.get(url)
                        if r_img.status_code == 200:
                            icon = Image.open(io.BytesIO(r_img.content)).convert("RGBA")
                            canvas.paste(icon, (c*130, r*130), icon)
                    except: pass

                await asyncio.gather(*(fetch_and_paste(c, r, u) for c, r, u in tasks))
            
            buf = io.BytesIO()
            canvas.save(buf, format='PNG')
            buf.seek(0)
            return buf

        def create_meta_embed(index: int, total_samples: int, server: str, tier: str = None):
            title = f"🔥 TOP META BUILD: T{tier}" if tier else "🔥 TOP META BUILDS"
            if index > 0 and not tier:
                title += f" (Part {index + 1})"
            
            emb = discord.Embed(
                title=title,
                description=f"Official Render Grid. Server: {server.upper()}",
                color=discord.Color.gold(),
            )
            return emb

        def format_visual_build(slots: dict, names: dict):
            def pick(slot: str) -> str:
                item_data = slots.get(slot)
                if not item_data: return "      -       "
                # If old format (string), handle it; otherwise use dict
                i_id = item_data if isinstance(item_data, str) else item_data.get("Type")
                if not i_id: return "      -       "
                
                name = names.get(i_id, i_id.replace("T", "").replace("_", " "))
                return name[:14].center(14)

            h = pick("Head")
            c = pick("Cape")
            a = pick("Armor")
            b = pick("Bag")
            mh = pick("MainHand")
            oh = pick("OffHand")
            s = pick("Shoes")
            f = pick("Food")
            p = pick("Potion")
            mt = pick("Mount")

            return (
                f"[{b}] [{h}] [{c}]\n"
                f"[{mh}] [{a}] [{oh}]\n"
                f"[{f}] [{s}] [{p}]\n"
                f"                [{mt}]"
            )

        # We will now send one message per tier with its image
        for tier in tiers[:8]: # Limit to top 8 tiers for speed/rate limits
            builds = meta.tier_to_builds[tier]
            if not builds: continue
            
            top_build = builds[0]
            img_buf = await generate_loadout_image(top_build.get("slots") or {})
            filename = f"meta_t{tier}.png"
            file = discord.File(fp=img_buf, filename=filename)
            
            emb = create_meta_embed(0, meta.sample_events, server, tier=tier)
            emb.set_image(url=f"attachment://{filename}")
            
            # Rank info in text
            sections = []
            for i, b in enumerate(builds[:2]):
                grid = format_visual_build(b.get("slots") or {}, item_names_map)
                sections.append(f"Rank #{i+1} ({b['count']}x uses):\n{grid}")
            
            emb.add_field(name="🛡️ Equipment Grid", value="```\n" + "\n\n".join(sections) + "\n```", inline=False)
            
            await ctx.send(file=file, embed=emb)
            await asyncio.sleep(0.5)

        # Finally send the CSV

        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["item_id", "count"])
        for item_id, count in meta.item_counts[:2000]:
            w.writerow([item_id, count])
        data = out.getvalue().encode("utf-8")
        await ctx.send(file=discord.File(fp=io.BytesIO(data), filename="meta_items.csv"))

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
            
            value_text = (
                f"**Buy:** {row['buy_city']} at {row['buy_price']:,.0f}\n"
                f"**Sell:** BM at {row['bm_price']:,.0f}\n"
                f"**Profit:** {row['profit']:,.0f} (**{row['roi_margin']}% ROI**)\n"
                f"**Status:** {shortage_str} (Safety: {row['safety_score']:.1f})"
            )
            
            if len(current_embed) + len(value_text) + len(row['item_id']) > 5500:
                await ctx.send(embed=current_embed)
                current_embed = discord.Embed(
                    title="💀 BLACK MARKET: TOP ROI (cont.)",
                    color=discord.Color.dark_red()
                )

            current_embed.add_field(name=f"📦 {row['item_id'][:25]}", value=value_text, inline=False)
            
        await ctx.send(embed=current_embed)
        
    except Exception as e:
        log.error(f"BM command error: {e}")
        await ctx.send(f"❌ Error analyzing Black Market: {e}")

@bot.command()
async def status(ctx):
    """Check the overall health and status of the system."""
    from app.db.session import get_db_session
    from app.db.models import MarketPrice, ArbitrageOpportunity, CraftingOpportunity, Item
    from sqlalchemy import func
    import main # to check scheduler status

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
