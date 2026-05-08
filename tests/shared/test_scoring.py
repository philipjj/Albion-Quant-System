from datetime import datetime
from shared.domain.signal import Signal
from shared.domain.opportunity import Opportunity
from shared.domain.alpha import Alpha
from shared.domain.scoring import derive_opportunity, derive_alpha

def test_derive_opportunity():
    sig = Signal(
        item_id="T8_HEAD_CLOTH",
        city="Bridgewatch",
        timestamp=datetime.now(),
        signal_type="spread_anomaly",
        strength=2.5
    )
    market_data = {
        "vwap_estimation": 1150.0,
        "slippage": 5.0,
        "daily_volume": 100,
        "estimated_margin": 20.0,
        "source_city": "Bridgewatch",
        "destination_city": "Caerleon",
        "item_weight": 0.5,
        "estimated_profit": 100.0
    }
    opp = derive_opportunity(sig, market_data)
    assert isinstance(opp, Opportunity)
    assert opp.signal == sig
    assert opp.fill_probability > 0
    assert opp.transport_cost > 0

def test_derive_alpha():
    sig = Signal(
        item_id="T8_HEAD_CLOTH",
        city="Bridgewatch",
        timestamp=datetime.now(),
        signal_type="spread_anomaly",
        strength=2.5,
        metadata={"data_age_seconds": 60}
    )
    opp = Opportunity(
        signal=sig,
        vwap_estimation=1150.0,
        slippage=5.0,
        fill_probability=0.8,
        transport_cost=50.0,
        estimated_profit=1000.0
    )
    alpha = derive_alpha(opp)
    assert isinstance(alpha, Alpha)
    assert alpha.opportunity == opp
    assert alpha.expected_value > 0
