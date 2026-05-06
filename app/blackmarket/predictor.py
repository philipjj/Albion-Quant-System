import pandas as pd
from sqlalchemy import select

from app.blackmarket.tracker import BlackMarketTracker
from app.core.config import settings
from app.db.models import MarketPrice
from app.db.session import get_db_session


class BlackMarketPredictor:
    """
    Predicts the highest Black Market Return on Investment (ROI).
    Combines BM Tracker metrics (shortage, sink velocity) with Royal City prices
    to find the most profitable and safest transport/crafting opportunities to Caerleon.
    """
    def __init__(self):
        self.tracker = BlackMarketTracker()
        self.royal_cities = ["Martlock", "Lymhurst", "Bridgewatch", "Fort Sterling", "Thetford"]

    def find_highest_roi(self, top_n: int = 15) -> pd.DataFrame:
        """
        Calculates ROI for transporting goods from Royal Cities to the Black Market.
        Returns the top opportunities based on Profit Margin, adjusting for Shortage Level.
        """
        opportunities = []

        with get_db_session() as db:
            # 1. Get recent Black Market prices
            bm_query = select(MarketPrice).where(
                MarketPrice.city == "Black Market"
            ).order_by(MarketPrice.item_id, MarketPrice.fetched_at.desc())

            # Subquery or distinct might be better, but we'll do a simple latest-fetch in python for demo
            bm_records = db.execute(bm_query).scalars().all()

            latest_bm = {}
            for r in bm_records:
                if r.item_id not in latest_bm:
                    latest_bm[r.item_id] = r.buy_price_max

            if not latest_bm:
                return pd.DataFrame()

            # 2. Get recent Royal City prices (sell_price_min to buy from market)
            royal_query = select(MarketPrice).where(
                MarketPrice.city.in_(self.royal_cities)
            ).order_by(MarketPrice.item_id, MarketPrice.fetched_at.desc())

            royal_records = db.execute(royal_query).scalars().all()
            latest_royal = {}
            for r in royal_records:
                # Keep the absolute cheapest royal city price for each item
                if r.item_id not in latest_royal or r.sell_price_min < latest_royal[r.item_id]["price"]:
                    if r.sell_price_min > 0: # Avoid zero prices
                        latest_royal[r.item_id] = {"price": r.sell_price_min, "city": r.city}

            # 3. Calculate ROI and track metrics
            for item_id, bm_price in latest_bm.items():
                if item_id in latest_royal and bm_price > 0:
                    royal_price = latest_royal[item_id]["price"]
                    source_city = latest_royal[item_id]["city"]

                    # Calculate taxes (BM sales always pay sales tax, no setup fee for instant sell)
                    bm_tax = bm_price * settings.tax_rate
                    gross_profit = bm_price - royal_price - bm_tax
                    margin = (gross_profit / royal_price) * 100 if royal_price > 0 else 0

                    if margin > 5.0: # Minimum 5% margin to care
                        # Fetch BM specific metrics for risk assessment
                        metrics = self.tracker.analyze_item_metrics(item_id, days_back=3)

                        # High shortage = safer transport (BM will likely still be buying)
                        # High sink velocity = riskier (someone else might fulfill it before you arrive)
                        safety_score = metrics.get('shortage_level', 0.0) * 100 - (metrics.get('sink_velocity', 0.0) * 5)

                        opportunities.append({
                            "item_id": item_id,
                            "buy_city": source_city,
                            "buy_price": royal_price,
                            "bm_price": bm_price,
                            "profit": gross_profit,
                            "roi_margin": round(margin, 2),
                            "shortage_level": metrics.get('shortage_level', 0.0),
                            "safety_score": round(safety_score, 2)
                        })

        if not opportunities:
            return pd.DataFrame()

        df = pd.DataFrame(opportunities)

        # Sort by ROI Margin primarily, but also factor in safety
        df['weighted_score'] = df['roi_margin'] + (df['shortage_level'] * 10)
        df = df.sort_values(by='weighted_score', ascending=False).head(top_n)

        return df

    def print_top_roi(self):
        """Helper to print out the top BM ROI to console."""
        from rich.console import Console
        from rich.table import Table

        df = self.find_highest_roi(top_n=15)
        console = Console(force_terminal=True)

        if df.empty:
            console.print("[red]No Black Market opportunities found.[/red]")
            return

        table = Table(title="💀 BLACK MARKET TOP ROI 💀", show_lines=True)
        table.add_column("Item ID", style="cyan")
        table.add_column("Buy City", style="green")
        table.add_column("Cost", justify="right")
        table.add_column("BM Payout", justify="right")
        table.add_column("Profit", justify="right", style="bold green")
        table.add_column("ROI %", justify="right", style="bold")
        table.add_column("Shortage", justify="center")

        for _, row in df.iterrows():
            shortage_str = "High" if row['shortage_level'] > 0.7 else "Med" if row['shortage_level'] > 0.3 else "Low"
            table.add_row(
                row['item_id'][:25],
                row['buy_city'],
                f"{row['buy_price']:,.0f}",
                f"{row['bm_price']:,.0f}",
                f"{row['profit']:,.0f}",
                f"{row['roi_margin']}%",
                shortage_str
            )

        console.print(table)

if __name__ == "__main__":
    predictor = BlackMarketPredictor()
    predictor.print_top_roi()
