"""
Backtesting Engine.
Runs strategies over historical data.
"""
from datetime import datetime
from typing import Dict, Any
from research.replay.engine import ReplayEngine

class Strategy:
    """Base class for strategies."""
    def on_data(self, event: Dict[str, Any]):
        """Called on each market event."""
        pass

class BacktestEngine:
    """
    Runs a backtest by replaying data and calling a strategy.
    """
    def __init__(self, replay_engine: ReplayEngine, strategy: Strategy):
        self.replay_engine = replay_engine
        self.strategy = strategy
        
    def run(
        self,
        start_time: datetime,
        end_time: datetime
    ) -> Dict[str, Any]:
        """
        Runs the backtest.
        """
        total_events = 0
        
        # Iterate over data
        for event in self.replay_engine.replay_iterator(start_time, end_time):
            total_events += 1
            self.strategy.on_data(event)
            
        return {
            "total_events": total_events,
            "status": "completed"
        }
