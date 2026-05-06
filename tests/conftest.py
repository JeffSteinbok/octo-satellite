import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    """Provide a test client with clean (no-secret) config."""
    monkeypatch.delenv("OCTO_SHARED_SECRET", raising=False)
    import octo_satellite.auth
    import octo_satellite.config
    import octo_satellite.main

    importlib.reload(octo_satellite.config)
    importlib.reload(octo_satellite.auth)
    importlib.reload(octo_satellite.main)
    return TestClient(octo_satellite.main.app)
