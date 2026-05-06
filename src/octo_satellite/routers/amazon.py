from fastapi import APIRouter, Depends, HTTPException, Request

from octo_satellite.auth import verify_shared_secret
from octo_satellite.audit import log_request
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
