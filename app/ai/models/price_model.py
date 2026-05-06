import lightgbm as lgb
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, mean_absolute_error
import pandas as pd
import joblib
import os

class PriceModel:
    """
    Predicts future price movements using LightGBM and XGBoost.
    """
    def __init__(self, model_type='lightgbm', model_path='data/models/price_model.pkl'):
        self.model_type = model_type
        self.model_path = model_path
        self.model = None
        
        # Ensure model dir exists
        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)

    def train(self, df: pd.DataFrame):
        """Train the price prediction model."""
        if df.empty:
            raise ValueError("Training dataframe is empty.")
            
        features = [
            'sell_price', 'buy_price', 'sell_sma_3', 'sell_sma_7', 
            'price_volatility', 'spread_pct', 'volume', 
            'killboard_usage', 'patch_impact', 'city_supply'
        ]
        
        X = df[features]
        y = df['target_sell_price']
        
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
        
        if self.model_type == 'lightgbm':
            self.model = lgb.LGBMRegressor(n_estimators=100, learning_rate=0.1, random_state=42)
        elif self.model_type == 'xgboost':
            self.model = xgb.XGBRegressor(n_estimators=100, learning_rate=0.1, random_state=42)
        else:
            raise ValueError("Unsupported model type. Use 'lightgbm' or 'xgboost'.")
            
        self.model.fit(X_train, y_train)
        
        # Evaluate
        preds = self.model.predict(X_test)
        mse = mean_squared_error(y_test, preds)
        mae = mean_absolute_error(y_test, preds)
        
        print(f"[{self.model_type.upper()}] Price Model trained. MSE: {mse:.2f}, MAE: {mae:.2f}")
        self.save()

    def predict(self, df: pd.DataFrame) -> pd.Series:
        """Predict target sell price for new data."""
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
