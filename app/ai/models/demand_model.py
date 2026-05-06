import os

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split


class DemandModel:
    """
    Predicts sudden demand spikes using RandomForest.
    We classify a 'spike' as price going up significantly or volume increasing.
    """
    def __init__(self, model_path='data/models/demand_model.pkl'):
        self.model_path = model_path
        self.model = None
        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)

    def train(self, df: pd.DataFrame):
        """Train the demand spike model."""
        if df.empty:
            raise ValueError("Training dataframe is empty.")

        features = [
            'sell_price', 'buy_price', 'sell_sma_3', 'sell_sma_7',
            'price_volatility', 'spread_pct', 'volume',
            'killboard_usage', 'patch_impact', 'city_supply'
        ]

        # Define target: 1 if target_price_movement == 1 and spread < 5% (high demand, low supply), else 0
        df['is_demand_spike'] = ((df['target_price_movement'] == 1) & (df['spread_pct'] < 5.0)).astype(int)

        X = df[features]
        y = df['is_demand_spike']

        # If there are no spikes to train on or it's all spikes, just return
        if len(np.unique(y)) < 2:
            print("[DemandModel] Not enough class variance to train (all 0 or all 1). Skipping.")
            return

        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)

        self.model = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42)
        self.model.fit(X_train, y_train)

        # Evaluate
        preds = self.model.predict(X_test)
        acc = accuracy_score(y_test, preds)

        print(f"[RandomForest] Demand Model trained. Accuracy: {acc:.2f}")
        print(classification_report(y_test, preds, zero_division=0))
        self.save()

    def predict(self, df: pd.DataFrame) -> pd.Series:
        """Predict if there will be a demand spike."""
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
