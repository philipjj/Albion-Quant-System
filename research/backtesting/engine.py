"""
Backtesting Engine.
Runs strategies over historical data.
"""
from datetime import datetime
from typing import Dict, Any
from research.replay.engine import ReplayEngine

class Strategy:
    """Base class for strategies."""
    def on_data(self, event: Dict[str, Any], engine: Any):
        """Called on each market event."""
        pass

class BacktestEngine:
    """
    Runs a backtest by replaying data and calling a strategy.
    Maintains portfolio state.
    """
    def __init__(
        self,
        replay_engine: Any,
        strategy: Strategy,
        initial_cash: float = 10000.0
    ):
        self.replay_engine = replay_engine
        self.strategy = strategy
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.positions: Dict[str, float] = {}
        
    def execute_order(
        self,
        item_id: str,
        quantity: float,
        price: float,
        side: str
    ):
        """
        Simulates execution of an order.
        Updates cash and positions.
        """
        cost = quantity * price
        
        if side == "buy":
            if self.cash >= cost:
                self.cash -= cost
                self.positions[item_id] = self.positions.get(item_id, 0.0) + quantity
            else:
                # Insufficient funds
                pass
        elif side == "sell":
            current_pos = self.positions.get(item_id, 0.0)
            if current_pos >= quantity:
                self.cash += cost
                self.positions[item_id] = current_pos - quantity
            else:
                # Insufficient position
                pass
                
    def run(
        self,
        start_time: datetime,
        end_time: datetime
    ) -> Dict[str, Any]:
        """
        Runs the backtest.
        """
        total_events = 0
        equity_curve = [self.cash]
        
        # Iterate over data
        for event in self.replay_engine.replay_iterator(start_time, end_time):
            total_events += 1
            self.strategy.on_data(event, self)
            equity_curve.append(self.cash)
            
        pnl = self.cash - self.initial_cash
        
        # Calculate returns for Sharpe
        returns = []
        for i in range(1, len(equity_curve)):
            prev = equity_curve[i-1]
            if prev > 0:
                returns.append((equity_curve[i] - prev) / prev)
            else:
                returns.append(0.0)
                
        from research.diagnostics.metrics import calculate_sharpe_ratio, calculate_max_drawdown
        
        sharpe = calculate_sharpe_ratio(returns)
        mdd = calculate_max_drawdown(equity_curve)
        
        return {
            "total_events": total_events,
            "cash": self.cash,
            "pnl": pnl,
            "sharpe_ratio": sharpe,
            "max_drawdown": mdd,
            "status": "completed"
        }
