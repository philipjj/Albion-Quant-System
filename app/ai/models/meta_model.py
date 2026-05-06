import os

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split


class MetaModel:
    """
    Predicts Meta Shifts using XGBoost.
    A meta shift implies sudden high usage in killboards combined with patch impact.
    """
    def __init__(self, model_path='data/models/meta_model.pkl'):
        self.model_path = model_path
        self.model = None
        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)

    def train(self, df: pd.DataFrame):
        """Train the meta shifts model."""
        if df.empty:
            raise ValueError("Training dataframe is empty.")

        features = [
            'sell_price', 'buy_price', 'sell_sma_3', 'sell_sma_7',
            'price_volatility', 'spread_pct', 'volume',
            'killboard_usage', 'patch_impact', 'city_supply'
        ]

        # Meta shift is likely if killboard usage is very high and patching happened
        df['is_meta_shift'] = ((df['killboard_usage'] > 0.8) | (df['patch_impact'] > 0)).astype(int)

        X = df[features]
        y = df['is_meta_shift']

        if len(np.unique(y)) < 2:
            print("[MetaModel] Not enough class variance to train. Skipping.")
            return

        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)

        self.model = xgb.XGBClassifier(n_estimators=100, learning_rate=0.05, random_state=42)
        self.model.fit(X_train, y_train)

        preds = self.model.predict(X_test)
        acc = accuracy_score(y_test, preds)

        print(f"[XGBoost] Meta Shift Model trained. Accuracy: {acc:.2f}")
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
