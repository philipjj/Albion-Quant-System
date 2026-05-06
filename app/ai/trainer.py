import pandas as pd
from app.db.session import get_db_session
from app.db.models import Item
from app.ai.features import FeatureEngineer
from app.ai.models.price_model import PriceModel
from app.ai.models.demand_model import DemandModel
from app.ai.models.crafting_model import CraftingModel
from app.ai.models.meta_model import MetaModel
import os

class AITrainer:
    """
    Orchestrates data fetching, feature engineering, and model training.
    """
    def __init__(self):
        self.fe = FeatureEngineer()
        self.price_model = PriceModel()
        self.demand_model = DemandModel()
        self.crafting_model = CraftingModel()
        self.meta_model = MetaModel()

    def build_dataset(self, city: str = "Caerleon", limit_items: int = 50) -> pd.DataFrame:
        """
        Builds a comprehensive dataset for training by combining multiple items.
        """
        print(f"Building dataset for city: {city} (limit: {limit_items} items)...")
        
        with get_db_session() as db:
            items = db.query(Item.item_id).limit(limit_items).all()
            
        all_features = []
        for (item_id,) in items:
            df = self.fe.build_features(item_id, city)
            if df is not None and not df.empty:
                # Add item_id context if needed for global models, though we drop it for training
                df['item_id'] = item_id 
                all_features.append(df)
                
        if not all_features:
            print("No data available to build dataset.")
            return pd.DataFrame()
            
        full_df = pd.concat(all_features)
        print(f"Dataset built: {len(full_df)} rows.")
        return full_df

    def train_all(self):
        """Train all models using available data."""
        # We can train on one main city or concatenate multiple
        df = self.build_dataset(city="Caerleon", limit_items=100)
        
        if df.empty or len(df) < 50:
            print("Not enough data to train models. Need more historical snapshots.")
            return
            
        print("--- Training Price Model ---")
        self.price_model.train(df)
        
        print("\n--- Training Demand Model ---")
        self.demand_model.train(df)
        
        print("\n--- Training Crafting Saturation Model ---")
        self.crafting_model.train(df)
        
        print("\n--- Training Meta Shifts Model ---")
        self.meta_model.train(df)
        
        print("\n✅ All AI models trained successfully.")

if __name__ == "__main__":
    trainer = AITrainer()
    trainer.train_all()
