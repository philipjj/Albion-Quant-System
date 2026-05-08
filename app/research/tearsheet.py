"""
Tearsheet Generator.
Calculates performance metrics for a backtest.
"""
from typing import List, Dict

def generate_tearsheet(trades: List[Dict[str, any]], initial_equity: float, final_equity: float) -> Dict[str, any]:
    """
    Calculates basic performance metrics.
    """
    total_return = (final_equity - initial_equity) / initial_equity
    
    return {
        "initial_equity": initial_equity,
        "final_equity": final_equity,
        "total_return": total_return,
        "total_trades": len(trades)
    }
