from datetime import datetime
from pydantic import BaseModel

class MarketSnapshot(BaseModel):
    item_id: str
    city: str
    quality: int = 1
    timestamp: datetime
    
    best_bid: float
    best_ask: float
    
    bid_depth: int
    ask_depth: int
    
    spread: float
    midprice: float
    
    rolling_volume: int
    volatility: float
