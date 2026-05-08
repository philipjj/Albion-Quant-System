"""
Tests for manipulation detector.
"""
from app.regime.manipulation import detect_manipulation
import pytest

def test_manipulation_detected():
    # Large order placed and removed quickly
    snapshots = [
        {"bids": [(100.0, 10.0)], "asks": [(101.0, 10.0)]},
        {"bids": [(100.0, 1000.0)], "asks": [(101.0, 10.0)]},  # Spoof bid!
        {"bids": [(100.0, 10.0)], "asks": [(101.0, 10.0)]},   # Spoof removed!
    ]
    assert detect_manipulation(snapshots) == True

def test_no_manipulation():
    snapshots = [
        {"bids": [(100.0, 10.0)], "asks": [(101.0, 10.0)]},
        {"bids": [(100.0, 12.0)], "asks": [(101.0, 10.0)]},
        {"bids": [(100.0, 11.0)], "asks": [(101.0, 11.0)]},
    ]
    assert detect_manipulation(snapshots) == False
