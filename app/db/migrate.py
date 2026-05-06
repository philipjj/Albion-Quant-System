import sqlite3

from app.core.config import DATA_DIR


def migrate():
    db_path = DATA_DIR / "albion_quant.db"

    if not db_path.exists():
        print(f"Database not found at {db_path.absolute()}. Please run 'python main.py --init' first.")
        return

    print(f"Migrating database: {db_path.absolute()}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    new_columns = [
        ("journal_profit", "FLOAT DEFAULT 0.0"),
        ("daily_volume", "INTEGER DEFAULT 0"),
        ("ingredients_json", "TEXT"),
        ("volume_source", "VARCHAR(32) DEFAULT 'ESTIMATED'"),
        ("safe_limit", "INTEGER DEFAULT 1"),
        ("current_supply", "INTEGER DEFAULT 0"),
        ("market_gap", "INTEGER DEFAULT 0"),
        ("expected_hourly_profit", "FLOAT DEFAULT 0.0"),
        ("ev_score", "FLOAT DEFAULT 0.0"),
        ("volatility", "FLOAT DEFAULT 0.0"),
        ("persistence", "INTEGER DEFAULT 1"),
    ]

    tables = ["arbitrage_opportunities", "crafting_opportunities"]

    for table in tables:
        print(f"Checking table: {table}")
        cursor.execute(f"PRAGMA table_info({table})")
        columns = [col[1] for col in cursor.fetchall()]

        for col_name, col_type in new_columns:
            if col_name not in columns:
                print(f"Adding column '{col_name}' to {table}...")
                try:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
                except sqlite3.OperationalError as e:
                    print(f"Error adding {col_name}: {e}")
            else:
                print(f"Column '{col_name}' already exists in {table}.")

    conn.commit()
    conn.close()
    print("Migration complete. The system is now ready.")

if __name__ == "__main__":
    migrate()
