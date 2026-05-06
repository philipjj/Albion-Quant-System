from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.mark.integration
def test_api_smoke_sequence() -> None:
    """Light integration: multiple endpoints on one app instance."""
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/status").status_code == 200
        assert client.get("/docs").status_code == 200
