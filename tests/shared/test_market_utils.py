from shared.utils.market import calculate_rrr, calculate_blended_price

def test_calculate_rrr():
    # Test with default values
    rrr = calculate_rrr("Martlock", "hide", 4)
    # BASE_CITY_PRODUCTION_BONUS (18) + REFINING_SPECIALIZATION_BONUS (40) = 58
    # RRR = 1 - 1 / (1 + 58/100) = 1 - 1/1.58 = 0.36708...
    # The current implementation in market_utils.py rounds to 4 decimals.
    assert rrr == 0.3671

def test_calculate_blended_price():
    # Test normal blending
    price = calculate_blended_price(100.0, 80.0)
    # (100 * 0.7) + (80 * 0.3) = 70 + 24 = 94
    assert price == 94.0
    
    # Test high spread blending
    price = calculate_blended_price(100.0, 40.0)
    # Spread = (100 - 40)/100 = 0.6 > 0.5
    # (100 * 0.4) + (40 * 0.6) = 40 + 24 = 64
    assert price == 64.0
