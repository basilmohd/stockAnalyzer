"""
Telegram messaging layer — all outbound messages and approval requests.
All functions are async and communicate with the real Telegram Bot API.
"""
import logging
from datetime import datetime

import pytz
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DEFAULT_SL_PCT

logger = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")

_ALERT_EMOJI: dict[str, str] = {
    "INFO": "ℹ️",
    "BUY": "🟢",
    "SELL": "🔴",
    "URGENT": "🚨",
    "SUCCESS": "✅",
    "WARNING": "⚠️",
}

_ACTION_EMOJI: dict[str, str] = {
    "BUY": "🟢",
    "SELL": "🔴",
    "REDUCE": "🟡",
    "EXIT": "🚨",
}


def get_bot() -> Bot:
    """Return a Bot instance using the configured token."""
    return Bot(token=TELEGRAM_BOT_TOKEN)


async def send_message(text: str, parse_mode: str = "HTML") -> bool:
    """Send a plain text message to the configured chat.

    Returns True on success, False on any exception.
    """
    try:
        bot = get_bot()
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=parse_mode,
        )
        logger.info("Telegram: message sent (%d chars)", len(text))
        return True
    except Exception as exc:
        logger.error("Telegram send_message failed: %s", exc)
        return False


async def send_alert(
    title: str,
    body: str,
    alert_type: str = "INFO",
) -> bool:
    """Send a formatted alert message.

    alert_type: INFO | BUY | SELL | URGENT | SUCCESS | WARNING
    """
    emoji = _ALERT_EMOJI.get(alert_type.upper(), "ℹ️")
    now_ist = datetime.now(IST).strftime("%d %b %Y %H:%M IST")
    text = (
        f"{emoji} <b>{title}</b>\n"
        f"\n"
        f"{body}\n"
        f"\n"
        f"<i>{now_ist}</i>"
    )
    return await send_message(text)


async def send_approval_request(
    token: str,
    title: str,
    body: str,
    approve_label: str = "✅ APPROVE",
    skip_label: str = "❌ SKIP",
    expiry_mins: int = 30,
) -> bool:
    """Send an inline-keyboard approval request message."""
    btn_approve = InlineKeyboardButton(approve_label, callback_data=f"approve:{token}")
    btn_skip = InlineKeyboardButton(skip_label, callback_data=f"skip:{token}")
    keyboard = InlineKeyboardMarkup([[btn_approve, btn_skip]])

    text = (
        f"📡 <b>{title}</b>\n"
        f"\n"
        f"{body}\n"
        f"\n"
        f"⏱ <i>Expires in {expiry_mins} minutes</i>"
    )
    try:
        bot = get_bot()
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
        logger.info("Telegram: approval request sent (token=%s)", token)
        return True
    except Exception as exc:
        logger.error("Telegram send_approval_request failed: %s", exc)
        return False


async def send_morning_briefing(context: dict) -> bool:
    """Send the morning portfolio briefing derived from build_claude_context()."""
    today = datetime.now(IST).strftime("%a %d %b")

    portfolio: dict = context.get("portfolio", {})
    total_value: float = portfolio.get("total_value", 0)
    total_pnl_pct: float = portfolio.get("total_pnl_pct", 0)
    holdings: list[dict] = context.get("holdings", [])
    risk_flags: list[str] = context.get("risk_flags", [])

    # Build holdings lines
    holding_lines: list[str] = []
    for h in holdings:
        circle = "🟢" if h.get("pnl_pct", 0) >= 0 else "🔴"
        symbol = h.get("symbol", "?")
        pnl_pct = h.get("pnl_pct", 0.0)
        sl_status = h.get("sl_status", "OK")
        holding_lines.append(f"{circle} {symbol} {pnl_pct:+.1f}% | SL: {sl_status}")

    holdings_block = "\n".join(holding_lines) if holding_lines else "No holdings data."

    # Build risk flags block
    if risk_flags:
        flags_block = "\n".join(f"• {f}" for f in risk_flags)
    else:
        flags_block = "None — portfolio looks healthy"

    text = (
        f"☀️ <b>MORNING BRIEFING</b> — {today}\n"
        f"\n"
        f"📊 Portfolio: ₹{total_value:,.0f}\n"
        f"Overall P&amp;L: {total_pnl_pct:+.1f}%\n"
        f"\n"
        f"<b>Holdings ({len(holdings)} stocks)</b>\n"
        f"{holdings_block}\n"
        f"\n"
        f"⚠️ <b>RISK FLAGS</b>\n"
        f"{flags_block}\n"
        f"\n"
        f"<i>Next signal scan: 11:00 AM IST</i>"
    )
    return await send_message(text)


def _confidence_bar(confidence: float, width: int = 10) -> str:
    """Return a filled/empty block bar representing confidence (0.0–1.0)."""
    filled = round(confidence * width)
    return "█" * filled + "░" * (width - filled)


async def send_signal_alert(
    symbol: str,
    action: str,
    confidence: float,
    reasoning: str,
    entry_price: float,
    target_price: float,
    stop_loss: float,
    suggested_qty: int,
    token: str,
    indicators: dict,
) -> bool:
    """Send a trade signal with an inline approval request.

    action: BUY | SELL | REDUCE | EXIT
    indicators dict keys: rsi, macd, above_200dma (bool), volume_ratio (float)
    """
    emoji = _ACTION_EMOJI.get(action.upper(), "📊")
    bar = _confidence_bar(confidence)

    rsi = indicators.get("rsi", "N/A")
    macd = indicators.get("macd", "N/A")
    above_200dma = indicators.get("above_200sma", False)
    volume_ratio = indicators.get("volume_ratio", 0.0)

    dma_symbol = "✓" if above_200dma else "✗"

    gain_pct = ((target_price - entry_price) / entry_price) * 100
    loss_pct = ((stop_loss - entry_price) / entry_price) * 100

    body = (
        f"📊 RSI: {rsi} | MACD: {macd}\n"
        f"   Above 200DMA: {dma_symbol} | Vol: {volume_ratio:.1f}x avg\n"
        f"\n"
        f"💡 {reasoning}\n"
        f"\n"
        f"Entry: ₹{entry_price:,.0f}\n"
        f"Target: ₹{target_price:,.0f} ({gain_pct:+.1f}%)\n"
        f"Stop Loss: ₹{stop_loss:,.0f} ({loss_pct:+.1f}%)\n"
        f"Qty: {suggested_qty} shares (~₹{entry_price * suggested_qty:,.0f})"
    )

    title = (
        f"{emoji} {action} — {symbol}\n"
        f"Confidence: {confidence * 100:.0f}% {bar}"
    )

    return await send_approval_request(
        token=token,
        title=title,
        body=body,
        expiry_mins=30,
    )


async def send_sl_breach_alert(
    symbol: str,
    entry_price: float,
    current_price: float,
    pnl_pct: float,
    quantity: int,
    token: str,
) -> bool:
    """Send an urgent stop-loss breach alert with an approval request."""
    est_exit_value = current_price * quantity
    est_locked_loss = (current_price - entry_price) * quantity

    body = (
        f"EXIT — <b>{symbol}</b>\n"
        f"Entry: ₹{entry_price:,.0f} → Current: ₹{current_price:,.0f}\n"
        f"Loss: {pnl_pct:+.1f}% ← BREACHED {abs(DEFAULT_SL_PCT):.0f}% SL threshold\n"
        f"\n"
        f"⚠️ Defined stop-loss level breached.\n"
        f"\n"
        f"Sell {quantity} shares @ MARKET\n"
        f"Est. exit value: ₹{est_exit_value:,.0f}\n"
        f"Est. locked loss: ₹{est_locked_loss:,.0f}"
    )

    return await send_approval_request(
        token=token,
        title="🚨 URGENT — STOP LOSS BREACH",
        body=body,
        approve_label="🚨 EXECUTE EXIT",
        skip_label="⏸ HOLD / OVERRIDE",
        expiry_mins=15,
    )


def _score_bar(score: int, width: int = 10) -> str:
    """Return a filled/empty block bar for a 0–100 score."""
    filled = round((score / 100) * width)
    return "█" * filled + "░" * (width - filled)


async def send_weekly_health_report(
    score: int,
    breakdown: dict,
    portfolio_summary: dict,
    recommendations: list[str],
) -> bool:
    """Send the weekly portfolio health report."""
    diversification = breakdown.get("diversification", 0)
    momentum = breakdown.get("momentum", 0)
    risk_management = breakdown.get("risk_management", 0)
    quality = breakdown.get("quality", 0)

    total_value: float = portfolio_summary.get("total_value", 0)
    total_pnl_pct: float = portfolio_summary.get("total_pnl_pct", 0)

    rec_lines = "\n".join(
        f"{i + 1}. {rec}" for i, rec in enumerate(recommendations)
    )

    text = (
        f"📊 <b>WEEKLY HEALTH REPORT</b>\n"
        f"\n"
        f"🏆 Score: {score}/100\n"
        f"\n"
        f"<b>Breakdown</b>\n"
        f"Diversification  {_score_bar(diversification)} {diversification}\n"
        f"Momentum         {_score_bar(momentum)} {momentum}\n"
        f"Risk Mgmt        {_score_bar(risk_management)} {risk_management}\n"
        f"Quality          {_score_bar(quality)} {quality}\n"
        f"\n"
        f"📈 Portfolio: ₹{total_value:,.0f} | P&amp;L: {total_pnl_pct:+.1f}%\n"
        f"\n"
        f"<b>Top {len(recommendations)} Actions Next Week</b>\n"
        f"{rec_lines}"
    )
    return await send_message(text)
