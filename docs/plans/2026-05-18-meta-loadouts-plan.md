# Meta Builds & Loadouts Integration Plan

## 1. Research Summary: Albion Online Meta (May 2026)

Based on current research, the following item combinations and loadouts define the current meta for different playstyles. We can use this data to enhance AQS by providing better recommendations and adjusting market demand multipliers.

### 1.1 PvP Meta Loadout
*   **Playstyle:** Mobility, burst damage, and tactical outplay.
*   **S-Tier Weapons:** Carving Sword, Bloodletter, Bear Paws, Fists of Avalon.
*   **Popular Ganking/Solo Build:**
    *   **Weapon:** Bloodletter or Bear Paws
    *   **Armor:** Stalker Jacket
    *   **Head/Shoes:** Mercenary Hood / Assassin Hood, Any Sandals
    *   **Cape:** Avalonian Cape or Thetford Cape
    *   **Consumables:** Invisibility Potion, High-tier Stew (Avalon Stew)

### 1.2 PvE Meta Loadout
*   **Playstyle:** AoE damage, sustain, and fast clearing.
*   **Top Weapons:** 1H Spear, Battleaxe, Light Crossbow, Nature Staff, Dual Swords.
*   **Common Armor Choices:**
    *   **Chest:** Mercenary Jacket (for sustain), Cultist Robe (for damage/utility), Mage Robe.
    *   **Head:** Guardian Helmet, Assassin Hood.
    *   **Shoes:** Leather/Soldier Boots (Rejuvenating Sprint).
    *   **Consumables:** Pork Omelette (Cooldown reduction), Thetford/Avalonian Cape.

### 1.3 Highest DPS Potential Items
*   **Burst/Assassination (PvP):** 1H Dagger, Dagger Pair, Heavy Crossbow, Cursed Staffs (1H, Cursed Skull).
*   **Sustained DPS (PvE/Bossing):** Fire Staffs, Crossbows, Great Axe.
*   **Synergy Gear (Glass Cannon):** Cleric Robe, Mage Robe, Royal Sandals, Poison Potions.

### 1.4 Highest Self-Sustainable Build (Solo Play)
*   **The Gold Standard:** Battleaxe Build
    *   **Weapon:** Battleaxe (Built-in healing via "Blood Bandit").
    *   **Off-hand:** Torch (increases attack speed to trigger healing/cooldowns).
    *   **Chest:** Mercenary Jacket ("Bloodlust" provides massive healing on hit).
    *   **Head:** Guardian Helmet or Hunter Hood.
    *   **Shoes:** Any leather boots.
    *   **Food:** Roasted Pure Mist Snapper (Life Steal) or Pork Omelette (Cooldowns).
*   **Alternatives:** 1H Spear + Mercenary Jacket, Nature Staffs.

---

## 2. Integration Plan into Albion Quant System (AQS)

Currently, AQS has a basic `!meta` command and applies an `item_is_meta` multiplier to Expected Value (EV). We can expand this system to leverage the specific loadouts above.

### Phase 1: Meta Database Expansion
1.  **Create a Loadout Config:** Implement a `meta_loadouts.yaml` or a dedicated DB table to store the meta combinations (PvP, PvE, DPS, Solo Sustain).
2.  **Tagging System:** Tag individual items (e.g., `T4_MAIN_AXE`) with categories like `solo_sustain`, `pvp_burst`, `pve_clear`.

### Phase 2: Scoring Engine Enhancements (`app/core/scoring.py`)
1.  **Dynamic EV Multipliers:** Modify `_get_meta_multipliers()` to increase the EV for items that appear across multiple meta loadouts (e.g., Mercenary Jacket, Thetford Cape).
2.  **Synergy Demand:** If a weapon is trending (e.g., Battleaxe), automatically boost the demand/confidence score of its synergistic items (Torch, Mercenary Jacket).

### Phase 3: Discord Bot UI Additions (`app/alerts/bot.py`)
1.  **Expanded `!meta` Command:** 
    *   `!meta pvp` -> Shows top PvP loadouts.
    *   `!meta pve` -> Shows top PvE loadouts.
    *   `!meta dps` -> Shows highest DPS potential items.
    *   `!meta solo` -> Shows highest self-sustainable builds.
2.  **Visual Embeds:** Use the newly redesigned premium Discord embeds to display these loadouts, including icons for the weapon, armor, and consumables required.

### Phase 4: Market Signals Integration
1.  **Alerting on Meta Shifts:** When patch notes drop, cross-reference nerfed/buffed items with our `meta_loadouts` database.
2.  **Arbitrage Prioritization:** Items identified in the "Solo Sustain" or "PvP Meta" lists have higher liquidity. The system should prioritize highlighting arbitrage opportunities for these specific items over niche equipment.
