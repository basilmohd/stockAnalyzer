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

from config import USE_MOCK, USE_MOCK_KITE, REDIS_URL
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
    # Register bot commands with Telegram
    from core.telegram_bot import register_bot_commands
    await register_bot_commands()
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
        "mode": "mock" if USE_MOCK_KITE else "live",
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


@app.post("/scanner/trigger")
async def trigger_scanner() -> dict:
    """Manually trigger the opportunity scanner — sends Telegram alerts, returns summary."""
    from agent.scanner import send_opportunity_alerts
    return await send_opportunity_alerts()


@app.post("/health/trigger")
async def trigger_health() -> dict:
    """Manually trigger the weekly health report — sends to Telegram, returns health dict."""
    from agent.health import compute_health_score, send_weekly_health_report
    await send_weekly_health_report()
    from agent.health import compute_health_score
    return compute_health_score()


@app.get("/health/latest")
def health_latest() -> dict:
    """Return the latest PortfolioSnapshot health score from SQLite."""
    from core.db import get_db
    from models.portfolio_snap import PortfolioSnapshot
    with get_db() as db:
        snap = (
            db.query(PortfolioSnapshot)
            .order_by(PortfolioSnapshot.id.desc())
            .first()
        )
    if not snap:
        return {"status": "no_data", "data": None}
    return {"status": "ok", "data": json.loads(snap.health_score_json)}


@app.post("/health/clear-cache")
def clear_holdings_cache(request: Request) -> dict:
    """Manually clear Redis holdings cache (debug endpoint).
    
    Useful when you've manually traded via Zerodha portal and want to force a
    refresh without waiting for the 30-min periodic refresh job.
    """
    cleared = request.app.state.redis.delete("kite:holdings_cache")
    if cleared:
        logger.info("Holdings cache manually cleared via POST /health/clear-cache")
        return {"status": "ok", "message": "Holdings cache cleared successfully"}
    else:
        return {"status": "ok", "message": "Holdings cache was not present or Redis unavailable"}


@app.post("/holdings/refresh")
async def refresh_holdings_endpoint():
    """On-demand holdings refresh."""
    from core.exception_handler import safe_run
    from data.portfolio import get_holdings_with_sl_status
    
    result = await safe_run("manual_holdings_refresh", get_holdings_with_sl_status)
    return {
        "status": "success" if result else "error",
        "message": "Holdings cache refreshed"
    }

@app.get("/action-log")
def action_log_list() -> list:
    """Return the last 20 ActionLog records ordered by created_at DESC."""
    from core.db import get_db
    from models.action_log import ActionLog as ActionLogModel
    with get_db() as db:
        records = (
            db.query(ActionLogModel)
            .order_by(ActionLogModel.created_at.desc())
            .limit(20)
            .all()
        )
    return [
        {
            "id": r.id,
            "symbol": r.symbol,
            "strategy_type": r.strategy_type,
            "signal_action": r.signal_action,
            "confidence": r.confidence,
            "entry_price": r.entry_price,
            "suggested_sl": r.suggested_sl,
            "suggested_target": r.suggested_target,
            "action_taken": r.action_taken,
            "rejection_reason": r.rejection_reason,
            "telegram_sent_at": r.telegram_sent_at.isoformat() if r.telegram_sent_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]


@app.get("/action-log/stats")
def action_log_stats() -> dict:
    """Return counts of ActionLog records grouped by action_taken."""
    from sqlalchemy import func
    from core.db import get_db
    from models.action_log import ActionLog as ActionLogModel
    with get_db() as db:
        rows = (
            db.query(ActionLogModel.action_taken, func.count(ActionLogModel.id))
            .group_by(ActionLogModel.action_taken)
            .all()
        )
    return {action: count for action, count in rows}


@app.get("/sizing/preview")
def sizing_preview(
    symbol: str, entry: float, sl: float, strategy: str = "SWING_TRADE"
) -> dict:
    """Preview the position-sizing math for a hypothetical entry — no scan, no order.

    Example:
        /sizing/preview?symbol=INFY&entry=1500&sl=1440&strategy=SWING_TRADE
    """
    from agent.sizing import calculate_position
    position = calculate_position(
        entry_price=entry, stop_loss_price=sl, strategy_type=strategy
    )
    return {
        "symbol": symbol.upper(),
        "entry": entry,
        "stop_loss": sl,
        "strategy": strategy,
        "position": position,
    }


@app.get("/guard/status")
def guard_status() -> dict:
    """One-glance portfolio guard state: open positions + deployable capital."""
    from agent.portfolio_guard import get_open_positions_summary
    from agent.sizing import get_available_capital
    return {
        "open_positions": get_open_positions_summary(),
        "capital": get_available_capital(),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("webhook_server:app", host="0.0.0.0", port=8000, reload=True)
