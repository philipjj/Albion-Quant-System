"""
Tests for regime classifier.
"""
from app.regime.classifier import RegimeClassifier
import pytest

def test_adversarial_regime():
    classifier = RegimeClassifier()
    # Mock data that triggers manipulation
    snapshots = [
        {"bids": [(100.0, 10.0)], "asks": [(101.0, 10.0)]},
        {"bids": [(100.0, 1000.0)], "asks": [(101.0, 10.0)]},
        {"bids": [(100.0, 10.0)], "asks": [(101.0, 10.0)]},
    ]
    assert classifier.classify(prices=[100.0, 101.0, 100.0], volumes=[1000.0], snapshots=snapshots) == "Adversarial"

def test_illiquid_regime():
    classifier = RegimeClassifier()
    assert classifier.classify(prices=[100.0, 101.0, 100.0], volumes=[10.0], snapshots=[]) == "Illiquid"

def test_trending_regime():
    classifier = RegimeClassifier()
    assert classifier.classify(prices=[100.0, 102.0, 105.0], volumes=[1000.0], snapshots=[]) == "Trending"

def test_stable_regime():
    classifier = RegimeClassifier()
    assert classifier.classify(prices=[100.0, 101.0, 100.0], volumes=[1000.0], snapshots=[]) == "Stable"
