from datetime import datetime
from shared.domain.signal import Signal
from shared.domain.opportunity import Opportunity

def test_opportunity_creation():
    sig = Signal(
        item_id="T8_HEAD_CLOTH",
        city="Bridgewatch",
        timestamp=datetime.now(),
        signal_type="spread_anomaly",
        strength=2.5
    )
    opp = Opportunity(
        signal=sig,
        vwap_estimation=1150.0,
        slippage=5.0,
        fill_probability=0.8,
        transport_cost=50.0,
        estimated_profit=100.0
    )
    assert opp.signal.item_id == "T8_HEAD_CLOTH"
    assert opp.fill_probability == 0.8
