from pydantic import BaseModel

from app.shared.domain.signal import Signal


class Opportunity(BaseModel):
    signal: Signal
    vwap_estimation: float
    slippage: float
    fill_probability: float
    transport_cost: float
    estimated_profit: float
