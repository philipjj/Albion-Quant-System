from app.core.validators import detect_anomaly

def test_detect_anomaly_missing_history():
    # Should flag as anomaly if no historical data is present (or zero)
    assert detect_anomaly(1000, None) is True
    assert detect_anomaly(1000, 0) is True

def test_detect_anomaly_no_spike():
    # 1000 vs 900 -> 11% deviation -> False
    assert detect_anomaly(1000, 900) is False
    
    # 1000 vs 200 -> 400% deviation -> False
    assert detect_anomaly(1000, 200) is False

def test_detect_anomaly_spike():
    # 10000 vs 1000 -> 900% deviation -> True
    assert detect_anomaly(10000, 1000) is True
    
    # 1 vs 1000 -> 99.9% deviation -> False (Wait, 1 - 1000 = 999 / 1000 = 0.999 deviation, which is < 5.0)
    assert detect_anomaly(1, 1000) is False
