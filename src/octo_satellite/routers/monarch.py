from fastapi import APIRouter, Depends, HTTPException, Request

from octo_satellite.audit import log_request
from octo_satellite.auth import verify_shared_secret
from octo_satellite.providers.monarch import monarch_session

router = APIRouter(
    prefix="/monarch",
    tags=["monarch"],
    dependencies=[Depends(verify_shared_secret)],
)


def _validate_date(value: str | None, field: str) -> str | None:
    """Validate an optional ISO ``YYYY-MM-DD`` date string, raising 422 if invalid."""
    if value is None:
        return None
    from datetime import date

    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {field}: '{value}'. Expected ISO format YYYY-MM-DD.",
        ) from None


def _validate_range(start_date: str | None, end_date: str | None) -> tuple[str | None, str | None]:
    """Validate an optional date range and ensure start is not after end."""
    start = _validate_date(start_date, "start_date")
    end = _validate_date(end_date, "end_date")
    if start is not None and end is not None and start > end:
        raise HTTPException(
            status_code=422,
            detail=f"start_date ({start}) must not be after end_date ({end}).",
        )
    return start, end


@router.get("/health")
async def health(request: Request):
    """Verify Monarch Money session is authenticated."""
    result = await monarch_session.check_auth()
    status_code = 200 if result["authenticated"] else 401
    await log_request(request, "monarch", "health", status_code)
    return {"provider": "monarch", **result}


@router.post("/login")
async def login(request: Request):
    """Interactive login to Monarch Money.

    Prompts for email, password, and MFA in the server terminal.
    """
    success = await monarch_session.login()
    status_code = 200 if success else 401
    await log_request(request, "monarch", "login", status_code)
    if success:
        return {"provider": "monarch", "status": "logged_in"}
    return {"provider": "monarch", "status": "login_failed"}


@router.get("/sync-status")
async def sync_status(request: Request):
    """Get sync status for all accounts — last synced time, institution health, etc."""
    result = await monarch_session.get_sync_status()
    status_code = 200 if result is not None else 401
    await log_request(request, "monarch", "sync-status", status_code)
    if result is None:
        raise HTTPException(status_code=401, detail="Session expired. Re-login required.")
    return {"provider": "monarch", **result}


@router.post("/refresh")
async def refresh_accounts(request: Request):
    """Trigger an account refresh with all linked institutions.

    Fire-and-forget — returns immediately after requesting the refresh.
    Use GET /monarch/sync-status to check progress.
    """
    result = await monarch_session.refresh_accounts()
    status_code = 200 if result is not None else 401
    await log_request(request, "monarch", "refresh", status_code)
    if result is None:
        raise HTTPException(status_code=401, detail="Session expired. Re-login required.")
    return {"provider": "monarch", **result}


@router.get("/accounts")
async def get_accounts(request: Request):
    """Get accounts and balances grouped by type.

    Returns account groups with per-type totals.
    """
    result = await monarch_session.get_accounts()
    status_code = 200 if result is not None else 401
    await log_request(request, "monarch", "accounts", status_code)
    if result is None:
        raise HTTPException(status_code=401, detail="Session expired. Re-login required.")
    return {"provider": "monarch", "accounts": result}


@router.get("/net-worth")
async def get_net_worth(
    request: Request, start_date: str | None = None, end_date: str | None = None
):
    """Get net worth from Monarch (uses account inclusion settings).

    Query params:
        start_date: Optional ISO date (YYYY-MM-DD). If provided (with or without
                    end_date), returns the daily snapshot history over the range.
        end_date: Optional ISO date (YYYY-MM-DD). Defaults to today.
    """
    start, end = _validate_range(start_date, end_date)
    result = await monarch_session.get_net_worth(start_date=start, end_date=end)
    status_code = 200 if result is not None else 401
    await log_request(request, "monarch", "net-worth", status_code)
    if result is None:
        raise HTTPException(status_code=401, detail="Session expired. Re-login required.")
    return {"provider": "monarch", **result}


@router.get("/investments")
async def get_investments(request: Request, account_id: int | None = None):
    """Get investment account positions (holdings).

    Query params:
        account_id: Optional — if provided, returns positions for that account only.
                    Otherwise returns positions for all investment accounts.
    """
    result = await monarch_session.get_investment_positions(account_id=account_id)
    status_code = 200 if result is not None else 401
    await log_request(request, "monarch", "investments", status_code)
    if result is None:
        raise HTTPException(status_code=401, detail="Session expired. Re-login required.")
    return {"provider": "monarch", **result}


@router.get("/categories")
async def get_categories(request: Request):
    """List transaction categories (id, name, group) for use as filters."""
    result = await monarch_session.get_categories()
    status_code = 200 if result is not None else 401
    await log_request(request, "monarch", "categories", status_code)
    if result is None:
        raise HTTPException(status_code=401, detail="Session expired. Re-login required.")
    return {"provider": "monarch", **result}


@router.get("/merchants")
async def get_merchants(
    request: Request,
    months: int = 3,
    start_date: str | None = None,
    end_date: str | None = None,
    category: str | None = None,
    limit: int | None = None,
):
    """Break spending down by merchant — aggregate totals only, no transactions.

    Query params:
        category: Optional category or category-group name (case-insensitive)
                  to scope the breakdown, e.g. `?category=Travel & Lifestyle`
                  or `?category=Air Travel`. See GET /monarch/categories.
        months: Lookback window when no dates are given (default: 3).
        start_date: Optional ISO date (YYYY-MM-DD). Takes precedence over months.
        end_date: Optional ISO date (YYYY-MM-DD). Defaults to today.
        limit: Optional cap on the number of merchants returned (top spend first).
    """
    start, end = _validate_range(start_date, end_date)
    result = await monarch_session.get_merchant_spending(
        months=months, start_date=start, end_date=end, category=category, limit=limit
    )
    if result is not None and result.get("error") == "category_not_found":
        await log_request(request, "monarch", "merchants", 404)
        raise HTTPException(status_code=404, detail=f"Unknown category: '{result['category']}'.")
    status_code = 200 if result is not None else 401
    await log_request(request, "monarch", "merchants", status_code)
    if result is None:
        raise HTTPException(status_code=401, detail="Session expired. Re-login required.")
    return {"provider": "monarch", **result}


@router.get("/spending")
async def get_spending(
    request: Request,
    months: int = 3,
    start_date: str | None = None,
    end_date: str | None = None,
):
    """Get spending trends — income, expenses, savings by month.

    Query params:
        months: Number of months to look back (default: 3). Ignored when
                start_date is provided.
        start_date: Optional ISO date (YYYY-MM-DD). Takes precedence over months.
        end_date: Optional ISO date (YYYY-MM-DD). Defaults to today.
    """
    start, end = _validate_range(start_date, end_date)
    result = await monarch_session.get_spending(months=months, start_date=start, end_date=end)
    status_code = 200 if result is not None else 401
    await log_request(request, "monarch", "spending", status_code)
    if result is None:
        raise HTTPException(status_code=401, detail="Session expired. Re-login required.")
    return {"provider": "monarch", **result}
