"""Trade journal — the authoritative record of decisions AND positions.

Two layers:
  • update_action_log(): flips a PENDING ActionLog to APPROVED/SKIPPED/EXPIRED and
    stamps response time — records the user's response to every alert.
  • Trade lifecycle (Week 10): open_trade / close_trade / get_open_trades /
    get_closed_trades / get_open_positions_summary — the real position ledger that
    replaces the Week 9 "APPROVED ActionLog = open position" proxy.
"""
from datetime import date, datetime, time, timedelta, timezone

import config
from agent.strategy import SECTOR_MAP
from core.db import get_db
from core.logger import get_logger
from models.action_log import ActionLog
from models.approval import Approval
from models.trade import Trade

logger = get_logger(__name__)


def _resolve_signal_id(signal_id_or_token) -> int | None:
    """Return a signal_id from either an int signal_id or a str approval token."""
    if signal_id_or_token is None:
        return None
    if isinstance(signal_id_or_token, int):
        return signal_id_or_token
    # Treat anything else as an approval token → look up its signal_id.
    token = str(signal_id_or_token)
    with get_db() as db:
        approval = db.query(Approval).filter(Approval.token == token).first()
        return approval.signal_id if approval else None


def update_action_log(signal_id_or_token, action_taken: str) -> int | None:
    """Update the latest PENDING ActionLog for a signal to *action_taken*.

    Accepts either a signal_id (int) or an approval token (str). Stamps
    action_taken_at = now (UTC) and response_time_sec = seconds elapsed since
    telegram_sent_at. No-ops (returns None) when the signal can't be resolved or no
    PENDING row exists. Never raises — journalling must not break the approval flow.

    Args:
        signal_id_or_token: signal_id (int) or approval token (str).
        action_taken: new status — "APPROVED", "SKIPPED", or "EXPIRED".

    Returns:
        The updated ActionLog row id, or None if nothing was updated.
    """
    try:
        signal_id = _resolve_signal_id(signal_id_or_token)
        if signal_id is None:
            return None

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with get_db() as db:
            row = (
                db.query(ActionLog)
                .filter(
                    ActionLog.signal_id == signal_id,
                    ActionLog.action_taken == "PENDING",
                )
                .order_by(ActionLog.id.desc())
                .first()
            )
            if row is None:
                logger.debug(
                    "No PENDING ActionLog for signal_id=%s (%s)", signal_id, action_taken
                )
                return None

            row.action_taken = action_taken
            row.action_taken_at = now
            if row.telegram_sent_at is not None:
                delta = (now - row.telegram_sent_at).total_seconds()
                row.response_time_sec = max(0, int(delta))
            row_id = row.id
            db.commit()

        logger.info("ActionLog #%s signal_id=%s → %s", row_id, signal_id, action_taken)
        return row_id
    except Exception as exc:
        logger.warning(
            "update_action_log failed (%s → %s): %s",
            signal_id_or_token, action_taken, exc,
        )
        return None


# ═════════════════════════════════════════════════════════════════════════════
# Trade ledger (Week 10) — real open/closed positions
# ═════════════════════════════════════════════════════════════════════════════

def _week_start() -> date:
    """Return the Monday (date) of the current calendar week."""
    today = date.today()
    return today - timedelta(days=today.weekday())


def _current_prices(symbols: list[str]) -> dict[str, float]:
    """Best-effort current last_price per symbol via one Kite quote call.

    Returns a {symbol: price} map; symbols whose quote is unavailable are omitted
    so callers fall back to entry price. Never raises.
    """
    if not symbols:
        return {}
    try:
        from core.kite_client import KiteClient
        kite = KiteClient()
        quote = kite.get_quote([f"NSE:{s}" for s in symbols])
        prices: dict[str, float] = {}
        for s in symbols:
            data = quote.get(f"NSE:{s}") or quote.get(s) or {}
            lp = data.get("last_price")
            if lp:
                prices[s] = float(lp)
        return prices
    except Exception as exc:
        logger.warning("_current_prices lookup failed: %s", exc)
        return {}


def _value_open_trades(trades: list[Trade]) -> float:
    """Mark-to-market value of open trades (quantity × current price).

    Falls back to entry_price for any symbol whose live quote is unavailable.
    """
    if not trades:
        return 0.0
    prices = _current_prices([t.symbol for t in trades])
    total = sum(t.quantity * prices.get(t.symbol, t.entry_price) for t in trades)
    return round(total, 2)


def open_trade(
    signal: dict, fill_price: float, order_id: str, action_log_id: int
) -> int:
    """Create an OPEN Trade row from an approved signal and link its ActionLog.

    entry_price is the ACTUAL fill (not the signal's projected price); quantity,
    position_value, target, and stop-loss come from the (sized) signal. time_stop_date
    is today + TIME_STOP_BY_STRATEGY[strategy]. is_paper reflects PAPER_TRADE_MODE.

    Args:
        signal: enriched signal dict (symbol, strategy_type, quantity, position_value,
            suggested_target, suggested_sl, signal_id).
        fill_price: actual fill price per share.
        order_id: broker/paper order id (PAPER-xxx or real Kite id).
        action_log_id: the ActionLog row to back-link to this trade.

    Returns:
        The new Trade row id.
    """
    symbol = signal.get("symbol", "")
    strategy = signal.get("strategy_type") or ""
    days = config.TIME_STOP_BY_STRATEGY.get(strategy, 10)
    time_stop_date = date.today() + timedelta(days=days)

    quantity = int(signal.get("quantity") or 0)
    position_value = signal.get("position_value")
    if position_value is None:
        position_value = round(quantity * fill_price, 2)
    target_price = signal.get("suggested_target")
    stop_loss_price = signal.get("suggested_sl")
    # Trade.target_price / stop_loss_price are NOT NULL; entries always carry them,
    # but guard against a malformed signal rather than raising on commit.
    if target_price is None:
        target_price = fill_price
    if stop_loss_price is None:
        stop_loss_price = fill_price

    is_paper = config.PAPER_TRADE_MODE

    with get_db() as db:
        trade = Trade(
            symbol=symbol,
            strategy_type=strategy or None,
            entry_date=datetime.now(),
            entry_price=fill_price,
            quantity=quantity,
            position_value=position_value,
            target_price=target_price,
            stop_loss_price=stop_loss_price,
            time_stop_date=time_stop_date,
            status="OPEN",
            order_id=order_id,
            is_paper=is_paper,
            signal_id=signal.get("signal_id"),
            action_log_id=action_log_id,
        )
        db.add(trade)
        db.commit()
        db.refresh(trade)
        trade_id = trade.id

        # Back-link: ActionLog row → this trade.
        if action_log_id:
            row = db.query(ActionLog).filter(ActionLog.id == action_log_id).first()
            if row is not None:
                row.trade_id = trade_id
                db.commit()

    logger.info(
        "Trade opened: %s %d@%s target=%s sl=%s (paper=%s)",
        symbol, quantity, fill_price, target_price, stop_loss_price, is_paper,
    )
    return trade_id


def close_trade(
    trade_id: int, exit_price: float, exit_reason: str, exit_order_id: str
) -> dict:
    """Close an open Trade: stamp exit fields, compute realized PnL, mark CLOSED.

    Args:
        trade_id: id of the OPEN trade to close.
        exit_price: actual exit fill price per share.
        exit_reason: TARGET / STOPLOSS / TIME_STOP / MANUAL.
        exit_order_id: broker/paper exit order id.

    Returns:
        Summary dict (symbol, quantity, entry_price, exit_price, exit_reason, pnl,
        pnl_pct, status). On a missing/already-closed trade: {"status": "error", ...}.
    """
    with get_db() as db:
        trade = db.query(Trade).filter(Trade.id == trade_id).first()
        if trade is None:
            logger.warning("close_trade: trade %s not found", trade_id)
            return {"status": "error", "reason": f"Trade {trade_id} not found"}

        pnl = (exit_price - trade.entry_price) * trade.quantity
        pnl_pct = (
            (exit_price - trade.entry_price) / trade.entry_price
            if trade.entry_price
            else 0.0
        )

        trade.exit_date = datetime.now()
        trade.exit_price = exit_price
        trade.exit_reason = exit_reason
        trade.exit_order_id = exit_order_id
        trade.pnl = round(pnl, 2)
        trade.pnl_pct = round(pnl_pct, 4)
        trade.status = "CLOSED"

        summary = {
            "status": "CLOSED",
            "trade_id": trade.id,
            "symbol": trade.symbol,
            "quantity": trade.quantity,
            "entry_price": trade.entry_price,
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 4),
        }
        db.commit()

    logger.info(
        "Trade closed: %s %s pnl=₹%.0f (%.1f%%)",
        summary["symbol"], exit_reason, pnl, pnl_pct * 100,
    )
    return summary


def get_trade(trade_id: int) -> Trade | None:
    """Return a single Trade by id (detached), or None if not found."""
    with get_db() as db:
        return db.query(Trade).filter(Trade.id == trade_id).first()


def get_open_trades() -> list[Trade]:
    """Return all Trade rows with status == 'OPEN'."""
    with get_db() as db:
        return db.query(Trade).filter(Trade.status == "OPEN").all()


def get_closed_trades(since: date | None = None) -> list[Trade]:
    """Return CLOSED trades, optionally filtered to exit_date >= *since*."""
    with get_db() as db:
        query = db.query(Trade).filter(Trade.status == "CLOSED")
        if since is not None:
            query = query.filter(Trade.exit_date >= datetime.combine(since, time.min))
        return query.all()


def get_open_positions_summary() -> dict:
    """Real snapshot of open positions for guard checks and reporting (Week 10).

    Replaces the Week 9 ActionLog proxy: reads OPEN rows from the Trade table and
    realized week PnL from CLOSED trades exited this calendar week.

    Returns:
        dict with open_count, symbols, by_sector, total_value (mark-to-market),
        week_pnl (realized, this week).
    """
    open_trades = get_open_trades()
    symbols = [t.symbol for t in open_trades]

    by_sector: dict[str, int] = {}
    for t in open_trades:
        sector = SECTOR_MAP.get(t.symbol, "Unknown")
        by_sector[sector] = by_sector.get(sector, 0) + 1

    total_value = _value_open_trades(open_trades)
    week_pnl = round(
        sum(t.pnl or 0.0 for t in get_closed_trades(since=_week_start())), 2
    )

    return {
        "open_count": len(open_trades),
        "symbols": symbols,
        "by_sector": by_sector,
        "total_value": total_value,
        "week_pnl": week_pnl,
    }
