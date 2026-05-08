from __future__ import annotations

from fastapi.testclient import TestClient
from main import app


def test_root_returns_json() -> None:
    with TestClient(app) as client:
        r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body.get("message") == "Albion Quant Trading System API"
    assert body.get("status") == "online"
