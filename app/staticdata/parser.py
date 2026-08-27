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
    Extracts items, crafting recipes, and localization names across all game categories.
    """

    def __init__(self):
        self.items_raw: list[dict] = []
        self.items_formatted: dict[str, str] = {}
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
        """Load raw JSON data from disk across all 20 item categories."""
        items_path = RAW_DIR / "items.json"
        if not items_path.exists():
            raise FileNotFoundError(
                f"items.json not found at {items_path}. Run download_static_data() first."
            )

        with open(items_path, encoding="utf-8") as f:
            data = json.load(f)

        self.items_raw = []
        if isinstance(data, dict) and "items" in data:
            items_section = data["items"]
            if isinstance(items_section, dict):
                for section_name, section_items in items_section.items():
                    if section_name.startswith("@") or section_name == "shopcategories":
                        continue
                    if isinstance(section_items, list):
                        self.items_raw.extend(section_items)
                    elif isinstance(section_items, dict):
                        self.items_raw.append(section_items)
        elif isinstance(data, list):
            self.items_raw = data

        log.info(f"Loaded {len(self.items_raw)} raw items across all categories.")

        # Load formatted items for English localization name lookup
        formatted_path = RAW_DIR / "items_formatted.json"
        self.items_formatted = {}
        if formatted_path.exists():
            with open(formatted_path, encoding="utf-8") as f:
                formatted_data = json.load(f)
            if isinstance(formatted_data, list):
                for item in formatted_data:
                    if isinstance(item, dict):
                        uid = item.get("UniqueName", "")
                        loc_dict = item.get("LocalizedNames")
                        if isinstance(loc_dict, dict):
                            en_name = loc_dict.get("EN-US", "")
                            if uid and en_name:
                                self.items_formatted[uid] = en_name
            elif isinstance(formatted_data, dict):
                for uid, item in formatted_data.items():
                    if isinstance(item, dict):
                        loc_dict = item.get("LocalizedNames", {})
                        if isinstance(loc_dict, dict):
                            en_name = loc_dict.get("EN-US", "")
                            if uid and en_name:
                                self.items_formatted[uid] = en_name
                    elif isinstance(item, str):
                        self.items_formatted[uid] = item
            log.info(f"Loaded {len(self.items_formatted)} English localized item names.")

    @staticmethod
    def get_tier(unique_name: str, raw_item: dict) -> int | None:
        """Extracts official item tier."""
        raw_tier = raw_item.get("@tier")
        if raw_tier is not None and str(raw_tier).isdigit():
            return int(raw_tier)
        m = re.search(r"(?:^T|_T)(\d+)(?:_|$|@)", unique_name)
        if m:
            return int(m.group(1))
        return None

    @staticmethod
    def normalize_category(unique_name: str, cat: str, subcat: str) -> tuple[str, str]:
        """Normalizes and maps item categories and subcategories to authoritative standardized values."""
        uid_upper = unique_name.upper()
        cat = (cat or "").lower().strip()
        subcat = (subcat or "").lower().strip()

        # Tokens & Royal Sigils
        if "QUESTITEM_TOKEN_ROYAL" in uid_upper or "ROYAL_SIGIL" in uid_upper:
            return "token", "royal_sigil"
        if "QUESTITEM_TOKEN_ARENA" in uid_upper:
            return "token", "arena_sigil"
        if "QUESTITEM_TOKEN_AVALON" in uid_upper or "SHARD_AVALONIAN" in uid_upper:
            return "artefacts", "shard_avalonian"
        if uid_upper.endswith("_RUNE") or "_RUNE@" in uid_upper:
            return "artefacts", "rune"
        if uid_upper.endswith("_SOUL") or "_SOUL@" in uid_upper:
            return "artefacts", "soul"
        if uid_upper.endswith("_RELIC") or "_RELIC@" in uid_upper:
            return "artefacts", "relic"
        if "_ARTEFACT_" in uid_upper:
            return "artefacts", subcat or "artefact"

        # Consumables
        if "_POTION_" in uid_upper or subcat == "potions":
            return "consumables", "potions"
        if "_MEAL_" in uid_upper or subcat == "food":
            return "consumables", "food"

        # Armors & Clothing
        if cat == "armors" or "_ARMOR_" in uid_upper:
            if "CLOTH" in uid_upper or "cloth" in subcat:
                return "armors", "cloth_armor"
            if "LEATHER" in uid_upper or "leather" in subcat:
                return "armors", "leather_armor"
            if "PLATE" in uid_upper or "plate" in subcat:
                return "armors", "plate_armor"
            return "armors", subcat or "other"

        # Helmets / Headwear
        if cat == "head" or "_HEAD_" in uid_upper:
            if "CLOTH" in uid_upper or "cloth" in subcat:
                return "head", "cloth_helmet"
            if "LEATHER" in uid_upper or "leather" in subcat:
                return "head", "leather_helmet"
            if "PLATE" in uid_upper or "plate" in subcat:
                return "head", "plate_helmet"
            return "head", subcat or "other"

        # Shoes / Footwear
        if cat == "shoes" or "_SHOES_" in uid_upper:
            if "CLOTH" in uid_upper or "cloth" in subcat:
                return "shoes", "cloth_shoes"
            if "LEATHER" in uid_upper or "leather" in subcat:
                return "shoes", "leather_shoes"
            if "PLATE" in uid_upper or "plate" in subcat:
                return "shoes", "plate_shoes"
            return "shoes", subcat or "other"

        # Weapons
        if "_SHAPESHIFTER_" in uid_upper:
            return "weapons", "shapeshifterstaff"
        if cat == "weapons":
            return "weapons", subcat or "other"

        # Offhands
        if cat == "offhands" or any(oh in uid_upper for oh in ["_OFF_", "_SHIELD", "_TOME", "_TORCH", "_HORN", "_BOOK", "_TOTEM"]):
            return "offhands", subcat or "other"

        # Capes, Bags, Mounts
        if "_CAPEITEM_" in uid_upper or "_CAPE" in uid_upper or cat == "capes":
            return "capes", subcat or "capes"
        if "_BAG" in uid_upper or cat == "bags":
            return "bags", subcat or "bags"
        if "_MOUNT_" in uid_upper or cat == "mounts":
            return "mounts", subcat or "mount"

        # Exact Refined & Raw Resources (without equipment prefix)
        if re.match(r"^T\d+_(?:PLANKS|METALBAR|BAR|LEATHER|CLOTH|STONEBLOCK)(?:_LEVEL\d+)?(?:@\d+)?$", uid_upper):
            return "crafting", "refinedresources"
        if re.match(r"^T\d+_(?:WOOD|ORE|HIDE|FIBER|ROCK|STONE)$", uid_upper):
            return "crafting", "resources"

        # Farming & Gathering
        if cat in ["farming", "gathering", "furniture", "vanity"]:
            return cat, subcat or "other"

        if cat in ["", "none", "other"]:
            if subcat in ["potions", "food", "tomes", "fish"]:
                return "consumables", subcat
            if subcat in ["tokens", "token"]:
                return "token", subcat
            if subcat in ["resources", "refinedresources"]:
                return "crafting", subcat

        return cat or "other", subcat or "other"

    def parse_items(self) -> list[dict]:
        """Parse raw items into normalized item and recipe records."""
        self.parsed_items = []
        self.parsed_recipes = []

        seen_item_ids = set()

        for raw_item in self.items_raw:
            if not isinstance(raw_item, dict):
                continue

            unique_name = raw_item.get("@uniquename", raw_item.get("UniqueName", ""))
            if not unique_name or unique_name in seen_item_ids:
                continue

            tier = self.get_tier(unique_name, raw_item)
            cat, subcat = self.normalize_category(
                unique_name,
                raw_item.get("@shopcategory", raw_item.get("shopcategory", "")),
                raw_item.get("@shopsubcategory1", raw_item.get("shopsubcategory1", "")),
            )
            weight = float(raw_item.get("@weight", 0) or 0)
            item_value = float(raw_item.get("@itemvalue", 0) or 0)
            max_stack = int(raw_item.get("@maxstacksize", 999) or 999)

            # Localized name lookup
            name = self.items_formatted.get(unique_name, "")
            if not name:
                name = unique_name.replace("_", " ").title()

            item = {
                "item_id": unique_name,
                "name": name,
                "tier": tier,
                "enchant": 0,
                "category": cat,
                "subcategory": subcat,
                "shop_category": cat,
                "shop_subcategory": subcat,
                "weight": weight,
                "max_stack": max_stack,
                "item_value": item_value,
                "is_craftable": False,
            }

            # Check for base crafting requirements
            craftingrequirements = raw_item.get("craftingrequirements", None)
            if craftingrequirements:
                item["is_craftable"] = True
                self._parse_recipe(unique_name, craftingrequirements, enchant_level=0)

            # Handle enchantment variants (.1, .2, .3, .4)
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
                        if ench_id in seen_item_ids:
                            continue

                        ench_name = self.items_formatted.get(ench_id, f"{name} .{ench_level}")
                        ench_value = float(ench.get("@itemvalue", item_value) or item_value)

                        ench_item = item.copy()
                        ench_item["item_id"] = ench_id
                        ench_item["name"] = ench_name
                        ench_item["enchant"] = ench_level
                        ench_item["item_value"] = ench_value

                        # Parse enchanted recipe if present
                        ench_craft = ench.get("craftingrequirements", None)
                        if ench_craft:
                            ench_item["is_craftable"] = True
                            self._parse_recipe(
                                ench_id,
                                ench_craft,
                                enchant_level=ench_level,
                                base_id=unique_name,
                            )

                        self.parsed_items.append(ench_item)
                        seen_item_ids.add(ench_id)

            self.parsed_items.append(item)
            seen_item_ids.add(unique_name)

        log.info(
            f"Parsed {len(self.parsed_items)} items and {len(self.parsed_recipes)} recipe ingredients."
        )
        return self.parsed_items

    def _parse_recipe(
        self,
        crafted_item_id: str,
        craft_req: dict | list,
        enchant_level: int = 0,
        base_id: str = "",
    ) -> None:
        """Parse crafting requirements into recipe ingredients with matching enchanted base equipment."""
        req_list = craft_req if isinstance(craft_req, list) else [craft_req]

        for req in req_list:
            if not isinstance(req, dict):
                continue

            resources = req.get("craftresource", [])
            if isinstance(resources, dict):
                resources = [resources]

            crafting_station = req.get("@craftingstation", "")
            nutrition = float(req.get("@amountofnutrition", 0) or 0)
            focus = float(req.get("@craftingfocus", 0) or 0)
            fame = float(req.get("@craftingfame", 0) or 0)

            for resource in resources:
                if not isinstance(resource, dict):
                    continue

                ingredient_id = resource.get("@uniquename", "")
                quantity = float(resource.get("@count", 1) or 1)

                if not ingredient_id:
                    continue

                # When crafting an enchanted item, match the base equipment ingredient enchantment
                if enchant_level > 0 and base_id:
                    if ingredient_id == base_id or (
                        any(
                            k in ingredient_id
                            for k in ["_CAPE", "_ARMOR_", "_HEAD_", "_SHOES_", "_BAG"]
                        )
                        and "@" not in ingredient_id
                        and not any(
                            x in ingredient_id
                            for x in ["ARTEFACT", "TOKEN", "QUESTITEM", "SIGIL", "_BP"]
                        )
                    ):
                        ingredient_id = f"{ingredient_id}@{enchant_level}"

                self.parsed_recipes.append(
                    {
                        "crafted_item_id": crafted_item_id,
                        "ingredient_item_id": ingredient_id,
                        "quantity": quantity,
                        "crafting_station": crafting_station,
                        "nutrition_cost": nutrition,
                        "focus_cost": focus,
                        "crafting_fame": fame,
                    }
                )

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
        """Cleans and populates items and recipes tables with validated official static data."""
        log.info("Populating database with validated official static data...")

        # 1. Clear old recipes and items
        db.query(Recipe).delete()
        db.query(Item).delete()
        db.commit()

        # 2. Bulk Insert Items
        seen_ids = set()
        item_objects = []
        for d in self.parsed_items:
            iid = d["item_id"]
            if iid not in seen_ids:
                seen_ids.add(iid)
                item_objects.append(Item(**d))

        if item_objects:
            db.bulk_save_objects(item_objects)
            db.commit()
        log.info(f"Inserted {len(item_objects)} validated official items into DB.")

        # 3. Bulk Insert Recipes
        recipe_objects = [Recipe(**d) for d in self.parsed_recipes]
        if recipe_objects:
            db.bulk_save_objects(recipe_objects)
            db.commit()
        log.info(f"Inserted {len(recipe_objects)} validated official recipe ingredients into DB.")

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
