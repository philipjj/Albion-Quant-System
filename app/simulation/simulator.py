"""
Execution Simulator.
Combines slippage, market impact, and matching to simulate execution.
"""
from typing import Dict
from app.simulation.slippage import calculate_slippage
from app.simulation.market_impact import calculate_impact
from app.simulation.matching_engine import match_order

class ExecutionSimulator:
    def simulate_execution(self, order_type: str, size: float, price: float, snapshot: Dict[str, any], daily_volume: float, volatility: float) -> Dict[str, any]:
        """
        Simulates execution with slippage and market impact.
        """
        # 1. Match order
        match_result = match_order(order_type, size, price, snapshot)
        
        executed_size = match_result['executed_size']
        if executed_size == 0:
            return match_result
            
        # 2. Calculate slippage
        depth = snapshot.get('ask_volume', 0) if order_type == "buy" else snapshot.get('bid_volume', 0)
        slippage = calculate_slippage(executed_size, depth, volatility)
        
        # 3. Calculate market impact
        impact = calculate_impact(executed_size, daily_volume)
        
        # Adjust price based on slippage and impact
        # Slippage increases buy price and decreases sell price
        # Impact also increases buy price and decreases sell price
        avg_price = match_result['avg_price']
        
        if order_type == "buy":
            final_price = avg_price * (1.0 + slippage + impact)
        else:
            final_price = avg_price * (1.0 - slippage - impact)
            
        return {
            "executed_size": executed_size,
            "avg_price": final_price,
            "remaining_size": match_result['remaining_size'],
            "slippage": slippage,
            "market_impact": impact
        }
