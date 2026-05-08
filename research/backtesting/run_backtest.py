"""
Run Backtest on Real Data.
"""
from research.backtesting.engine import BacktestEngine
from research.backtesting.strategy import SimpleArbitrageStrategy
from research.replay.engine import ReplayEngine
from datetime import datetime

def main():
    print("Initializing Replay Engine...")
    # Use real DB
    replay_engine = ReplayEngine(source="db", db_path="data/albion_quant.db")
    
    strategy = SimpleArbitrageStrategy()
    
    print("Initializing Backtest Engine...")
    backtester = BacktestEngine(replay_engine=replay_engine, strategy=strategy, initial_cash=100000.0)
    
    start_time = datetime(2026, 5, 7, 12, 0, 0)
    end_time = datetime(2026, 5, 7, 13, 0, 0)
    
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
