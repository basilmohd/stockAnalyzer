"""Signal generation engine — AI-driven BUY/SELL/REDUCE/EXIT for NSE holdings."""
import json
from datetime import datetime, timezone

import config
from agent.strategy import classify_strategy, validate_entry
from core.approval import generate_token
from core.db import get_db
from core.redis_client import RedisClient
from core.telegram_bot import get_bot
from data.news import get_news_sentiment_all_holdings
from data.portfolio import build_claude_context
from data.technicals import IndicatorResult, get_technicals_for_holdings
from models.action_log import ActionLog
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

_STRATEGY_EMOJI: dict[str, str] = {
    "MEAN_REVERSION": "🔄",
    "SWING_TRADE": "🏹",
    "TREND_FOLLOW": "📈",
    "EXIT_SIGNAL": "📤",
}

SL_BY_STRATEGY: dict[str, float | None] = {
    "MEAN_REVERSION": 0.05,
    "SWING_TRADE": 0.04,
    "TREND_FOLLOW": 0.05,
    "EXIT_SIGNAL": None,
}

TARGET_BY_STRATEGY: dict[str, float | None] = {
    "MEAN_REVERSION": 0.08,
    "SWING_TRADE": 0.07,
    "TREND_FOLLOW": 0.12,
    "EXIT_SIGNAL": None,
}


def _indicator_to_technicals(ind: IndicatorResult) -> dict:
    """Convert IndicatorResult to the flat technicals dict expected by strategy functions."""
    return {
        "rsi": ind.rsi,
        "sma_50": ind.sma_50,
        "sma_200": ind.sma_200,
        "current_price": ind.last_close,
        "macd": {
            "macd": ind.macd,
            "histogram": round(ind.macd - ind.macd_signal, 4),
        },
        "volume_ratio": ind.volume_ratio,
        "pct_from_52w_high": ind.price_vs_52w_high_pct,
        "above_200dma": ind.above_200sma,
    }


def _write_action_log(
    signal: dict,
    strategy_type: str,
    action_taken: str,
    current_price: float,
    suggested_sl: float | None,
    suggested_target: float | None,
    rejection_reason: str | None = None,
    signal_id: int | None = None,
    telegram_sent_at: datetime | None = None,
) -> None:
    """Persist an ActionLog record to SQLite."""
    with get_db() as db:
        record = ActionLog(
            signal_id=signal_id,
            symbol=signal.get("symbol", ""),
            strategy_type=strategy_type,
            signal_action=signal.get("action", "").upper(),
            confidence=float(signal.get("confidence", 0.0)),
            entry_price=current_price,
            suggested_qty=signal.get("suggested_quantity"),
            suggested_sl=suggested_sl,
            suggested_target=suggested_target,
            action_taken=action_taken,
            rejection_reason=rejection_reason,
            telegram_sent_at=telegram_sent_at,
        )
        db.add(record)
        db.commit()


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

    Includes strategy type, target, and stop-loss prices when available.
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
    strategy_type = signal.get("strategy_type", "")
    suggested_target = signal.get("suggested_target")
    suggested_sl = signal.get("suggested_sl")
    current_price = signal.get("current_price", 0.0)

    action_emoji = _ACTION_EMOJI.get(action, "📊")
    strategy_emoji = _STRATEGY_EMOJI.get(strategy_type, "")
    filled = round(confidence * 5)
    bar = "█" * filled + "░" * (5 - filled)
    confidence_pct = round(confidence * 100)

    rsi_str = f"{rsi:.1f}" if isinstance(rsi, (int, float)) else str(rsi)
    macd_str = f"{macd_histogram:.2f}" if isinstance(macd_histogram, (int, float)) else str(macd_histogram)

    lines = [
        f"🔔 <b>Signal Alert — {symbol}</b>",
        "",
    ]

    if strategy_type:
        lines.append(f"Strategy: {strategy_emoji} {strategy_type}")

    lines += [
        f"Action: {action_emoji} <b>{action}</b>",
        f"Confidence: {bar} {confidence_pct}%",
        "",
        f"📊 RSI: {rsi_str} | MACD: {macd_str}",
        f"📰 News: {news_sentiment}",
        "",
    ]

    if suggested_target and current_price:
        target_pct = round(((suggested_target - current_price) / current_price) * 100, 1)
        lines.append(f"🎯 Target: ₹{suggested_target:.2f} (+{target_pct}%)")

    if suggested_sl and current_price:
        sl_pct = round(((current_price - suggested_sl) / current_price) * 100, 1)
        lines.append(f"🛡 Stop Loss: ₹{suggested_sl:.2f} (-{sl_pct}%)")

    if suggested_target or suggested_sl:
        lines.append("")

    lines += [
        f"💡 {reason}",
        f"Urgency: {urgency}",
    ]

    return "\n".join(lines)


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
    """Orchestrate the full signal pipeline: scan → classify → validate → alert → cache.

    Each signal is classified into a strategy, validated against entry rules, and either
    rejected (AUTO_REJECTED ActionLog, no Telegram) or enriched with SL/target prices
    before being sent as a Telegram approval request (PENDING ActionLog).

    Returns summary dict: {scanned, filtered, validated, rejected, alerts_sent, run_at}.
    Caches the summary in Redis under 'signals:last_run' with 2-hour TTL.
    """
    raw = run_signal_scan()
    filtered = filter_signals(raw)

    technicals_map = get_technicals_for_holdings()
    validated_signals: list[dict] = []
    rejected_count = 0

    for signal in filtered:
        symbol = signal.get("symbol", "")

        ind = technicals_map.get(symbol)
        if ind is None or isinstance(ind, dict):
            logger.debug("No valid technicals for %s — skipping strategy check", symbol)
            validated_signals.append(signal)
            continue

        technicals = _indicator_to_technicals(ind)
        current_price = technicals["current_price"]

        strategy = classify_strategy(signal, technicals)

        if strategy == "NO_TRADE":
            logger.debug("%s classified NO_TRADE — skipping silently", symbol)
            continue

        passed, reason = validate_entry(strategy, signal, technicals)

        if not passed:
            rejected_count += 1
            logger.info("%s rejected: %s", symbol, reason)
            _write_action_log(
                signal=signal,
                strategy_type=strategy,
                action_taken="AUTO_REJECTED",
                current_price=current_price,
                suggested_sl=None,
                suggested_target=None,
                rejection_reason=reason,
            )
            continue

        sl_pct = SL_BY_STRATEGY.get(strategy)
        target_pct = TARGET_BY_STRATEGY.get(strategy)
        suggested_sl = round(current_price * (1 - sl_pct), 2) if sl_pct else None
        suggested_target = round(current_price * (1 + target_pct), 2) if target_pct else None

        enriched = dict(signal)
        enriched["strategy_type"] = strategy
        enriched["suggested_sl"] = suggested_sl
        enriched["suggested_target"] = suggested_target
        enriched["current_price"] = current_price
        validated_signals.append(enriched)

    await send_signal_alerts(validated_signals)

    # Write PENDING ActionLog for every alert sent (signal_id populated after send)
    now = datetime.now(timezone.utc)
    for signal in validated_signals:
        symbol = signal.get("symbol", "")
        ind = technicals_map.get(symbol)
        current_price = signal.get("current_price", 0.0)
        if ind and not isinstance(ind, dict) and not current_price:
            current_price = ind.last_close
        _write_action_log(
            signal=signal,
            strategy_type=signal.get("strategy_type", ""),
            action_taken="PENDING",
            current_price=current_price,
            suggested_sl=signal.get("suggested_sl"),
            suggested_target=signal.get("suggested_target"),
            telegram_sent_at=now,
        )

    result = {
        "scanned": len(raw),
        "filtered": len(filtered),
        "validated": len(validated_signals),
        "rejected": rejected_count,
        "alerts_sent": len(validated_signals),
        "run_at": datetime.now().isoformat(),
    }

    _redis.setex("signals:last_run", 7200, json.dumps(result))
    logger.info("Signal pipeline complete: %s", result)
    return result
