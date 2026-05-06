from fastapi import HTTPException, Query, Request, status

from octo_satellite.config import settings


async def verify_shared_secret(
    request: Request,
    token: str | None = Query(None, alias="token"),
) -> None:
    """Dependency that enforces shared secret auth when configured.

    Auth is skipped when running on the dev port.
    Accepts either:
      - Authorization: Bearer <secret> header
      - ?token=<secret> query parameter
    """
    if settings.shared_secret is None:
        return

    # Skip auth on dev port
    if settings.port == settings.dev_port:
        return

    # Check query param first
    if token == settings.shared_secret:
        return

    # Then check header
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )

    bearer_token = auth_header[len("Bearer ") :]
    if bearer_token != settings.shared_secret:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid shared secret",
        )
