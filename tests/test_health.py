from unittest.mock import AsyncMock, patch


def test_root_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@patch("routers.amazon.amazon_session")
def test_amazon_health_authenticated(mock_session, client):
    mock_session.check_auth = AsyncMock(return_value={"authenticated": True, "name": "TestUser"})
    resp = client.get("/amazon/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "amazon"
    assert data["authenticated"] is True


@patch("routers.amazon.amazon_session")
def test_amazon_health_unauthenticated(mock_session, client):
    mock_session.check_auth = AsyncMock(return_value={"authenticated": False, "name": None})
    resp = client.get("/amazon/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["authenticated"] is False
