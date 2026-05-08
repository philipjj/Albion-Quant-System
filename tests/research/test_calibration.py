"""
Tests for Calibration Framework.
"""
from research.calibration.validator import ProbabilityCalibrator
import pytest

def test_brier_score():
    calibrator = ProbabilityCalibrator()
    
    # Perfect predictions
    predictions = [1.0, 0.0, 1.0, 0.0]
    outcomes = [1, 0, 1, 0]
    assert calibrator.calculate_brier_score(predictions, outcomes) == 0.0
    
    # Perfect wrong predictions
    predictions = [0.0, 1.0, 0.0, 1.0]
    outcomes = [1, 0, 1, 0]
    assert calibrator.calculate_brier_score(predictions, outcomes) == 1.0
    
    # Mixed
    predictions = [0.5, 0.5, 0.5, 0.5]
    outcomes = [1, 0, 1, 0]
    assert calibrator.calculate_brier_score(predictions, outcomes) == 0.25

def test_calibration_error():
    calibrator = ProbabilityCalibrator()
    
    predictions = [0.8, 0.8, 0.8, 0.8]
    outcomes = [1, 1, 1, 0]  # 3/4 = 0.75 realized
    
    # Expected: 0.8, Realized: 0.75
    # Error should be around |0.8 - 0.75| = 0.05
    error = calibrator.calculate_calibration_error(predictions, outcomes, bins=1)
    assert pytest.approx(error, 0.01) == 0.05
