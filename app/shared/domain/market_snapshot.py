from datetime import datetime

from pydantic import BaseModel


class MarketSnapshot(BaseModel):
    item_id: str
    city: str
    quality: int = 1
    timestamp: datetime

    best_bid: float
    best_ask: float

    bid_depth: int = 0
    ask_depth: int = 0

    spread: float = 0.0
    midprice: float = 0.0

    rolling_volume: int = 0
    volatility: float = 0.0

    sell_price_min_date: datetime | None = None
    buy_price_max_date: datetime | None = None
    data_age_seconds: float | None = 0.0
