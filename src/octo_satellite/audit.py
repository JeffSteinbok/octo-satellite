"""Audit logging for all broker API calls."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Request

from octo_satellite.config import settings

logger = logging.getLogger("octo_satellite.audit")

LOG_DIR = Path(settings.audit_log_dir).expanduser()
LOG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)

_log_file = LOG_DIR / "audit.jsonl"


async def log_request(request: Request, provider: str, endpoint: str, status_code: int):
    """Append an audit entry for an API call."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "endpoint": endpoint,
        "method": request.method,
        "path": str(request.url.path),
        "client": request.client.host if request.client else None,
        "status_code": status_code,
    }
    with open(_log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")

    logger.info(f"{provider}/{endpoint} → {status_code}")
