"""
Script to initialize the database (create tables and hypertables).
Run this after updating DATABASE_URL in .env.
"""
import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.db.session import init_db

def main():
    print("Initializing database...")
    try:
        init_db()
        print("✅ Database initialization complete!")
    except Exception as e:
        print(f"❌ Error initializing database: {e}")
        print("\nPlease check your DATABASE_URL in .env and ensure Postgres is running.")

if __name__ == "__main__":
    main()
