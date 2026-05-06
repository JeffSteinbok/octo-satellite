from fastapi import APIRouter, Depends, HTTPException, Request

from octo_satellite.audit import log_request
from octo_satellite.auth import verify_shared_secret
from octo_satellite.providers.amazon import amazon_session

router = APIRouter(
    prefix="/amazon",
    tags=["amazon"],
    dependencies=[Depends(verify_shared_secret)],
)


@router.get("/health")
async def health(request: Request):
    """Verify Amazon session is authenticated.

    Returns the auth status and account name if logged in.
    """
    result = await amazon_session.check_auth()
    status_code = 200 if result["authenticated"] else 401
    await log_request(request, "amazon", "health", status_code)
    return {"provider": "amazon", **result}


@router.post("/login")
async def login(request: Request):
    """Launch a headed browser for manual Amazon login.

    Opens a visible browser window — complete login and 2FA there.
    Session is saved to disk for subsequent headless use.
    """
    success = await amazon_session.login()
    status_code = 200 if success else 401
    await log_request(request, "amazon", "login", status_code)
    if success:
        return {"provider": "amazon", "status": "logged_in"}
    return {"provider": "amazon", "status": "login_failed"}


@router.get("/orders")
async def list_orders(request: Request, page: int = 1):
    """List Amazon orders with pagination.

    Args:
        page: Page number (1-based, 10 orders per page).

    Returns orders with total count and pagination info.
    """
    result = await amazon_session.get_orders(page_num=page)
    status_code = 200 if result["orders"] is not None else 401
    await log_request(request, "amazon", "orders", status_code)
    if not result["orders"] and result["total_count"] == 0:
        raise HTTPException(status_code=401, detail="Session expired. Re-login required.")
    return {"provider": "amazon", **result}


@router.get("/orders/{order_id}")
async def get_order(order_id: str, request: Request):
    """Get details and tracking info for a specific order.

    Returns order details including items, shipping address, and tracking.
    """
    order = await amazon_session.get_order(order_id)
    status_code = 200 if order is not None else 404
    await log_request(request, "amazon", f"orders/{order_id}", status_code)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found or session expired.")
    return {"provider": "amazon", "order": order}


@router.get("/cart")
async def get_cart(request: Request):
    """View current Amazon cart contents."""
    result = await amazon_session.get_cart()
    status_code = 200 if result.get("error") is None else 401
    await log_request(request, "amazon", "cart", status_code)
    if result.get("error") == "not_authenticated":
        raise HTTPException(status_code=401, detail="Session expired. Re-login required.")
    return {"provider": "amazon", **result}


@router.post("/cart")
async def add_to_cart(request: Request, asin: str):
    """Add a product to cart by ASIN.

    Args:
        asin: Amazon product identifier (e.g. B0FQFB8FMG).
    """
    result = await amazon_session.add_to_cart(asin)
    status_code = 200 if result["success"] else 400
    await log_request(request, "amazon", f"cart/add/{asin}", status_code)
    if result.get("error") == "not_authenticated":
        raise HTTPException(status_code=401, detail="Session expired. Re-login required.")
    return {"provider": "amazon", **result}


@router.delete("/cart/{item_id}")
async def remove_from_cart(item_id: str, request: Request):
    """Remove an item from cart by item_id.

    item_id is the ephemeral cart item ID returned by GET /cart.
    """
    result = await amazon_session.remove_from_cart(item_id)
    status_code = 200 if result["success"] else 404
    await log_request(request, "amazon", f"cart/remove/{item_id}", status_code)
    if result.get("error") == "not_authenticated":
        raise HTTPException(status_code=401, detail="Session expired. Re-login required.")
    if result.get("error") == "item_not_found":
        raise HTTPException(status_code=404, detail="Item not found in cart.")
    return {"provider": "amazon", **result}


@router.get("/search")
async def search_products(request: Request, q: str, page: int = 1):
    """Search Amazon products.

    Args:
        q: Search query string.
        page: Page number (1-based).
    """
    result = await amazon_session.search(q, page_num=page)
    status_code = 200 if result.get("error") is None else 401
    await log_request(request, "amazon", f"search?q={q}", status_code)
    if result.get("error") == "not_authenticated":
        raise HTTPException(status_code=401, detail="Session expired. Re-login required.")
    return {"provider": "amazon", **result}


@router.get("/items/{asin}")
async def get_product(asin: str, request: Request):
    """Get product details by ASIN.

    Returns title, price, rating, features, availability, and more.
    """
    product = await amazon_session.get_product(asin)
    status_code = 200 if product is not None else 404
    await log_request(request, "amazon", f"items/{asin}", status_code)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found or session expired.")
    return {"provider": "amazon", **product}
