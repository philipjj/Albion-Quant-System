from datetime import datetime
from shared.domain.signal import Signal
from shared.domain.opportunity import Opportunity
from shared.domain.alpha import Alpha

def test_alpha_creation():
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
    alpha = Alpha(
        opportunity=opp,
        expected_value=80.0,
        decay_risk=0.1,
        confidence=0.9
    )
    assert alpha.opportunity.signal.item_id == "T8_HEAD_CLOTH"
    assert alpha.expected_value == 80.0
