"""Tests for Costco router endpoints."""

from unittest.mock import AsyncMock, patch

# -- Login --


@patch("octo_satellite.routers.costco.costco_session")
def test_costco_login_success(mock_session, client):
    mock_session.login = AsyncMock(return_value=True)
    resp = client.post("/costco/login")
    assert resp.status_code == 200
    assert resp.json()["status"] == "logged_in"


@patch("octo_satellite.routers.costco.costco_session")
def test_costco_login_failure(mock_session, client):
    mock_session.login = AsyncMock(return_value=False)
    resp = client.post("/costco/login")
    assert resp.status_code == 200
    assert resp.json()["status"] == "login_failed"


# -- Orders --


@patch("octo_satellite.routers.costco.costco_session")
def test_list_orders_success(mock_session, client):
    mock_session.get_orders = AsyncMock(
        return_value={
            "orders": [{"order_id": "12345678", "date": "May 01, 2026", "total": "$125.00"}],
            "total_count": 1,
            "page": 1,
            "total_pages": 1,
            "error": None,
        }
    )
    resp = client.get("/costco/orders")
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "costco"
    assert len(data["orders"]) == 1


@patch("octo_satellite.routers.costco.costco_session")
def test_list_orders_empty_is_ok(mock_session, client):
    """Empty orders should return 200, not 401."""
    mock_session.get_orders = AsyncMock(
        return_value={
            "orders": [],
            "total_count": 0,
            "page": 1,
            "total_pages": 0,
            "error": None,
        }
    )
    resp = client.get("/costco/orders")
    assert resp.status_code == 200
    assert resp.json()["orders"] == []


@patch("octo_satellite.routers.costco.costco_session")
def test_list_orders_expired(mock_session, client):
    mock_session.get_orders = AsyncMock(
        return_value={
            "orders": None,
            "total_count": 0,
            "page": 1,
            "total_pages": 0,
            "error": "not_authenticated",
        }
    )
    resp = client.get("/costco/orders")
    assert resp.status_code == 401


# -- Order Detail --


@patch("octo_satellite.routers.costco.costco_session")
def test_get_order_success(mock_session, client):
    mock_session.get_order = AsyncMock(return_value={"order_id": "12345678", "items": []})
    resp = client.get("/costco/orders/12345678")
    assert resp.status_code == 200
    assert resp.json()["order"]["order_id"] == "12345678"


@patch("octo_satellite.routers.costco.costco_session")
def test_get_order_not_found(mock_session, client):
    mock_session.get_order = AsyncMock(return_value=None)
    resp = client.get("/costco/orders/99999")
    assert resp.status_code == 404


# -- Cart --


@patch("octo_satellite.routers.costco.costco_session")
def test_get_cart_success(mock_session, client):
    mock_session.get_cart = AsyncMock(
        return_value={
            "items": [{"title": "Paper Towels", "item_number": "1234567"}],
            "subtotal": "$24.99",
            "error": None,
        }
    )
    resp = client.get("/costco/cart")
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "costco"
    assert len(data["items"]) == 1


@patch("octo_satellite.routers.costco.costco_session")
def test_get_cart_expired(mock_session, client):
    mock_session.get_cart = AsyncMock(
        return_value={"items": [], "subtotal": None, "error": "not_authenticated"}
    )
    resp = client.get("/costco/cart")
    assert resp.status_code == 401


@patch("octo_satellite.routers.costco.costco_session")
def test_add_to_cart_success(mock_session, client):
    mock_session.add_to_cart = AsyncMock(
        return_value={"success": True, "item_number": "1234567", "title": "Paper Towels"}
    )
    resp = client.post("/costco/cart?item_number=1234567")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@patch("octo_satellite.routers.costco.costco_session")
def test_add_to_cart_out_of_stock(mock_session, client):
    mock_session.add_to_cart = AsyncMock(
        return_value={
            "success": False,
            "error": "out_of_stock",
            "title": "Paper Towels",
            "item_number": "1234567",
        }
    )
    resp = client.post("/costco/cart?item_number=1234567")
    assert resp.status_code == 400


@patch("octo_satellite.routers.costco.costco_session")
def test_add_to_cart_expired(mock_session, client):
    mock_session.add_to_cart = AsyncMock(
        return_value={"success": False, "error": "not_authenticated"}
    )
    resp = client.post("/costco/cart?item_number=1234567")
    assert resp.status_code == 401


@patch("octo_satellite.routers.costco.costco_session")
def test_remove_from_cart_success(mock_session, client):
    mock_session.remove_from_cart = AsyncMock(return_value={"success": True, "item_id": "abc123"})
    resp = client.delete("/costco/cart/abc123")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@patch("octo_satellite.routers.costco.costco_session")
def test_remove_from_cart_not_found(mock_session, client):
    mock_session.remove_from_cart = AsyncMock(
        return_value={"success": False, "error": "item_not_found"}
    )
    resp = client.delete("/costco/cart/abc123")
    assert resp.status_code == 404


# -- Search --


@patch("octo_satellite.routers.costco.costco_session")
def test_search_success(mock_session, client):
    mock_session.search = AsyncMock(
        return_value={
            "results": [{"item_number": "1234567", "title": "Paper Towels", "price": "$24.99"}],
            "has_next": False,
            "page": 1,
            "error": None,
        }
    )
    resp = client.get("/costco/search?q=paper+towels")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["results"]) == 1


@patch("octo_satellite.routers.costco.costco_session")
def test_search_expired(mock_session, client):
    mock_session.search = AsyncMock(return_value={"results": [], "error": "not_authenticated"})
    resp = client.get("/costco/search?q=test")
    assert resp.status_code == 401


# -- Product Detail --


@patch("octo_satellite.routers.costco.costco_session")
def test_get_product_success(mock_session, client):
    mock_session.get_product = AsyncMock(
        return_value={
            "item_number": "1234567",
            "title": "Kirkland Paper Towels",
            "price": "$24.99",
            "directly_addable": True,
        }
    )
    resp = client.get("/costco/items/1234567")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Kirkland Paper Towels"


@patch("octo_satellite.routers.costco.costco_session")
def test_get_product_not_found(mock_session, client):
    mock_session.get_product = AsyncMock(return_value=None)
    resp = client.get("/costco/items/9999999")
    assert resp.status_code == 404


# -- Health --


@patch("octo_satellite.routers.costco.costco_session")
def test_health_authenticated(mock_session, client):
    mock_session.check_auth = AsyncMock(return_value={"authenticated": True, "name": "Jeff"})
    resp = client.get("/costco/health")
    assert resp.status_code == 200
    assert resp.json()["authenticated"] is True


@patch("octo_satellite.routers.costco.costco_session")
def test_health_not_authenticated(mock_session, client):
    mock_session.check_auth = AsyncMock(return_value={"authenticated": False, "name": None})
    resp = client.get("/costco/health")
    assert resp.status_code == 200
    assert resp.json()["authenticated"] is False
