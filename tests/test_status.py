from __future__ import annotations

from fastapi.testclient import TestClient
from main import app


def test_status_returns_shape() -> None:
    with TestClient(app) as client:
        r = client.get("/status")
    assert r.status_code == 200
    data = r.json()
    assert "database" in data
    assert "data_quality" in data
    assert "feature_gate" in data
    assert data["database"]["items"] is not None
    assert data["scheduler"] in ("running", "stopped")
