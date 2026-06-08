"""Exit monitor — watches OPEN trades for target / stop-loss / time-stop exits.

Runs every 5 min during market hours (like the SL monitor). For each OPEN trade it
fetches the live price and checks, in priority order, STOPLOSS → TARGET → TIME_STOP.
A triggered trade gets an approval token + a Telegram exit alert (SELL NOW / HOLD MORE),
rate-limited per trade via a Redis cooldown so it doesn't re-alert every 5 min.

Execution is paper-aware: place_order checks PAPER_TRADE_MODE first, so a paper exit
"fills" at the live quote and never reaches the real broker.
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import config
from config import MARKET_CLOSE, MARKET_OPEN, REDIS_URL, TIMEZONE
from agent.journal import close_trade, get_open_trades, get_trade
from core.approval import generate_token
from core.kite_client import KiteClient
from core.logger import get_logger
from core.redis_client import RedisClient
from core.telegram_bot import send_alert

IST = ZoneInfo(TIMEZONE)
logger = get_logger(__name__)
_redis = RedisClient(REDIS_URL)

EXIT_COOLDOWN_MINS = 30    # don't re-alert the same trade within this window
HOLD_COOLDOWN_MINS = 120   # user tapped HOLD MORE → silence this trade for 2 hours

_EXIT_EMOJI: dict[str, str] = {
    "TARGET": "🎯",
    "STOPLOSS": "🛑",
    "TIME_STOP": "⏰",
}


# ── Price + exit-condition helpers ──────────────────────────────────────────────

def _get_current_price(symbol: str) -> float | None:
    """Return the live last_price for *symbol*, or None if unavailable. Never raises."""
    try:
        kite = KiteClient()
        quote = kite.get_quote([f"NSE:{symbol}"])
        data = quote.get(f"NSE:{symbol}") or quote.get(symbol) or {}
        lp = data.get("last_price")
        return float(lp) if lp else None
    except Exception as exc:
        logger.warning("exit monitor: price lookup failed for %s: %s", symbol, exc)
        return None


def _determine_exit_reason(trade, current_price: float) -> str | None:
    """Return the exit reason if any condition is met, else None.

    Priority: STOPLOSS (downside first) → TARGET → TIME_STOP.
    """
    if trade.stop_loss_price and current_price <= trade.stop_loss_price:
        return "STOPLOSS"
    if trade.target_price and current_price >= trade.target_price:
        return "TARGET"
    if trade.time_stop_date and date.today() >= trade.time_stop_date:
        return "TIME_STOP"
    return None


# ── Cooldown + token→trade mapping (Redis) ──────────────────────────────────────

def _exit_on_cooldown(trade_id: int) -> bool:
    """True if an exit alert was already sent for *trade_id* within the cooldown window."""
    return _redis.get(f"exit_alert:{trade_id}") is not None


def _set_exit_cooldown(trade_id: int, minutes: int = EXIT_COOLDOWN_MINS) -> None:
    """Silence further exit alerts for *trade_id* for *minutes*."""
    _redis.setex(f"exit_alert:{trade_id}", minutes * 60, "1")


def clear_exit_cooldown(trade_id: int) -> None:
    """Drop the exit cooldown for *trade_id* (e.g. after the position is closed)."""
    _redis.delete(f"exit_alert:{trade_id}")


def resolve_trade_id(token: str) -> int | None:
    """Resolve an exit approval *token* back to its trade id via Redis. None if unknown."""
    raw = _redis.get(f"exit_meta:{token}")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


# ── Telegram formatting + send ──────────────────────────────────────────────────

def format_exit_telegram(trade, current_price: float, exit_reason: str) -> str:
    """Format an exit alert for Telegram (HTML). Tags PAPER trades."""
    paper_tag = " (PAPER)" if trade.is_paper else ""
    emoji = _EXIT_EMOJI.get(exit_reason, "📤")
    pnl = (current_price - trade.entry_price) * trade.quantity
    pnl_pct = (
        (current_price - trade.entry_price) / trade.entry_price
        if trade.entry_price
        else 0.0
    )
    days_held = (date.today() - trade.entry_date.date()).days

    lines = [
        f"📤 <b>Exit Signal — {trade.symbol}</b>{paper_tag}",
        "",
        f"Reason: {emoji} {exit_reason}",
        f"Entry: ₹{trade.entry_price:.2f} → Current: ₹{current_price:.2f} ({pnl_pct:+.1%})",
        f"P&L: {pnl:+.0f} on {trade.quantity} shares",
        f"Strategy: {trade.strategy_type} (held {days_held} days)",
    ]
    return "\n".join(lines)


async def _send_exit_alert(trade, current_price: float, exit_reason: str, token: str) -> None:
    """Send the exit alert with SELL NOW / HOLD MORE inline buttons."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.constants import ParseMode
    from core.telegram_bot import get_bot

    bot = get_bot()
    text = format_exit_telegram(trade, current_price, exit_reason)
    btn_sell = InlineKeyboardButton("✅ SELL NOW", callback_data=f"exit_sell:{token}")
    btn_hold = InlineKeyboardButton("⏭ HOLD MORE", callback_data=f"exit_hold:{token}")
    keyboard = InlineKeyboardMarkup([[btn_sell, btn_hold]])

    await bot.send_message(
        chat_id=config.TELEGRAM_CHAT_ID,
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


# ── Core monitor ────────────────────────────────────────────────────────────────

async def check_exit_conditions() -> list[dict]:
    """Check every OPEN trade for an exit; alert (with cooldown) on triggers.

    Returns:
        A list of {symbol, trade_id, exit_reason, current_price, unrealized_pnl}
        for each trade that fired an exit alert this run.
    """
    open_trades = get_open_trades()
    logger.info("Exit monitor: checking %d open trade(s)", len(open_trades))
    triggered: list[dict] = []

    for trade in open_trades:
        current_price = _get_current_price(trade.symbol)
        if current_price is None:
            logger.debug("Exit monitor: no price for %s — skipping", trade.symbol)
            continue

        exit_reason = _determine_exit_reason(trade, current_price)
        if exit_reason is None:
            continue  # still running

        if _exit_on_cooldown(trade.id):
            logger.info("Exit monitor: trade %s (%s) on cooldown", trade.id, trade.symbol)
            continue

        token = generate_token("EXIT", symbol=trade.symbol)
        _redis.setex(f"exit_meta:{token}", EXIT_COOLDOWN_MINS * 60, str(trade.id))

        await _send_exit_alert(trade, current_price, exit_reason, token)
        _set_exit_cooldown(trade.id)

        unrealized_pnl = round((current_price - trade.entry_price) * trade.quantity, 2)
        triggered.append({
            "symbol": trade.symbol,
            "trade_id": trade.id,
            "exit_reason": exit_reason,
            "current_price": current_price,
            "unrealized_pnl": unrealized_pnl,
        })
        logger.info(
            "Exit alert: %s %s @ %.2f (pnl=%.0f)",
            trade.symbol, exit_reason, current_price, unrealized_pnl,
        )

    logger.info("Exit monitor complete: %d exit alert(s)", len(triggered))
    return triggered


async def execute_exit(trade_id: int, exit_price: float) -> dict:
    """Sell an open trade and close it. Called when the user taps SELL NOW.

    Determines the exit reason from *exit_price* vs the trade's thresholds (falls back
    to MANUAL), places a paper-aware SELL, closes the trade with the actual fill, clears
    the cooldown, and sends a Telegram confirmation.

    Args:
        trade_id: id of the OPEN trade to exit.
        exit_price: reference current price (used to classify the exit reason).

    Returns:
        The close_trade summary dict, or {"status": "error", ...} on failure.
    """
    trade = get_trade(trade_id)
    if trade is None or trade.status != "OPEN":
        logger.warning("execute_exit: trade %s not open", trade_id)
        return {"status": "error", "reason": f"Trade {trade_id} not open"}

    symbol = trade.symbol
    quantity = trade.quantity
    is_paper = trade.is_paper
    exit_reason = _determine_exit_reason(trade, exit_price) or "MANUAL"

    kite = KiteClient()
    order = kite.place_order(symbol, "SELL", quantity)
    if order.get("status") != "COMPLETE":
        error = order.get("error", "Unknown error")
        await send_alert("Exit Failed", f"❌ Exit Failed — {error}", alert_type="WARNING")
        logger.error("Exit order failed: %s: %s", symbol, error)
        return {"status": "error", "reason": error}

    fill_price = order.get("fill_price") or exit_price
    summary = close_trade(trade_id, fill_price, exit_reason, order["order_id"])
    clear_exit_cooldown(trade_id)

    paper_tag = " (PAPER)" if is_paper else ""
    pnl = summary.get("pnl", 0.0)
    pnl_pct = summary.get("pnl_pct", 0.0)
    await send_alert(
        "Position Closed",
        (
            f"✅ *Position Closed{paper_tag}*\n"
            f"{symbol} | SOLD {quantity} @ ₹{fill_price:.2f}\n"
            f"P&L: {pnl:+.0f} ({pnl_pct:+.1%})\n"
            f"Reason: {exit_reason}"
        ),
        alert_type="SUCCESS",
    )
    logger.info(
        "Position closed: %s SOLD %d @ %.2f pnl=%.0f reason=%s (paper=%s)",
        symbol, quantity, fill_price, pnl, exit_reason, is_paper,
    )
    return summary


async def handle_exit_hold(token: str) -> dict:
    """User tapped HOLD MORE — silence this trade for HOLD_COOLDOWN_MINS and confirm."""
    trade_id = resolve_trade_id(token)
    if trade_id is None:
        return {"status": "error", "reason": "Exit token not found"}
    trade = get_trade(trade_id)
    symbol = trade.symbol if trade else str(trade_id)
    _set_exit_cooldown(trade_id, minutes=HOLD_COOLDOWN_MINS)
    logger.info("Exit HOLD: trade %s (%s) held for %d min", trade_id, symbol, HOLD_COOLDOWN_MINS)
    await send_alert("Holding Position", f"⏸ Holding {symbol}", alert_type="INFO")
    return {"status": "ok", "symbol": symbol, "trade_id": trade_id}


# ── Market-hours gate (mirrors agent/stoploss.run_with_market_check) ─────────────

async def run_with_market_check() -> list[dict] | None:
    """Run the exit monitor only inside 09:15–15:30 IST Mon–Fri; else return None."""
    now = datetime.now(IST)

    if now.weekday() >= 5:  # weekend
        logger.info("Exit monitor: weekend, skipping")
        return None

    open_h, open_m = map(int, MARKET_OPEN.split(":"))
    close_h, close_m = map(int, MARKET_CLOSE.split(":"))
    market_open = now.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
    market_close = now.replace(hour=close_h, minute=close_m, second=0, microsecond=0)

    if not (market_open <= now <= market_close):
        logger.info("Exit monitor: outside market hours (%s IST), skipping", now.strftime("%H:%M"))
        return None

    return await check_exit_conditions()
