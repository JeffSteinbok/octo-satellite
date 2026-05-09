import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from octo_satellite.config import settings
from octo_satellite.localhost import LocalhostOnlyMiddleware
from octo_satellite.providers.amazon import amazon_session
from octo_satellite.providers.monarch import monarch_session
from octo_satellite.routers import amazon, monarch

logger = logging.getLogger("octo_satellite")

HEARTBEAT_INTERVAL_SECONDS = 3 * 60 * 60  # 3 hours


async def _heartbeat_loop():
    """Background task that pings providers periodically to keep sessions alive."""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)

        # Amazon
        try:
            alive = await amazon_session.heartbeat()
            if not alive:
                logger.warning("Amazon session expired. Re-login required.")
        except Exception as e:
            logger.error(f"Amazon heartbeat failed: {e}")

        # Monarch
        try:
            result = await monarch_session.check_auth()
            if result["authenticated"]:
                logger.info("Monarch heartbeat: session alive")
            else:
                logger.warning("Monarch session expired. Re-login required.")
        except Exception as e:
            logger.error(f"Monarch heartbeat failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start heartbeat
    heartbeat_task = asyncio.create_task(_heartbeat_loop())
    logger.info(f"Heartbeat started (every {HEARTBEAT_INTERVAL_SECONDS // 3600}h)")
    yield
    # Shutdown
    heartbeat_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await heartbeat_task
    await amazon_session.close()


app = FastAPI(
    title="Octo Satellite",
    description="Local proxy service exposing provider APIs to OpenClaw without leaking secrets.",
    lifespan=lifespan,
)

app.include_router(amazon.router)
app.include_router(monarch.router)

if settings.localhost_only:
    app.add_middleware(LocalhostOnlyMiddleware)


@app.get("/", response_class=HTMLResponse)
async def root():
    """Landing page with links to docs and provider endpoints."""
    return """<!DOCTYPE html>
<html>
<head>
    <title>Octo Satellite</title>
    <style>
        body { font-family: system-ui, sans-serif; max-width: 600px; margin: 60px auto; padding: 0 20px; color: #e0e0e0; background: #1a1a2e; }
        h1 { font-size: 1.8em; }
        a { color: #64b5f6; }
        ul { list-style: none; padding: 0; }
        li { padding: 4px 0; }
        code { background: #2a2a4a; padding: 2px 6px; border-radius: 4px; font-size: 0.9em; }
        .section { margin-top: 24px; }
    </style>
</head>
<body>
    <h1>🐙🛰️ Octo Satellite</h1>
    <p>Local secrets broker for <a href="https://github.com/JeffSteinbok/openclaw">OpenClaw</a>.</p>

    <div class="section">
        <h3>📖 API Docs</h3>
        <ul>
            <li><a href="/docs">Interactive docs (Swagger)</a></li>
            <li><a href="/openapi.json">OpenAPI spec</a></li>
        </ul>
    </div>

    <div class="section">
        <h3>🔌 Providers</h3>
        <ul>
            <li><code>Amazon</code> — <a href="/amazon/health">/amazon/health</a></li>
            <li><code>Monarch</code> — <a href="/monarch/health">/monarch/health</a></li>
        </ul>
    </div>
</body>
</html>"""


@app.get("/health")
async def root_health():
    return {"status": "ok"}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
