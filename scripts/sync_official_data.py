"""
Official Albion Online Static Data Synchronization Script.
Parses ao-bin-dumps static items and recipes and populates SQLite database.
"""

import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.logging import log
from app.db.session import get_db_session
from app.staticdata.parser import StaticDataParser
from sqlalchemy import text


def main():
    log.info("🚀 Starting Official Albion Online Static Data Synchronization...")
    parser = StaticDataParser()
    parser.load_raw_data()
    parser.parse_items()
    parser.save_parsed_data()

    with get_db_session() as db:
        parser.populate_database(db)

        # Run verification checks
        total_items = db.execute(text("SELECT count(*) FROM items")).scalar()
        total_recipes = db.execute(text("SELECT count(*) FROM recipes")).scalar()
        unique_crafted = db.execute(text("SELECT count(DISTINCT crafted_item_id) FROM recipes")).scalar()
        missing_names = db.execute(text("SELECT count(*) FROM items WHERE name IS NULL OR name = ''")).scalar()
        missing_tiers = db.execute(text("SELECT count(*) FROM items WHERE tier IS NULL")).scalar()

        print("\n" + "=" * 60)
        print("[AUDIT] DATABASE SYNCHRONIZATION AUDIT COMPLETE")
        print("=" * 60)
        print(f"[OK] Total Items Ingested: {total_items}")
        print(f"[OK] Total Recipe Ingredients Ingested: {total_recipes}")
        print(f"[OK] Unique Craftable Items: {unique_crafted}")
        print(f"[OK] Items Missing Names: {missing_names}")
        print(f"[INFO] Non-Tiered Vanity / Cosmetic Items: {missing_tiers}")

        # Categories Breakdown
        print("\n--- Categories Breakdown ---")
        cats = db.execute(text("SELECT category, count(*) FROM items GROUP BY category ORDER BY count(*) DESC")).fetchall()
        for cat, cnt in cats:
            print(f"  {str(cat):25}: {cnt}")

        # Tiers Breakdown
        print("\n--- Tiers Breakdown ---")
        tiers = db.execute(text("SELECT tier, count(*) FROM items GROUP BY tier ORDER BY tier ASC")).fetchall()
        for t, cnt in tiers:
            print(f"  Tier {str(t):10}: {cnt}")
        print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
