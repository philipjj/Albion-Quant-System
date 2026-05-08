"""
Run Backtest on Real Data.
"""
from research.backtesting.engine import BacktestEngine
from research.backtesting.strategy import SimpleArbitrageStrategy
from research.replay.engine import ReplayEngine
from datetime import datetime

import argparse

def main():
    parser = argparse.ArgumentParser(description="Run Backtest on Real Data")
    parser.add_argument("--db", type=str, default="data/albion_quant.db", help="Path to database")
    parser.add_argument("--start", type=str, default="2026-05-07 12:00:00", help="Start time (YYYY-MM-DD HH:MM:SS)")
    parser.add_argument("--end", type=str, default="2026-05-07 13:00:00", help="End time (YYYY-MM-DD HH:MM:SS)")
    args = parser.parse_args()

    print(f"Initializing Replay Engine with {args.db}...")
    replay_engine = ReplayEngine(source="db", db_path=args.db)
    
    strategy = SimpleArbitrageStrategy()
    
    print("Initializing Backtest Engine...")
    backtester = BacktestEngine(replay_engine=replay_engine, strategy=strategy, initial_cash=100000.0)
    
    start_time = datetime.strptime(args.start, "%Y-%m-%d %H:%M:%S")
    end_time = datetime.strptime(args.end, "%Y-%m-%d %H:%M:%S")
    
    print(f"Running backtest from {start_time} to {end_time}...")
    
    try:
        metrics = backtester.run(start_time, end_time)
        
        print("\n=== Backtest Results ===")
        for k, v in metrics.items():
            print(f"{k}: {v}")
            
        print(f"Final Cash: {backtester.cash}")
        print(f"Open Positions: {backtester.positions}")
        
    except Exception as e:
        print(f"Error running backtest: {e}")

if __name__ == "__main__":
    main()
