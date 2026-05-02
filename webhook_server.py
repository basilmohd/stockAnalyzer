"""
Entry point A — FastAPI webhook server.
Handles Telegram callbacks, Kite OAuth redirect, and approval endpoints.
Run: uvicorn webhook_server:app --host 0.0.0.0 --port 8000 --reload
"""
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import FastAPI, Request

from config import USE_MOCK, REDIS_URL
from core.db import init_db
from core.redis_client import RedisClient
from routes.approval_routes import router as approval_router
from routes.kite_routes import router as kite_router
from routes.telegram_routes import router as telegram_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup / shutdown lifecycle."""
    logger.info("Starting Portfolio Agent — Webhook Server")
    app.state.redis = RedisClient(REDIS_URL)
    init_db()
    logger.info("Webhook server ready on port 8000")
    yield
    logger.info("Webhook server shutting down")


app = FastAPI(title="Portfolio Agent Webhook", version="0.1.0", lifespan=lifespan)

app.include_router(kite_router, prefix="/kite")
app.include_router(telegram_router, prefix="/telegram")
app.include_router(approval_router, prefix="/approve")


@app.get("/")
def root() -> dict:
    """Service identity probe."""
    return {"service": "Portfolio Agent Webhook", "version": "0.1.0"}


@app.get("/health")
def health() -> dict:
    """Liveness check used by EC2 / load balancer health checks."""
    return {
        "status": "ok",
        "mode": "mock" if USE_MOCK else "live",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/technicals/{symbol}")
def get_technicals(symbol: str, request: Request) -> dict:
    """Return cached technical indicators for *symbol* from Redis."""
    cached = request.app.state.redis.get(f"indicators:{symbol.upper()}")
    if not cached:
        return {"symbol": symbol.upper(), "status": "not_cached", "data": None}
    return {"symbol": symbol.upper(), "status": "ok", "data": json.loads(cached)}


@app.get("/news/{symbol}")
def get_news(symbol: str, request: Request) -> dict:
    """Return cached news articles for *symbol* from Redis."""
    cached = request.app.state.redis.get(f"news_articles:{symbol.upper()}")
    if not cached:
        return {"symbol": symbol.upper(), "status": "not_cached", "data": None}
    return {"symbol": symbol.upper(), "status": "ok", "data": json.loads(cached)}


@app.post("/briefing/trigger")
async def trigger_briefing() -> dict:
    """Manually trigger the morning briefing — sends result to Telegram immediately."""
    from agent.briefing import run_briefing
    success = await run_briefing()
    return {"triggered": True, "success": success}


@app.post("/signals/trigger")
async def trigger_signals() -> dict:
    """Manually trigger the signal pipeline — returns summary dict."""
    from agent.signals import run_signal_pipeline
    return await run_signal_pipeline()


@app.get("/signals/latest")
def signals_latest(request: Request) -> dict:
    """Return the cached result of the last signal pipeline run from Redis."""
    cached = request.app.state.redis.get("signals:last_run")
    if not cached:
        return {"status": "not_run", "data": None}
    return {"status": "ok", "data": json.loads(cached)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("webhook_server:app", host="0.0.0.0", port=8000, reload=True)
