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


MOCK_NET_WORTH_HISTORY = {
    "net_worth": 250000.0,
    "as_of": "2026-05-09",
    "period_start": "2026-05-01",
    "period_end": "2026-05-09",
    "history": [
        {"date": "2026-05-01", "net_worth": 240000.0},
        {"date": "2026-05-09", "net_worth": 250000.0},
    ],
}


@patch("octo_satellite.routers.monarch.monarch_session")
def test_get_net_worth_date_range(mock_session, client):
    mock_session.get_net_worth = AsyncMock(return_value=MOCK_NET_WORTH_HISTORY)
    resp = client.get("/monarch/net-worth?start_date=2026-05-01&end_date=2026-05-09")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["history"]) == 2
    mock_session.get_net_worth.assert_called_once_with(
        start_date="2026-05-01", end_date="2026-05-09"
    )


@patch("octo_satellite.routers.monarch.monarch_session")
def test_get_net_worth_invalid_date(mock_session, client):
    mock_session.get_net_worth = AsyncMock(return_value=MOCK_NET_WORTH)
    resp = client.get("/monarch/net-worth?end_date=2026-13-01")
    assert resp.status_code == 422
    mock_session.get_net_worth.assert_not_called()


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


@patch("octo_satellite.routers.monarch.monarch_session")
def test_get_spending_date_range(mock_session, client):
    mock_session.get_spending = AsyncMock(return_value=MOCK_SPENDING)
    resp = client.get("/monarch/spending?start_date=2026-01-01&end_date=2026-03-31")
    assert resp.status_code == 200
    mock_session.get_spending.assert_called_once_with(
        months=3, start_date="2026-01-01", end_date="2026-03-31"
    )


@patch("octo_satellite.routers.monarch.monarch_session")
def test_get_spending_invalid_date(mock_session, client):
    mock_session.get_spending = AsyncMock(return_value=MOCK_SPENDING)
    resp = client.get("/monarch/spending?start_date=not-a-date")
    assert resp.status_code == 422
    mock_session.get_spending.assert_not_called()


@patch("octo_satellite.routers.monarch.monarch_session")
def test_get_spending_start_after_end(mock_session, client):
    mock_session.get_spending = AsyncMock(return_value=MOCK_SPENDING)
    resp = client.get("/monarch/spending?start_date=2026-05-01&end_date=2026-01-01")
    assert resp.status_code == 422
    mock_session.get_spending.assert_not_called()


# -- Merchants / Categories --

MOCK_CATEGORIES = {
    "categories": [
        {"id": "1", "name": "Airfare", "group": "Travel", "type": "expense"},
        {"id": "2", "name": "Travel", "group": "Travel", "type": "expense"},
    ]
}

MOCK_MERCHANTS = {
    "period_start": "2026-01-01",
    "period_end": "2026-12-31",
    "total_spent": -1200.0,
    "category": {"id": "2", "name": "Travel"},
    "merchants": [
        {"id": "m1", "name": "Delta", "logo_url": None, "amount": -800.0, "income": 0},
        {"id": "m2", "name": "Airbnb", "logo_url": None, "amount": -400.0, "income": 0},
    ],
}


@patch("octo_satellite.routers.monarch.monarch_session")
def test_get_categories_success(mock_session, client):
    mock_session.get_categories = AsyncMock(return_value=MOCK_CATEGORIES)
    resp = client.get("/monarch/categories")
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "monarch"
    assert len(data["categories"]) == 2
    assert data["categories"][1]["name"] == "Travel"


@patch("octo_satellite.routers.monarch.monarch_session")
def test_get_categories_expired_session(mock_session, client):
    mock_session.get_categories = AsyncMock(return_value=None)
    resp = client.get("/monarch/categories")
    assert resp.status_code == 401


@patch("octo_satellite.routers.monarch.monarch_session")
def test_get_merchants_success(mock_session, client):
    mock_session.get_merchant_spending = AsyncMock(return_value=MOCK_MERCHANTS)
    resp = client.get("/monarch/merchants")
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "monarch"
    assert data["merchants"][0]["name"] == "Delta"


@patch("octo_satellite.routers.monarch.monarch_session")
def test_get_merchants_by_category_and_range(mock_session, client):
    mock_session.get_merchant_spending = AsyncMock(return_value=MOCK_MERCHANTS)
    resp = client.get(
        "/monarch/merchants?category=Travel&start_date=2026-01-01&end_date=2026-12-31&limit=5"
    )
    assert resp.status_code == 200
    mock_session.get_merchant_spending.assert_called_once_with(
        months=3, start_date="2026-01-01", end_date="2026-12-31", category="Travel", limit=5
    )


@patch("octo_satellite.routers.monarch.monarch_session")
def test_get_merchants_unknown_category(mock_session, client):
    mock_session.get_merchant_spending = AsyncMock(
        return_value={"error": "category_not_found", "category": "Nope"}
    )
    resp = client.get("/monarch/merchants?category=Nope")
    assert resp.status_code == 404


@patch("octo_satellite.routers.monarch.monarch_session")
def test_get_merchants_invalid_date(mock_session, client):
    mock_session.get_merchant_spending = AsyncMock(return_value=MOCK_MERCHANTS)
    resp = client.get("/monarch/merchants?start_date=bad")
    assert resp.status_code == 422
    mock_session.get_merchant_spending.assert_not_called()


@patch("octo_satellite.routers.monarch.monarch_session")
def test_get_merchants_expired_session(mock_session, client):
    mock_session.get_merchant_spending = AsyncMock(return_value=None)
    resp = client.get("/monarch/merchants")
    assert resp.status_code == 401


# -- Investments --

MOCK_INVESTMENTS = {
    "accounts": [
        {
            "account_id": 123,
            "total_value": 50000.0,
            "total_cost_basis": 40000.0,
            "total_gain_loss": 10000.0,
            "positions": [
                {
                    "name": "Apple Inc.",
                    "ticker": "AAPL",
                    "quantity": 100,
                    "cost_basis": 15000.0,
                    "total_value": 20000.0,
                    "current_price": 200.0,
                    "price_change_dollars": 2.50,
                    "price_change_percent": 1.25,
                    "last_synced": "2026-05-09T17:00:00+00:00",
                },
                {
                    "name": "Vanguard S&P 500 ETF",
                    "ticker": "VOO",
                    "quantity": 50,
                    "cost_basis": 25000.0,
                    "total_value": 30000.0,
                    "current_price": 600.0,
                    "price_change_dollars": -1.00,
                    "price_change_percent": -0.17,
                    "last_synced": "2026-05-09T17:00:00+00:00",
                },
            ],
        }
    ]
}


@patch("octo_satellite.routers.monarch.monarch_session")
def test_get_investments_success(mock_session, client):
    mock_session.get_investment_positions = AsyncMock(return_value=MOCK_INVESTMENTS)
    resp = client.get("/monarch/investments")
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "monarch"
    assert len(data["accounts"]) == 1
    account = data["accounts"][0]
    assert account["total_value"] == 50000.0
    assert account["total_gain_loss"] == 10000.0
    assert len(account["positions"]) == 2
    assert account["positions"][0]["ticker"] == "AAPL"


@patch("octo_satellite.routers.monarch.monarch_session")
def test_get_investments_with_account_id(mock_session, client):
    mock_session.get_investment_positions = AsyncMock(return_value=MOCK_INVESTMENTS)
    resp = client.get("/monarch/investments?account_id=123")
    assert resp.status_code == 200
    mock_session.get_investment_positions.assert_called_once_with(account_id=123)


@patch("octo_satellite.routers.monarch.monarch_session")
def test_get_investments_expired_session(mock_session, client):
    mock_session.get_investment_positions = AsyncMock(return_value=None)
    resp = client.get("/monarch/investments")
    assert resp.status_code == 401
