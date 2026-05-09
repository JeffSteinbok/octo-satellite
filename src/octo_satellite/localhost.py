"""Middleware to reject requests from non-loopback clients."""

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger("octo_satellite.localhost")

LOOPBACK_PREFIXES = ("127.", "::1", "::ffff:127.")


class LocalhostOnlyMiddleware(BaseHTTPMiddleware):
    """Reject any request whose client IP is not loopback.

    This is a defense-in-depth measure: even if the server is accidentally
    bound to 0.0.0.0 or a real interface, remote clients get a 403.
    """

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else None
        if not client_ip or not client_ip.startswith(LOOPBACK_PREFIXES):
            logger.warning(f"Rejected non-loopback request from {client_ip}")
            return JSONResponse(
                status_code=403,
                content={"detail": "This service only accepts connections from localhost."},
            )
        return await call_next(request)
