"""
Capital Optimization.
Optimizes capital allocation across opportunities.
"""
from typing import List, Dict

class CapitalOptimizer:
    def optimize_capital(self, opportunities: List[Dict[str, any]], max_capital: float) -> List[Dict[str, any]]:
        """
        Allocates capital to opportunities with the highest ROI.
        opportunities is a list of dicts: {'item_id': str, 'profit': float, 'capital_required': float}
        """
        # Calculate ROI
        for opp in opportunities:
            if opp.get('capital_required', 0) == 0:
                opp['roi'] = float('inf')
            else:
                opp['roi'] = opp.get('profit', 0) / opp.get('capital_required', 0)
                
        # Sort by ROI descending
        sorted_opps = sorted(opportunities, key=lambda x: x.get('roi', 0), reverse=True)
        
        selected_opps = []
        current_capital = 0.0
        
        for opp in sorted_opps:
            if current_capital + opp.get('capital_required', 0) <= max_capital:
                selected_opps.append(opp)
                current_capital += opp.get('capital_required', 0)
                
        return selected_opps
