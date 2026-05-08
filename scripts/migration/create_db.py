"""
Script to create the database and enable TimescaleDB extension.
"""
import sys
import os
from sqlalchemy import create_engine, text

def main():
    # Connect to the default 'postgres' database to create 'albion_quant'
    url = "postgresql://postgres:Jockluak0@localhost:5432/postgres"
    print(f"Connecting to {url} to create database...")
    
    try:
        engine = create_engine(url, isolation_level="AUTOCOMMIT")
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1 FROM pg_database WHERE datname='albion_quant'"))
            if result.fetchone():
                print("Database 'albion_quant' already exists.")
            else:
                conn.execute(text("CREATE DATABASE albion_quant"))
                print("Database 'albion_quant' created successfully!")
                
    except Exception as e:
        print(f"Error creating database: {e}")
        return

    # Connect to 'albion_quant' to create extension
    url_aq = "postgresql://postgres:Jockluak0@localhost:5432/albion_quant"
    print(f"\nConnecting to {url_aq} to create extension...")
    try:
        engine_aq = create_engine(url_aq, isolation_level="AUTOCOMMIT")
        with engine_aq.connect() as conn:
            print("Trying to create extension timescaledb...")
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;"))
            print("Extension timescaledb verified/created successfully!")
    except Exception as e:
        print(f"Error creating extension: {e}")
        print("\nNote: If you are using vanilla PostgreSQL, you may need to install the TimescaleDB extension package.")

if __name__ == "__main__":
    main()
