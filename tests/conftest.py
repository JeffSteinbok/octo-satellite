import importlib

import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    """Provide a test client with clean (no-secret) config."""
    monkeypatch.delenv("OCTO_SHARED_SECRET", raising=False)
    import config, auth, main
    importlib.reload(config)
    importlib.reload(auth)
    importlib.reload(main)
    return TestClient(main.app)
