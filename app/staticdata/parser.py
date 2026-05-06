"""
Static Data Parser for Albion Online.
Downloads and parses ao-bin-dumps data (items, recipes, localization).
Creates canonical item identifiers and populates the database.
"""

import json
import re

import httpx
from sqlalchemy.orm import Session

from app.core.config import PARSED_DIR, RAW_DIR
from app.core.logging import log
from app.db.models import Item, Recipe
from app.db.session import get_db_session

# ao-bin-dumps GitHub raw URLs
AO_BIN_DUMPS_BASE = "https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master"
ITEMS_URL = f"{AO_BIN_DUMPS_BASE}/items.json"
LOCALIZATION_URL = f"{AO_BIN_DUMPS_BASE}/formatted/items.json"


class StaticDataParser:
    """
    Parses static game data from ao-bin-dumps.
    Extracts items, crafting recipes, and localization names.
    """

    def __init__(self):
        self.items_raw: list = []
        self.items_formatted: dict = {}
        self.parsed_items: list[dict] = []
        self.parsed_recipes: list[dict] = []

    async def download_static_data(self) -> None:
        """Download raw data files from ao-bin-dumps GitHub."""
        log.info("Downloading static data from ao-bin-dumps...")

        async with httpx.AsyncClient(timeout=60.0) as client:
            # Download items.json
            log.info("Fetching items.json...")
            resp = await client.get(ITEMS_URL)
            resp.raise_for_status()
            items_path = RAW_DIR / "items.json"
            items_path.write_text(resp.text, encoding="utf-8")
            log.info(f"Saved items.json ({len(resp.text)} bytes)")

            # Download formatted items for localization
            log.info("Fetching formatted/items.json...")
            try:
                resp2 = await client.get(LOCALIZATION_URL)
                resp2.raise_for_status()
                loc_path = RAW_DIR / "items_formatted.json"
                loc_path.write_text(resp2.text, encoding="utf-8")
                log.info(f"Saved items_formatted.json ({len(resp2.text)} bytes)")
            except Exception as e:
                log.warning(f"Could not download formatted items: {e}")

    def load_raw_data(self) -> None:
        """Load raw JSON data from disk."""
        items_path = RAW_DIR / "items.json"
        if not items_path.exists():
            raise FileNotFoundError(
                f"items.json not found at {items_path}. Run download_static_data() first."
            )

        with open(items_path, encoding="utf-8") as f:
            data = json.load(f)

        # The items.json structure can vary — handle both list and dict formats
        if isinstance(data, dict):
            # Sometimes wrapped in a root key
            if "items" in data:
                items_section = data["items"]
                if isinstance(items_section, dict) and "equipmentitem" in items_section:
                    # Flatten all item types
                    self.items_raw = []
                    for key, value in items_section.items():
                        if isinstance(value, list):
                            self.items_raw.extend(value)
                        elif isinstance(value, dict):
                            self.items_raw.append(value)
                else:
                    self.items_raw = items_section if isinstance(items_section, list) else [items_section]
            else:
                self.items_raw = [data]
        elif isinstance(data, list):
            self.items_raw = data
        else:
            self.items_raw = []

        log.info(f"Loaded {len(self.items_raw)} raw items")

        # Load formatted items for name lookup
        formatted_path = RAW_DIR / "items_formatted.json"
        if formatted_path.exists():
            with open(formatted_path, encoding="utf-8") as f:
                formatted_data = json.load(f)
            # Build lookup by UniqueName
            if isinstance(formatted_data, list):
                self.items_formatted = {
                    item.get("UniqueName", ""): item
                    for item in formatted_data
                    if isinstance(item, dict)
                }
            elif isinstance(formatted_data, dict):
                self.items_formatted = formatted_data
            log.info(f"Loaded {len(self.items_formatted)} formatted item names")

    @staticmethod
    def parse_item_id(unique_name: str) -> dict:
        """
        Parse a canonical item ID into its components.
        
        Examples:
            T4_BAG -> tier=4, enchant=0
            T6_2H_BOW -> tier=6, enchant=0
            T8_MAIN_FIRESTAFF@3 -> tier=8, enchant=3
        """
        result = {
            "item_id": unique_name,
            "tier": None,
            "enchant": 0,
        }

        # Extract enchantment level
        if "@" in unique_name:
            base, enchant_str = unique_name.rsplit("@", 1)
            try:
                result["enchant"] = int(enchant_str)
            except ValueError:
                pass
            result["item_id"] = unique_name  # Keep full ID with @

        # Extract tier
        tier_match = re.match(r"T(\d+)_", unique_name)
        if tier_match:
            result["tier"] = int(tier_match.group(1))

        return result

    def parse_items(self) -> list[dict]:
        """Parse raw items into normalized item records."""
        self.parsed_items = []

        for raw_item in self.items_raw:
            if not isinstance(raw_item, dict):
                continue

            unique_name = raw_item.get("@uniquename", raw_item.get("UniqueName", ""))
            if not unique_name:
                continue

            # Parse ID components
            id_parts = self.parse_item_id(unique_name)

            # Get localized name
            formatted = self.items_formatted.get(unique_name, {})
            name = unique_name
            if isinstance(formatted, dict):
                localized = formatted.get("LocalizedNames")
                if isinstance(localized, dict):
                    name = localized.get("EN-US", "") or unique_name

            item = {
                "item_id": unique_name,
                "name": name,
                "tier": id_parts["tier"],
                "enchant": id_parts["enchant"],
                "category": raw_item.get("@shopcategory", raw_item.get("shopcategory", "")),
                "subcategory": raw_item.get("@shopsubcategory1", raw_item.get("shopsubcategory1", "")),
                "shop_category": raw_item.get("@shopcategory", ""),
                "shop_subcategory": raw_item.get("@shopsubcategory1", ""),
                "weight": float(raw_item.get("@weight", 0) or 0),
                "max_stack": int(raw_item.get("@maxstacksize", 999) or 999),
                "item_value": float(raw_item.get("@itemvalue", 0) or 0),
                "is_craftable": False,
            }

            # Check for crafting requirements
            craftingrequirements = raw_item.get("craftingrequirements", None)
            if craftingrequirements:
                item["is_craftable"] = True
                self._parse_recipe(unique_name, craftingrequirements, raw_item)

            # Handle enchantment variants
            enchantments = raw_item.get("enchantments", {})
            if isinstance(enchantments, dict):
                enchant_list = enchantments.get("enchantment", [])
                if isinstance(enchant_list, dict):
                    enchant_list = [enchant_list]
                for ench in enchant_list:
                    if not isinstance(ench, dict):
                        continue
                    ench_level = int(ench.get("@enchantmentlevel", 0) or 0)
                    if ench_level > 0:
                        ench_id = f"{unique_name}@{ench_level}"
                        ench_item = item.copy()
                        ench_item["item_id"] = ench_id
                        ench_item["enchant"] = ench_level
                        ench_item["name"] = f"{name} .{ench_level}"

                        # Parse enchanted recipe if present
                        ench_craft = ench.get("craftingrequirements", None)
                        if ench_craft:
                            ench_item["is_craftable"] = True
                            self._parse_recipe(ench_id, ench_craft, ench)

                        self.parsed_items.append(ench_item)

            self.parsed_items.append(item)

        log.info(f"Parsed {len(self.parsed_items)} items, {len(self.parsed_recipes)} recipe ingredients")
        return self.parsed_items

    def _parse_recipe(self, crafted_item_id: str, craft_req: dict | list, raw_item: dict) -> None:
        """Parse crafting requirements into recipe ingredients."""
        if isinstance(craft_req, list):
            # Multiple recipe variants — use first
            craft_req = craft_req[0] if craft_req else {}

        if not isinstance(craft_req, dict):
            return

        # Get crafting resources
        resources = craft_req.get("craftresource", [])
        if isinstance(resources, dict):
            resources = [resources]

        crafting_station = craft_req.get("@craftingstation", "")
        nutrition = float(craft_req.get("@amountofnutrition", 0) or 0)
        focus = float(craft_req.get("@craftingfocus", 0) or 0)
        fame = float(craft_req.get("@craftingfame", 0) or 0)

        for resource in resources:
            if not isinstance(resource, dict):
                continue

            ingredient_id = resource.get("@uniquename", "")
            quantity = float(resource.get("@count", 1) or 1)

            if ingredient_id:
                self.parsed_recipes.append({
                    "crafted_item_id": crafted_item_id,
                    "ingredient_item_id": ingredient_id,
                    "quantity": quantity,
                    "crafting_station": crafting_station,
                    "nutrition_cost": nutrition,
                    "focus_cost": focus,
                    "crafting_fame": fame,
                })

    def save_parsed_data(self) -> None:
        """Save parsed data to JSON files for inspection."""
        items_out = PARSED_DIR / "items_parsed.json"
        with open(items_out, "w", encoding="utf-8") as f:
            json.dump(self.parsed_items, f, indent=2, ensure_ascii=False)
        log.info(f"Saved {len(self.parsed_items)} items to {items_out}")

        recipes_out = PARSED_DIR / "recipes_parsed.json"
        with open(recipes_out, "w", encoding="utf-8") as f:
            json.dump(self.parsed_recipes, f, indent=2, ensure_ascii=False)
        log.info(f"Saved {len(self.parsed_recipes)} recipes to {recipes_out}")

    def populate_database(self, db: Session) -> None:
        """Insert parsed items and recipes into the database."""
        log.info("Populating database with static data...")

        # Upsert items
        item_count = 0
        for item_data in self.parsed_items:
            existing = db.query(Item).filter_by(item_id=item_data["item_id"]).first()
            if existing:
                for key, value in item_data.items():
                    setattr(existing, key, value)
            else:
                db.add(Item(**item_data))
            item_count += 1

            if item_count % 1000 == 0:
                db.flush()

        db.flush()
        log.info(f"Upserted {item_count} items")

        # Insert recipes (clear old ones first)
        db.query(Recipe).delete()
        recipe_count = 0
        for recipe_data in self.parsed_recipes:
            db.add(Recipe(**recipe_data))
            recipe_count += 1

            if recipe_count % 1000 == 0:
                db.flush()

        db.flush()
        log.info(f"Inserted {recipe_count} recipe ingredients")

    async def run_full_pipeline(self) -> dict:
        """
        Complete static data pipeline:
        1. Download from GitHub
        2. Parse items and recipes
        3. Save parsed JSON
        4. Populate database
        """
        log.info("=" * 60)
        log.info("STATIC DATA PIPELINE - START")
        log.info("=" * 60)

        await self.download_static_data()
        self.load_raw_data()
        self.parse_items()
        self.save_parsed_data()

        with get_db_session() as db:
            self.populate_database(db)

        stats = {
            "items_parsed": len(self.parsed_items),
            "recipes_parsed": len(self.parsed_recipes),
        }

        log.info(f"STATIC DATA PIPELINE - COMPLETE: {stats}")
        return stats
