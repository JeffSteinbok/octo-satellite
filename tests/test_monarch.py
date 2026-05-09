"""Tests for Monarch Money router endpoints."""

from unittest.mock import AsyncMock, patch

MOCK_ACCOUNTS = {
    "Investments": {
        "total": 100000.0,
        "accounts": [
            {
                "name": "Brokerage",
                "balance": 100000.0,
                "institution": "Fidelity",
                "last_updated": "2026-05-09T17:00:00+00:00",
            }
        ],
    }
}

MOCK_SYNC_STATUS = {
    "accounts": [
        {
            "id": "123",
            "name": "Checking",
            "institution": "Chase",
            "institution_status": "HEALTHY",
            "last_synced": "2026-05-09T17:00:00+00:00",
            "sync_disabled": False,
            "update_required": False,
            "disconnected_at": None,
        },
        {
            "id": "456",
            "name": "Savings",
            "institution": "Chase",
            "institution_status": "HEALTHY",
            "last_synced": "2026-05-09T16:00:00+00:00",
            "sync_disabled": False,
            "update_required": False,
            "disconnected_at": None,
        },
    ]
}

MOCK_NET_WORTH = {
    "net_worth": 250000.0,
    "as_of": "2026-05-09",
}

MOCK_SPENDING = {
    "period_start": "2026-02-09",
    "period_end": "2026-05-09",
    "totals": {
        "income": 15000.0,
        "expenses": -10000.0,
        "savings": 5000.0,
        "savings_rate": 0.33,
    },
    "income_by_category": [{"category": "Salary", "amount": 15000.0}],
    "expenses_by_category": [{"category": "Housing", "amount": -5000.0}],
}


# -- Health --


@patch("octo_satellite.routers.monarch.monarch_session")
def test_monarch_health_authenticated(mock_session, client):
    mock_session.check_auth = AsyncMock(return_value={"authenticated": True})
    resp = client.get("/monarch/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "monarch"
    assert data["authenticated"] is True


@patch("octo_satellite.routers.monarch.monarch_session")
def test_monarch_health_unauthenticated(mock_session, client):
    mock_session.check_auth = AsyncMock(return_value={"authenticated": False})
    resp = client.get("/monarch/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["authenticated"] is False


# -- Sync Status --


@patch("octo_satellite.routers.monarch.monarch_session")
def test_sync_status_success(mock_session, client):
    mock_session.get_sync_status = AsyncMock(return_value=MOCK_SYNC_STATUS)
    resp = client.get("/monarch/sync-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "monarch"
    assert len(data["accounts"]) == 2
    assert data["accounts"][0]["institution_status"] == "HEALTHY"
    assert data["accounts"][0]["last_synced"] is not None


@patch("octo_satellite.routers.monarch.monarch_session")
def test_sync_status_expired_session(mock_session, client):
    mock_session.get_sync_status = AsyncMock(return_value=None)
    resp = client.get("/monarch/sync-status")
    assert resp.status_code == 401


# -- Refresh --


@patch("octo_satellite.routers.monarch.monarch_session")
def test_refresh_success(mock_session, client):
    mock_session.refresh_accounts = AsyncMock(
        return_value={"refresh_requested": True, "account_count": 5}
    )
    resp = client.post("/monarch/refresh")
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "monarch"
    assert data["refresh_requested"] is True
    assert data["account_count"] == 5


@patch("octo_satellite.routers.monarch.monarch_session")
def test_refresh_expired_session(mock_session, client):
    mock_session.refresh_accounts = AsyncMock(return_value=None)
    resp = client.post("/monarch/refresh")
    assert resp.status_code == 401


# -- Accounts --


@patch("octo_satellite.routers.monarch.monarch_session")
def test_get_accounts_success(mock_session, client):
    mock_session.get_accounts = AsyncMock(return_value=MOCK_ACCOUNTS)
    resp = client.get("/monarch/accounts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "monarch"
    assert "Investments" in data["accounts"]
    assert data["accounts"]["Investments"]["total"] == 100000.0


@patch("octo_satellite.routers.monarch.monarch_session")
def test_get_accounts_expired_session(mock_session, client):
    mock_session.get_accounts = AsyncMock(return_value=None)
    resp = client.get("/monarch/accounts")
    assert resp.status_code == 401


# -- Net Worth --


@patch("octo_satellite.routers.monarch.monarch_session")
def test_get_net_worth_success(mock_session, client):
    mock_session.get_net_worth = AsyncMock(return_value=MOCK_NET_WORTH)
    resp = client.get("/monarch/net-worth")
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "monarch"
    assert data["net_worth"] == 250000.0
    assert data["as_of"] == "2026-05-09"


@patch("octo_satellite.routers.monarch.monarch_session")
def test_get_net_worth_expired_session(mock_session, client):
    mock_session.get_net_worth = AsyncMock(return_value=None)
    resp = client.get("/monarch/net-worth")
    assert resp.status_code == 401


# -- Spending --


@patch("octo_satellite.routers.monarch.monarch_session")
def test_get_spending_success(mock_session, client):
    mock_session.get_spending = AsyncMock(return_value=MOCK_SPENDING)
    resp = client.get("/monarch/spending?months=3")
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "monarch"
    assert data["totals"]["income"] == 15000.0
    assert len(data["expenses_by_category"]) == 1


@patch("octo_satellite.routers.monarch.monarch_session")
def test_get_spending_expired_session(mock_session, client):
    mock_session.get_spending = AsyncMock(return_value=None)
    resp = client.get("/monarch/spending")
    assert resp.status_code == 401
