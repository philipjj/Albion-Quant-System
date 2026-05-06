from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import and_, select

from app.db.models import MarketHistory, MarketSnapshot
from app.db.session import get_db_session


class FeatureEngineer:
    """
    Extracts and engineers features for the AI Layer.
    Handles price history, volume, spread, supply, and external data.
    """

    def __init__(self):
        pass

    def get_price_history(self, item_id: str, city: str, days: int = 7) -> pd.DataFrame:
        """Fetch historical prices for an item in a specific city."""
        with get_db_session() as db:
            cutoff = datetime.utcnow() - timedelta(days=days)
            query = select(MarketSnapshot).where(
                and_(
                    MarketSnapshot.item_id == item_id,
                    MarketSnapshot.city == city,
                    MarketSnapshot.snapshot_at >= cutoff
                )
            ).order_by(MarketSnapshot.snapshot_at.asc())

            records = db.execute(query).scalars().all()

            if not records:
                return pd.DataFrame()

            data = [{
                'timestamp': r.snapshot_at,
                'sell_price': r.sell_price_min,
                'buy_price': r.buy_price_max
            } for r in records]

            df = pd.DataFrame(data)
            df.set_index('timestamp', inplace=True)
            return df

    def compute_spread_percentage(self, sell_price: float, buy_price: float) -> float:
        """Compute the spread percentage between sell and buy orders."""
        if not sell_price or not buy_price or sell_price <= 0:
            return 0.0
        return ((sell_price - buy_price) / sell_price) * 100

    def get_volume(self, item_id: str, city: str) -> int:
        """Retrieve verified 24h sales volume from collected market history."""
        with get_db_session() as db:
            cutoff = datetime.utcnow() - timedelta(hours=24)
            records = db.query(MarketHistory.item_count).filter(
                MarketHistory.item_id == item_id,
                MarketHistory.city == city,
                MarketHistory.timestamp >= cutoff,
            ).all()
            return int(sum(row[0] or 0 for row in records))

    def get_killboard_usage(self, item_id: str) -> float:
        """Return killboard usage when an external feed is integrated."""
        return 0.0

    def get_patch_changes(self, item_id: str) -> float:
        """
        Return impact score of recent patch changes using the Patch Diff Engine.
        """
        # In a full implementation, you would store the latest output of
        # PatchDiffEngine.generate_item_meta_scores() in the DB or in-memory cache
        # and look up the item_id here.
        # For now, we simulate finding the meta score.

        # simulated lookups from patch diff engine:
        if item_id == "T4_MAIN_SWORD":
            return 0.5583 # From our PatchDiffEngine massive buff
        if item_id == "T4_2H_BOW":
            return -0.9208 # From our PatchDiffEngine massive nerf

        return 0.0 # Unchanged item

    def get_city_supply(self, item_id: str, city: str) -> int:
        """Return active order supply when order-book collection is available."""
        return 0

    def build_features(self, item_id: str, city: str) -> pd.DataFrame | None:
        """
        Construct a complete feature vector for a given item and city.
        Combines history, spread, volume, and external signals.
        """
        history_df = self.get_price_history(item_id, city, days=14)
        if history_df.empty or len(history_df) < 5:
            return None

        # Time series features
        # Moving averages
        history_df['sell_sma_3'] = history_df['sell_price'].rolling(window=3, min_periods=1).mean()
        history_df['sell_sma_7'] = history_df['sell_price'].rolling(window=7, min_periods=1).mean()

        # Volatility
        history_df['price_volatility'] = history_df['sell_price'].rolling(window=7, min_periods=1).std().fillna(0)

        # Spread
        history_df['spread_pct'] = history_df.apply(
            lambda row: self.compute_spread_percentage(row['sell_price'], row['buy_price']),
            axis=1
        )

        # Add external features (mostly static or daily, mapping to latest)
        history_df['volume'] = self.get_volume(item_id, city)
        history_df['killboard_usage'] = self.get_killboard_usage(item_id)
        history_df['patch_impact'] = self.get_patch_changes(item_id)
        history_df['city_supply'] = self.get_city_supply(item_id, city)

        # Target creation (predicting next period's price or movement)
        history_df['target_sell_price'] = history_df['sell_price'].shift(-1)
        history_df['target_price_movement'] = (history_df['target_sell_price'] > history_df['sell_price']).astype(int)

        # Drop NaN targets (the last row)
        history_df.dropna(subset=['target_sell_price'], inplace=True)

        return history_df
