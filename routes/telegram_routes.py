"""
Telegram bot webhook routes.
"""
import logging
from typing import Any

from fastapi import APIRouter, Request

from core.approval import mark_approved, mark_skipped, validate_token
from core.telegram_bot import get_bot, send_alert

logger = logging.getLogger(__name__)

router = APIRouter()


async def _answer_callback_query(query_id: str, text: str) -> None:
    """Dismiss the inline button loading spinner and surface a toast to the user."""
    bot = get_bot()
    await bot.answer_callback_query(callback_query_id=query_id, text=text)


@router.post("/webhook")
async def telegram_webhook(request: Request) -> dict:
    """
    Receive Telegram update payloads. Routes callback_query actions to the
    approval engine; plain messages are logged and ignored.
    """
    payload: Any = await request.json()
    redis = request.app.state.redis

    if "callback_query" in payload:
        cq = payload["callback_query"]
        callback_data: str = cq.get("data", "")
        query_id: str = cq["id"]

        parts = callback_data.split(":", 1)
        if len(parts) != 2:
            logger.warning("Malformed callback_data: %s", callback_data)
            return {"status": "ok"}

        action, token = parts

        if action == "approve":
            result = validate_token(token)
            if not result["valid"]:
                await _answer_callback_query(query_id, f"❌ {result['reason']}")
            else:
                mark_approved(token)
                redis.set(f"approved:{token}", "1")
                await _answer_callback_query(query_id, "✅ Approved! Order will be placed shortly.")
                await send_alert(
                    "Order Approved",
                    f"Token {token[:8]}... approved. Execution in progress.",
                    alert_type="SUCCESS",
                )

        elif action == "execute":
            await _answer_callback_query(query_id, "⚙️ Placing order…")
            from routes.approval_routes import handle_signal_execution
            order_result = await handle_signal_execution(token)
            if order_result.get("status") != "ok":
                logger.warning("Signal execution failed: %s", order_result.get("reason"))

        elif action == "skip":
            result = validate_token(token)
            if not result["valid"]:
                await _answer_callback_query(query_id, f"❌ {result['reason']}")
            else:
                mark_skipped(token)
                await _answer_callback_query(query_id, "⏭ Skipped.")
                await send_alert(
                    "Signal Skipped",
                    f"Signal {token[:8]}… skipped by user.",
                    alert_type="INFO",
                )

        else:
            logger.warning("Unknown callback action: %s", action)

    elif "message" in payload:
        logger.info("Telegram update type: message — ignored")
    else:
        update_type = next(iter(payload.keys()), "unknown")
        logger.info("Telegram update type: %s", update_type)

    return {"status": "ok"}
