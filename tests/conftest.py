"""
Pytest configuration and test isolation fixtures for Albion Quant System (AQS).
"""
import os
import pytest
from app.core.config import settings
from app.core import state

# Disable background workers during test runs
os.environ["DISABLE_BACKGROUND_TASKS"] = "true"


@pytest.fixture(autouse=True)
def setup_test_environment(monkeypatch):
    """Ensure tests run with isolated settings and enabled alerts where necessary."""
    old_alerts = settings.discord_alerts_enabled
    old_state_alerts = getattr(state, "discord_alerts_enabled", True)

    monkeypatch.setattr(settings, "discord_alerts_enabled", True)
    monkeypatch.setattr(state, "discord_alerts_enabled", True)

    yield

    monkeypatch.setattr(settings, "discord_alerts_enabled", old_alerts)
    monkeypatch.setattr(state, "discord_alerts_enabled", old_state_alerts)
