from shared.domain.signal import Signal
from pydantic import BaseModel

class Opportunity(BaseModel):
    signal: Signal
    vwap_estimation: float
    slippage: float
    fill_probability: float
    transport_cost: float
    estimated_profit: float
