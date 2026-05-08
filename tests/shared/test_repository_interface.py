import pytest
from abc import ABC
from shared.domain.repository import IMarketDataRepository

def test_interface_is_abstract():
    # Verify that we cannot instantiate the abstract class
    with pytest.raises(TypeError):
        IMarketDataRepository()

def test_interface_has_required_methods():
    # Verify that the required methods are defined as abstract
    assert "save_snapshots" in IMarketDataRepository.__abstractmethods__
    assert "get_latest_snapshot" in IMarketDataRepository.__abstractmethods__
