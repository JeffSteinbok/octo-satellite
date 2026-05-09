"""Tests for Amazon router endpoints."""

from unittest.mock import AsyncMock, patch

# -- Login --


@patch("octo_satellite.routers.amazon.amazon_session")
def test_amazon_login_success(mock_session, client):
    mock_session.login = AsyncMock(return_value=True)
    resp = client.post("/amazon/login")
    assert resp.status_code == 200
    assert resp.json()["status"] == "logged_in"


@patch("octo_satellite.routers.amazon.amazon_session")
def test_amazon_login_failure(mock_session, client):
    mock_session.login = AsyncMock(return_value=False)
    resp = client.post("/amazon/login")
    assert resp.status_code == 200
    assert resp.json()["status"] == "login_failed"


# -- Orders --


@patch("octo_satellite.routers.amazon.amazon_session")
def test_list_orders_success(mock_session, client):
    mock_session.get_orders = AsyncMock(
        return_value={
            "orders": [{"id": "111-222", "date": "2026-05-01", "total": "$25.00"}],
            "total_count": 1,
            "page": 1,
        }
    )
    resp = client.get("/amazon/orders")
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "amazon"
    assert len(data["orders"]) == 1


@patch("octo_satellite.routers.amazon.amazon_session")
def test_list_orders_expired(mock_session, client):
    mock_session.get_orders = AsyncMock(return_value={"orders": [], "total_count": 0, "page": 1})
    resp = client.get("/amazon/orders")
    assert resp.status_code == 401


# -- Order Detail --


@patch("octo_satellite.routers.amazon.amazon_session")
def test_get_order_success(mock_session, client):
    mock_session.get_order = AsyncMock(return_value={"id": "111-222", "items": []})
    resp = client.get("/amazon/orders/111-222")
    assert resp.status_code == 200
    assert resp.json()["order"]["id"] == "111-222"


@patch("octo_satellite.routers.amazon.amazon_session")
def test_get_order_not_found(mock_session, client):
    mock_session.get_order = AsyncMock(return_value=None)
    resp = client.get("/amazon/orders/111-222")
    assert resp.status_code == 404


# -- Cart --


@patch("octo_satellite.routers.amazon.amazon_session")
def test_get_cart_success(mock_session, client):
    mock_session.get_cart = AsyncMock(return_value={"items": [], "subtotal": "$0.00"})
    resp = client.get("/amazon/cart")
    assert resp.status_code == 200
    assert resp.json()["provider"] == "amazon"


@patch("octo_satellite.routers.amazon.amazon_session")
def test_get_cart_expired(mock_session, client):
    mock_session.get_cart = AsyncMock(return_value={"error": "not_authenticated"})
    resp = client.get("/amazon/cart")
    assert resp.status_code == 401


@patch("octo_satellite.routers.amazon.amazon_session")
def test_add_to_cart_success(mock_session, client):
    mock_session.add_to_cart = AsyncMock(return_value={"success": True})
    resp = client.post("/amazon/cart?asin=B0TEST123")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@patch("octo_satellite.routers.amazon.amazon_session")
def test_add_to_cart_failure(mock_session, client):
    mock_session.add_to_cart = AsyncMock(return_value={"success": False, "error": "unavailable"})
    resp = client.post("/amazon/cart?asin=B0TEST123")
    assert resp.status_code == 200
    assert resp.json()["success"] is False


@patch("octo_satellite.routers.amazon.amazon_session")
def test_remove_from_cart_success(mock_session, client):
    mock_session.remove_from_cart = AsyncMock(return_value={"success": True})
    resp = client.delete("/amazon/cart/item123")
    assert resp.status_code == 200


@patch("octo_satellite.routers.amazon.amazon_session")
def test_remove_from_cart_not_found(mock_session, client):
    mock_session.remove_from_cart = AsyncMock(
        return_value={"success": False, "error": "item_not_found"}
    )
    resp = client.delete("/amazon/cart/item123")
    assert resp.status_code == 404


# -- Search --


@patch("octo_satellite.routers.amazon.amazon_session")
def test_search_success(mock_session, client):
    mock_session.search = AsyncMock(return_value={"products": [{"title": "Widget"}], "total": 1})
    resp = client.get("/amazon/search?q=widget")
    assert resp.status_code == 200
    assert resp.json()["provider"] == "amazon"


@patch("octo_satellite.routers.amazon.amazon_session")
def test_search_expired(mock_session, client):
    mock_session.search = AsyncMock(return_value={"error": "not_authenticated"})
    resp = client.get("/amazon/search?q=widget")
    assert resp.status_code == 401


# -- Product Detail --


@patch("octo_satellite.routers.amazon.amazon_session")
def test_get_product_success(mock_session, client):
    mock_session.get_product = AsyncMock(
        return_value={"asin": "B0TEST", "title": "Widget", "price": "$9.99"}
    )
    resp = client.get("/amazon/items/B0TEST")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Widget"


@patch("octo_satellite.routers.amazon.amazon_session")
def test_get_product_not_found(mock_session, client):
    mock_session.get_product = AsyncMock(return_value=None)
    resp = client.get("/amazon/items/B0TEST")
    assert resp.status_code == 404
