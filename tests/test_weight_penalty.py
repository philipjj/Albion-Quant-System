from app.core.opportunity_engine import OpportunityScanner

def test_weight_penalty():
    scanner = OpportunityScanner()
    
    # Very heavy, low margin
    heavy_score = scanner._apply_weight_penalty(100.0, 100.0)
    assert heavy_score == 40.0 # 100 / 250 = 0.4 penalty -> 100 * 0.4 = 40
    
    # Mild penalty
    mild_score = scanner._apply_weight_penalty(100.0, 300.0)
    assert mild_score == 80.0
    
    # Neutral
    neutral_score = scanner._apply_weight_penalty(100.0, 600.0)
    assert neutral_score == 100.0
    
    # Bonus
    bonus_score = scanner._apply_weight_penalty(100.0, 1500.0)
    assert round(bonus_score, 2) == 110.0
