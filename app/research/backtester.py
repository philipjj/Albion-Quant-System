"""
Backtester.
Runs a strategy over historical data and evaluates performance.
"""
from typing import List, Dict
from app.simulation.simulator import ExecutionSimulator

class Backtester:
    def __init__(self, simulator: ExecutionSimulator, initial_equity: float = 1000000.0):
        self.simulator = simulator
        self.trades = []
        self.equity = initial_equity

    def run(self, strategy, historical_data: List[Dict[str, any]]):
        """
        Runs the strategy over historical data.
        historical_data is a list of snapshots.
        """
        for snapshot in historical_data:
            # 1. Get signal from strategy
            signal = strategy.evaluate(snapshot)
            
            if not signal:
                continue
                
            # 2. Simulate execution
            order_size = 100.0  # Fixed size for simplicity
            
            result = self.simulator.simulate_execution(
                order_type=signal.signal_type,
                size=order_size,
                price=snapshot.get('price', 0),
                snapshot=snapshot,
                daily_volume=snapshot.get('daily_volume', 1000.0),
                volatility=snapshot.get('volatility', 0.1)
            )
            
            if result['executed_size'] > 0:
                # Record trade
                self.trades.append({
                    "timestamp": snapshot.get('timestamp'),
                    "signal_type": signal.signal_type,
                    "size": result['executed_size'],
                    "price": result['avg_price'],
                    "slippage": result.get('slippage', 0),
                    "impact": result.get('market_impact', 0)
                })
                
                # Update equity
                cost = result['executed_size'] * result['avg_price']
                if signal.signal_type == "buy" or "buy" in signal.signal_type:
                    self.equity -= cost
                elif signal.signal_type == "sell" or "sell" in signal.signal_type:
                    self.equity += cost
                    
        return {
            "final_equity": self.equity,
            "total_trades": len(self.trades),
            "trades": self.trades
        }
