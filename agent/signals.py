"""Signal generation engine — AI-driven BUY/SELL/REDUCE/EXIT for NSE holdings."""
import json
from datetime import datetime

import config
from core.approval import generate_token
from core.db import get_db
from core.redis_client import RedisClient
from core.telegram_bot import get_bot
from data.news import get_news_sentiment_all_holdings
from data.portfolio import build_claude_context
from data.technicals import get_technicals_for_holdings
from models.signal import Signal

from core.logger import get_logger
logger = get_logger(__name__)
_redis = RedisClient(config.REDIS_URL)

_ACTION_EMOJI: dict[str, str] = {
    "BUY": "🟢",
    "SELL": "🔴",
    "REDUCE": "🟡",
    "EXIT": "⛔",
}


def run_signal_scan() -> list[dict]:
    """Fetch portfolio, technicals, and news; merge per symbol; call AI for signals.

    Returns the raw signal list from the AI (unfiltered).
    """
    portfolio_context = build_claude_context()
    technicals = get_technicals_for_holdings()
    news = get_news_sentiment_all_holdings()

    holdings = portfolio_context.get("holdings", [])
    merged: list[dict] = []

    for h in holdings:
        symbol: str = h["symbol"]
        entry = dict(h)

        ind = technicals.get(symbol)
        if ind and not isinstance(ind, dict):
            entry["rsi"] = ind.rsi
            entry["macd"] = ind.macd
            entry["macd_signal"] = ind.macd_signal
            entry["macd_histogram"] = round(ind.macd - ind.macd_signal, 2)
            entry["sma_50"] = ind.sma_50
            entry["sma_200"] = ind.sma_200
            entry["above_200sma"] = ind.above_200sma
            entry["volume_ratio"] = ind.volume_ratio
        elif isinstance(ind, dict):
            entry["indicator_error"] = ind.get("error", "unknown")

        news_data = news.get(symbol, {})
        entry["news_sentiment"] = news_data.get("sentiment_label", "NEUTRAL")
        entry["news_score"] = news_data.get("overall_score", 0)

        merged.append(entry)

    from core.claude_client import generate_signals
    signals = generate_signals(merged)
    logger.info("Signal scan complete: %d raw signals for %d holdings", len(signals), len(merged))
    return signals


def filter_signals(signals: list[dict]) -> list[dict]:
    """Apply confidence gate, drop HOLD, and deduplicate per symbol.

    Keeps only signals with confidence >= CONFIDENCE_THRESHOLD, action != HOLD,
    and the highest-confidence entry per symbol when duplicates exist.
    """
    filtered = [
        s for s in signals
        if s.get("confidence", 0.0) >= config.CONFIDENCE_THRESHOLD
        and s.get("action", "").upper() != "HOLD"
    ]

    best: dict[str, dict] = {}
    for s in filtered:
        sym = s.get("symbol", "")
        if sym not in best or s.get("confidence", 0.0) > best[sym].get("confidence", 0.0):
            best[sym] = s

    result = list(best.values())
    logger.info("Filtered to %d actionable signals (from %d raw)", len(result), len(signals))
    return result


def store_signals(signals: list[dict]) -> None:
    """Persist signals to SQLite as Signal ORM records. Logs each stored entry."""
    with get_db() as db:
        for signal in signals:
            record = Signal(
                symbol=signal.get("symbol", ""),
                action=signal.get("action", ""),
                confidence=float(signal.get("confidence", 0.0)),
                reasoning=signal.get("reason", ""),
                suggested_qty=signal.get("suggested_quantity"),
                status="PENDING",
            )
            db.add(record)
            logger.info(
                "Storing signal: %s %s conf=%.2f urgency=%s",
                record.symbol,
                record.action,
                record.confidence,
                signal.get("urgency", "MEDIUM"),
            )
        db.commit()


def _store_single_signal(signal: dict) -> int:
    """Persist one signal to SQLite and return its id."""
    with get_db() as db:
        record = Signal(
            symbol=signal.get("symbol", ""),
            action=signal.get("action", ""),
            confidence=float(signal.get("confidence", 0.0)),
            reasoning=signal.get("reason", ""),
            suggested_qty=signal.get("suggested_quantity"),
            status="PENDING",
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        logger.info(
            "Signal stored: %s %s id=%d", record.symbol, record.action, record.id
        )
        return record.id


def format_signal_telegram(signal: dict) -> str:
    """Format a single signal as an HTML string for Telegram.

    Confidence bar uses 5 filled/empty blocks (e.g. ████░ 80%).
    """
    symbol = signal.get("symbol", "?")
    action = signal.get("action", "?").upper()
    confidence = float(signal.get("confidence", 0.0))
    reason = signal.get("reason", "")
    rsi = signal.get("rsi", "N/A")
    macd_histogram = signal.get("macd_histogram", "N/A")
    news_sentiment = signal.get("news_sentiment", "NEUTRAL")
    urgency = signal.get("urgency", "MEDIUM")

    emoji = _ACTION_EMOJI.get(action, "📊")
    filled = round(confidence * 5)
    bar = "█" * filled + "░" * (5 - filled)
    confidence_pct = round(confidence * 100)

    rsi_str = f"{rsi:.1f}" if isinstance(rsi, (int, float)) else str(rsi)
    macd_str = f"{macd_histogram:.2f}" if isinstance(macd_histogram, (int, float)) else str(macd_histogram)

    return (
        f"🔔 <b>Signal Alert — {symbol}</b>\n"
        f"\n"
        f"Action: {emoji} <b>{action}</b>\n"
        f"Confidence: {bar} {confidence_pct}%\n"
        f"\n"
        f"📊 RSI: {rsi_str} | MACD: {macd_str}\n"
        f"📰 News: {news_sentiment}\n"
        f"\n"
        f"💡 {reason}\n"
        f"\n"
        f"Urgency: {urgency}"
    )


async def send_signal_alerts(signals: list[dict]) -> None:
    """Send a Telegram approval message for each signal, then persist to SQLite.

    Stores each signal to DB first to obtain its id, then creates a linked approval
    token. Uses execute:{token} callback (separate from SL approve:{token} flow).
    """
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.constants import ParseMode

    bot = get_bot()
    sent_count = 0

    for signal in signals:
        symbol = signal.get("symbol", "?")
        try:
            text = format_signal_telegram(signal)

            signal_id = _store_single_signal(signal)
            token = generate_token("SIGNAL", signal_id=signal_id)

            btn_execute = InlineKeyboardButton("✅ EXECUTE", callback_data=f"execute:{token}")
            btn_skip = InlineKeyboardButton("⏭ SKIP", callback_data=f"skip:{token}")
            keyboard = InlineKeyboardMarkup([[btn_execute, btn_skip]])

            await bot.send_message(
                chat_id=config.TELEGRAM_CHAT_ID,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
            sent_count += 1
            logger.info("Signal alert sent: %s (signal_id=%d)", symbol, signal_id)
        except Exception as exc:
            logger.error("Failed to send signal alert for %s: %s", symbol, exc)

    logger.info("Signal alerts sent: %d / %d", sent_count, len(signals))


async def run_signal_pipeline() -> dict:
    """Orchestrate the full signal pipeline: scan → filter → alert → cache result.

    Returns summary dict: {scanned, filtered, alerts_sent, run_at}.
    Caches the summary in Redis under 'signals:last_run' with 2-hour TTL.
    """
    raw = run_signal_scan()
    filtered = filter_signals(raw)
    await send_signal_alerts(filtered)

    result = {
        "scanned": len(raw),
        "filtered": len(filtered),
        "alerts_sent": len(filtered),
        "run_at": datetime.now().isoformat(),
    }

    _redis.setex("signals:last_run", 7200, json.dumps(result))
    logger.info("Signal pipeline complete: %s", result)
    return result
