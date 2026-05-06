import asyncio
import logging

import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI

from octo_satellite.config import settings
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
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass
    await amazon_session.close()


app = FastAPI(
    title="Octo Satellite",
    description="Local proxy service exposing provider APIs to OpenClaw without leaking secrets.",
    lifespan=lifespan,
)

app.include_router(amazon.router)
app.include_router(monarch.router)


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
