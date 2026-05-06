import pandas as pd
from sqlalchemy import select, func, desc
from datetime import datetime, timedelta

from app.db.session import get_db_session
from app.db.models import Item, MarketSnapshot, MarketPrice
from app.ai.features import FeatureEngineer

class MetaAnalyzer:
    """
    Identifies the CURRENT meta by analyzing recent market activity
    and external usage signals (e.g. killboard presence).
    """
    def __init__(self):
        self.fe = FeatureEngineer()

    def get_current_meta(self, top_n: int = 20, category: str = None) -> list[dict]:
        """
        Determines the current meta items by computing a 'Meta Score'.
        Meta Score = (Normalized Volume * 0.4) + (Killboard Usage * 0.5) + (Price Momentum * 0.1)
        """
        meta_items = []
        
        with get_db_session() as db:
            # Base query for items
            query = select(Item)
            if category:
                query = query.where(Item.category == category)
                
            # For performance, maybe limit to items that are craftable or weapons/armor
            # In a real scenario, you'd filter out garbage tier items.
            query = query.where(Item.tier >= 4)
            
            items = db.execute(query).scalars().all()
            
            for item in items:
                # We use Caerleon as a benchmark city, or aggregate across cities
                city = "Caerleon" 
                
                # Fetch history for momentum
                history_df = self.fe.get_price_history(item.item_id, city, days=7)
                
                price_momentum = 0.0
                if not history_df.empty and len(history_df) >= 2:
                    old_price = history_df['sell_price'].iloc[0]
                    new_price = history_df['sell_price'].iloc[-1]
                    if old_price > 0:
                        price_momentum = ((new_price - old_price) / old_price)
                
                # Get usage and volume
                # Note: Currently these are stubbed in FeatureEngineer
                volume = self.fe.get_volume(item.item_id, city)
                killboard_usage = self.fe.get_killboard_usage(item.item_id)
                
                meta_items.append({
                    "item_id": item.item_id,
                    "name": item.name,
                    "tier": item.tier,
                    "category": item.category,
                    "volume": volume,
                    "killboard_usage": killboard_usage,
                    "price_momentum": price_momentum
                })
                
        if not meta_items:
            return []
            
        df = pd.DataFrame(meta_items)
        
        # Normalize volume to 0-1 range to match killboard_usage
        max_vol = df['volume'].max()
        if max_vol > 0:
            df['norm_volume'] = df['volume'] / max_vol
        else:
            df['norm_volume'] = 0.0
            
        # Cap price momentum so it doesn't skew everything (e.g. max 100% impact)
        df['norm_momentum'] = df['price_momentum'].clip(-1.0, 1.0)
        
        # Calculate Meta Score
        df['meta_score'] = (df['norm_volume'] * 0.4) + (df['killboard_usage'] * 0.5) + (df['norm_momentum'] * 0.1)
        
        # Sort and get top N
        df = df.sort_values(by='meta_score', ascending=False).head(top_n)
        
        # Convert to list of dicts
        return df.to_dict('records')

    def display_current_meta(self, top_n: int = 15):
        """Helper to print out the current meta in the console."""
        from rich.console import Console
        from rich.table import Table
        
        meta_results = self.get_current_meta(top_n=top_n)
        
        console = Console(force_terminal=True)
        table = Table(title="🔥 CURRENT ALBION META 🔥", show_lines=True)
        
        table.add_column("Rank", style="cyan")
        table.add_column("Item", style="white")
        table.add_column("Tier", justify="center")
        table.add_column("Category", style="dim")
        table.add_column("Meta Score", justify="right", style="bold green")
        table.add_column("Killboard Use", justify="right")
        table.add_column("Momentum", justify="right")
        
        for idx, row in enumerate(meta_results):
            table.add_row(
                f"#{idx+1}",
                row['name'],
                str(row['tier']),
                str(row['category']),
                f"{row['meta_score']:.3f}",
                f"{row['killboard_usage']:.2%}",
                f"{row['price_momentum']:+.1%}"
            )
            
        console.print(table)

if __name__ == "__main__":
    analyzer = MetaAnalyzer()
    analyzer.display_current_meta()
