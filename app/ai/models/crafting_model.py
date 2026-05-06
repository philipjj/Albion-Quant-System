import lightgbm as lgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
import pandas as pd
import numpy as np
import joblib
import os

class CraftingModel:
    """
    Predicts crafting saturation (e.g. margin drops because of oversupply).
    """
    def __init__(self, model_path='data/models/crafting_model.pkl'):
        self.model_path = model_path
        self.model = None
        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)

    def train(self, df: pd.DataFrame):
        """Train the crafting saturation model."""
        if df.empty:
            raise ValueError("Training dataframe is empty.")
            
        features = [
            'sell_price', 'buy_price', 'sell_sma_3', 'sell_sma_7', 
            'price_volatility', 'spread_pct', 'volume', 
            'killboard_usage', 'patch_impact', 'city_supply'
        ]
        
        # Define target: 1 if spread_pct is going very low or city_supply is massive (proxy for saturation)
        # For our mock features, we will define saturation as high supply + dropping target price
        df['is_saturated'] = ((df['city_supply'] > 300) & (df['target_price_movement'] == 0)).astype(int)
        
        X = df[features]
        y = df['is_saturated']
        
        if len(np.unique(y)) < 2:
            print("[CraftingModel] Not enough class variance to train. Skipping.")
            return

        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
        
        self.model = lgb.LGBMClassifier(n_estimators=100, learning_rate=0.05, random_state=42)
        self.model.fit(X_train, y_train)
        
        preds = self.model.predict(X_test)
        acc = accuracy_score(y_test, preds)
        
        print(f"[LightGBM] Crafting Saturation Model trained. Accuracy: {acc:.2f}")
        self.save()

    def predict(self, df: pd.DataFrame) -> pd.Series:
        if self.model is None:
            self.load()
            
        features = [
            'sell_price', 'buy_price', 'sell_sma_3', 'sell_sma_7', 
            'price_volatility', 'spread_pct', 'volume', 
            'killboard_usage', 'patch_impact', 'city_supply'
        ]
        
        return self.model.predict(df[features])
        
    def save(self):
        joblib.dump(self.model, self.model_path)
        
    def load(self):
        if os.path.exists(self.model_path):
            self.model = joblib.load(self.model_path)
        else:
            raise FileNotFoundError(f"Model file not found at {self.model_path}")
