from datetime import datetime
from shared.domain.signal import Signal

def test_signal_creation():
    sig = Signal(
        item_id="T8_HEAD_CLOTH",
        city="Bridgewatch",
        timestamp=datetime.now(),
        signal_type="spread_anomaly",
        strength=2.5,
        metadata={"spread_pct": 0.55}
    )
    assert sig.item_id == "T8_HEAD_CLOTH"
    assert sig.signal_type == "spread_anomaly"
