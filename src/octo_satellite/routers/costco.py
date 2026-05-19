from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from octo_satellite.audit import log_request
from octo_satellite.auth import verify_shared_secret
from octo_satellite.providers.costco import costco_session

router = APIRouter(
    prefix="/costco",
    tags=["costco"],
    dependencies=[Depends(verify_shared_secret)],
)


@router.get("/health")
async def health(request: Request):
    """Verify Costco session is authenticated.

    Returns the auth status and account name if logged in.
    """
    result = await costco_session.check_auth()
    status_code = 200 if result["authenticated"] else 401
    await log_request(request, "costco", "health", status_code)
    return {"provider": "costco", **result}


@router.post("/login")
async def login(request: Request):
    """Launch a headed browser for manual Costco login.

    Opens a visible browser window — complete login there.
    Session is saved to disk for subsequent headless use.
    """
    success = await costco_session.login()
    status_code = 200 if success else 401
    await log_request(request, "costco", "login", status_code)
    if success:
        return {"provider": "costco", "status": "logged_in"}
    return {"provider": "costco", "status": "login_failed"}


@router.get("/orders")
async def list_orders(request: Request, page: int = 1):
    """List Costco orders with pagination.

    Args:
        page: Page number (1-based).

    Returns orders with total count and pagination info.
    """
    result = await costco_session.get_orders(page_num=page)
    if result.get("error") == "not_authenticated":
        await log_request(request, "costco", "orders", 401)
        raise HTTPException(status_code=401, detail="Session expired. Re-login required.")
    await log_request(request, "costco", "orders", 200)
    return {"provider": "costco", **result}


@router.get("/orders/{order_id}")
async def get_order(order_id: str, request: Request):
    """Get details for a specific Costco order.

    Returns order details including items, shipping address, and tracking.
    """
    order = await costco_session.get_order(order_id)
    status_code = 200 if order is not None else 404
    await log_request(request, "costco", f"orders/{order_id}", status_code)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found or session expired.")
    return {"provider": "costco", "order": order}


@router.get("/cart")
async def get_cart(request: Request):
    """View current Costco cart contents."""
    result = await costco_session.get_cart()
    if result.get("error") == "not_authenticated":
        await log_request(request, "costco", "cart", 401)
        raise HTTPException(status_code=401, detail="Session expired. Re-login required.")
    await log_request(request, "costco", "cart", 200)
    return {"provider": "costco", **result}


@router.post("/cart")
async def add_to_cart(request: Request, item_number: str):
    """Add a product to cart by Costco item number.

    Args:
        item_number: Costco product item number (e.g. 1234567).
    """
    result = await costco_session.add_to_cart(item_number)
    if result.get("error") == "not_authenticated":
        await log_request(request, "costco", f"cart/add/{item_number}", 401)
        raise HTTPException(status_code=401, detail="Session expired. Re-login required.")
    status_code = 200 if result["success"] else 400
    await log_request(request, "costco", f"cart/add/{item_number}", status_code)
    return JSONResponse(content={"provider": "costco", **result}, status_code=status_code)


@router.delete("/cart/{item_id}")
async def remove_from_cart(item_id: str, request: Request):
    """Remove an item from cart by item_id.

    item_id is the cart item ID returned by GET /cart.
    """
    result = await costco_session.remove_from_cart(item_id)
    if result.get("error") == "not_authenticated":
        await log_request(request, "costco", f"cart/remove/{item_id}", 401)
        raise HTTPException(status_code=401, detail="Session expired. Re-login required.")
    if result.get("error") == "item_not_found":
        await log_request(request, "costco", f"cart/remove/{item_id}", 404)
        raise HTTPException(status_code=404, detail="Item not found in cart.")
    status_code = 200 if result["success"] else 400
    await log_request(request, "costco", f"cart/remove/{item_id}", status_code)
    return {"provider": "costco", **result}


@router.get("/search")
async def search_products(request: Request, q: str, page: int = 1):
    """Search Costco products.

    Args:
        q: Search query string.
        page: Page number (1-based).
    """
    result = await costco_session.search(q, page_num=page)
    if result.get("error") == "not_authenticated":
        await log_request(request, "costco", f"search?q={q}", 401)
        raise HTTPException(status_code=401, detail="Session expired. Re-login required.")
    await log_request(request, "costco", f"search?q={q}", 200)
    return {"provider": "costco", **result}


@router.get("/items/{item_number}")
async def get_product(item_number: str, request: Request):
    """Get product details by Costco item number.

    Returns title, price, rating, features, availability, and more.
    """
    product = await costco_session.get_product(item_number)
    status_code = 200 if product is not None else 404
    await log_request(request, "costco", f"items/{item_number}", status_code)
    if product is None:
        raise HTTPException(
            status_code=404, detail="Product not found or session expired."
        )
    return {"provider": "costco", **product}
